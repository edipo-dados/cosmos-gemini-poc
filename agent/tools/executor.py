"""ToolExecutor: único caminho de execução das 7 ferramentas (docs/ARCHITECTURE.md, seção 5.3).

Ordem: 1) esquema Pydantic, antes do gateway; 2) autorização no Cosmos (lock curto); 3) domínio e execução (fora do lock),
só depois do `allow`; 4) `ToolAdapter.execute` para toda chamada autorizada; 5) auditoria em `finally`.
O Gemini e o cliente HTTP nunca recebem acesso a banco nem executam SQL: só pedem uma ferramenta pelo nome.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.services.audit import AuditStore
from app.services.query_engine import QueryEngine, QueryEngineError

from .cosmos_gateway import CosmosRuntime
from .errors import ToolError
from .schemas import ARG_MODELS, HTTP_STATUS
from .semantic_reader import SemanticReader

log = logging.getLogger("poc.tools")
REJECTED_CODES = {"unknown_metric", "dimension_not_allowed", "invalid_dimension_combination", "missing_required_dimension",
                  "invalid_filter", "invalid_date_range", "invalid_order", "invalid_limit", "query_not_found",
                  "no_sql_available", "invalid_arguments", "tool_not_authorized"}


@dataclass
class ToolOutcome:
    tool: str
    status: str                      # ok | rejected | error
    http_status: int
    payload: dict                    # o que o Gemini e o cliente HTTP recebem (sem SQL)
    query_id: str | None = None
    error_code: str | None = None
    audit_row: dict | None = None    # registro completo (com SQL), usado para montar a evidência da resposta
    episode_id: str | None = None
    decision_id: str | None = None


@dataclass
class _Result:
    payload: dict
    fields: dict = field(default_factory=dict)


def _error_payload(code: str, message: str, query_id: str | None, details: dict | None = None) -> dict:
    err: dict = {"code": code, "message": message}
    if details:
        err["details"] = details
    if query_id:
        err["query_id"] = query_id
    return {"error": err}


class ToolExecutor:
    def __init__(self, runtime: CosmosRuntime, reader: SemanticReader, engine: QueryEngine, audit: AuditStore):
        self.runtime, self.reader, self.engine, self.audit = runtime, reader, engine, audit

    # ---- API pública ----
    def execute(self, tool: str, raw_args: object, user_id: str, turn_id: str | None = None,
                episode_id: str | None = None) -> ToolOutcome:
        if tool not in ARG_MODELS:
            log.warning("ferramenta desconhecida solicitada: %.64r", tool)
            return ToolOutcome(tool, "rejected", 404, _error_payload("unknown_tool", f"Ferramenta '{tool}' não existe.", None),
                               error_code="unknown_tool")
        qid = str(uuid.uuid4())
        row = {"query_id": qid, "turn_id": turn_id, "user_id": user_id, "tool_name": tool, "cosmos_episode_id": episode_id}
        started = time.perf_counter()
        # 1) esquema, antes do gateway: sem new_attempt e sem decisão no Cosmos
        try:
            if not isinstance(raw_args, dict):
                raise ToolError("invalid_arguments", "Os argumentos devem ser um objeto JSON.")
            try:
                args = ARG_MODELS[tool].model_validate(raw_args)
            except ValidationError as exc:
                first = exc.errors()[0]
                where = ".".join(str(p) for p in first["loc"]) or "argumentos"
                raise ToolError("invalid_arguments", f"Argumento inválido em '{where}': {first['msg']}") from exc
        except ToolError as err:
            return self._finish(tool, row, started, err=err, decision_id=None)
        if tool == "query_metric":
            row.update(metric=args.metric, dimensions=args.dimensions, row_limit=args.limit)
        elif tool in ("explain_metric", "list_dimensions"):
            row["metric"] = args.metric
        # 2) episódio e autorização
        own_episode = episode_id is None
        authorized = None
        try:
            if own_episode:
                episode_id = self.runtime.open_episode(f"tool:{tool}")
                row["cosmos_episode_id"] = episode_id
            authorized = self.runtime.authorize(episode_id, tool, qid, args.model_dump(mode="json"))
        except ToolError as err:
            if own_episode and episode_id:
                self.runtime.close_episode(episode_id, ok=False)
            return self._finish(tool, row, started, err=err, decision_id=None)
        decision_id = authorized.decision.decision_id
        # 3) domínio e execução, fora do lock
        result: _Result | None = None
        err: ToolError | None = None
        try:
            result = self._run(tool, args, qid, user_id)
        except (ToolError, QueryEngineError) as exc:
            err = exc if isinstance(exc, ToolError) else ToolError(exc.code, exc.message, exc.details)
        except Exception as exc:  # noqa: BLE001
            log.error("falha inesperada em %s", tool, exc_info=True)
            err = ToolError("internal_error", f"Falha interna: {type(exc).__name__}")
        # 4) registro no Cosmos: toda chamada autorizada tem um runtime.adapter.result
        summary = {"row_count": (result.fields.get("row_count") or 0) if result else 0,
                   "status": "ok" if result else ("rejected" if err.code in REJECTED_CODES else "error")}
        self.runtime.put_pending(qid, summary)
        try:
            self.runtime.record(authorized)
        except Exception as exc:  # noqa: BLE001
            log.error("falha ao registrar resultado no Cosmos: %s", type(exc).__name__, exc_info=True)
            result, err = None, ToolError("cosmos_runtime_unavailable", "Runtime do Cosmos indisponível.")
        finally:
            self.runtime.drop_pending(qid)
            if own_episode:
                self.runtime.close_episode(episode_id, ok=err is None)
        return self._finish(tool, row, started, result=result, err=err, decision_id=decision_id)

    # ---- auditoria (bloco final) ----
    def _finish(self, tool: str, row: dict, started: float, result: _Result | None = None, err: ToolError | None = None,
                decision_id: str | None = None) -> ToolOutcome:
        qid = row["query_id"]
        row["cosmos_decision_id"] = decision_id
        row["duration_ms"] = int((time.perf_counter() - started) * 1000)
        if result is not None:
            row.update(result.fields)
            row["status"] = "ok"
            payload, code, http = {**result.payload, "query_id": qid}, None, 200
        else:
            code = err.code
            row.update(err_fields(err))
            row["status"] = "rejected" if code in REJECTED_CODES else "error"
            payload, http = _error_payload(code, err.message, qid, err.details), HTTP_STATUS.get(code, 500)
        row["error_code"] = code
        try:
            self.audit.insert_query(row)
        except Exception:  # noqa: BLE001
            log.error("falha ao gravar auditoria de %s (query_id=%s)", tool, qid, exc_info=True)
            payload, http, code = _error_payload("audit_failed", "Falha ao gravar a auditoria; o resultado foi descartado.", qid), 500, "audit_failed"
            row["status"] = "error"
        log.info("tool=%s query_id=%s status=%s code=%s", tool, qid, row["status"], code)
        return ToolOutcome(tool, row["status"], http, payload, qid, code, row, row.get("cosmos_episode_id"), decision_id)

    # ---- domínio ----
    def _run(self, tool: str, args, qid: str, user_id: str) -> _Result:
        return getattr(self, f"_tool_{tool}")(args, qid, user_id)

    def _require_metric(self, name: str) -> None:
        """Existência pelo catálogo YAML (fonte de verdade); a explicação vem do grafo do Cosmos."""
        names = sorted(self.engine.catalog.metrics)
        if name not in names:
            close = [n for n in names if name in n or n in name]
            raise ToolError("unknown_metric", f"Métrica '{name}' não existe no catálogo.",
                            {"available_metrics": names, "suggestions": close})

    def _tool_search_concepts(self, args, qid, user_id):
        results = self.reader.search(args.query)
        return _Result({"results": results, "count": len(results)}, {"row_count": len(results)})

    def _tool_explain_metric(self, args, qid, user_id):
        self._require_metric(args.metric)
        info = self.reader.explain(args.metric)
        return _Result(info, {"metric": args.metric, "catalog_version": self.engine.catalog.version, "row_count": 1,
                              "evidence": {"cosmos_node_id": info["cosmos_node_id"], "metric_version": info["version"]}})

    def _tool_list_metrics(self, args, qid, user_id):
        with self.engine.executor.connection() as con:
            ctx = self.engine.executor.context(con, self.engine.catalog)
        metrics = self.reader.list_metrics()
        lo, hi = ctx.data_range
        payload = {"metrics": metrics, "data_range": {"from": lo.isoformat(), "to": hi.isoformat()},
                   "data_as_of": self.engine.default_as_of.isoformat(), "etl_run_id": ctx.etl_run_id}
        return _Result(payload, {"row_count": len(metrics), "etl_run_id": ctx.etl_run_id,
                                 "catalog_version": self.engine.catalog.version})

    def _tool_list_dimensions(self, args, qid, user_id):
        if args.metric is not None:
            self._require_metric(args.metric)
        dims = self.reader.list_dimensions(args.metric)
        return _Result({"metric": args.metric, "dimensions": dims}, {"metric": args.metric, "row_count": len(dims)})

    def _tool_query_metric(self, args, qid, user_id):
        req = args.model_dump(mode="json")
        res = self.engine.query(req)
        payload = {k: v for k, v in res.items() if k not in ("sql", "sql_params", "query_id")}  # SQL só por show_sql
        fields = {"metric": res["metric"], "dimensions": req["dimensions"],
                  "filters": {"requested": req["filters"], "applied": res["filters_applied"], "date_from": req["date_from"],
                              "date_to": req["date_to"], "order_by": req["order_by"]},
                  "row_limit": req["limit"], "sql_text": res["sql"], "sql_params": res["sql_params"],
                  "source": f"duckdb:{self.engine.executor.path.rsplit('/', 1)[-1]}", "etl_run_id": res["etl_run_id"],
                  "catalog_version": res["catalog_version"], "row_count": res["row_count"],
                  "duration_ms": res["duration_ms"],
                  "result": {"columns": res["columns"], "rows": res["rows"], "truncated": res["truncated"]},
                  "evidence": {"business_name": res["business_name"], "metric_version": res["metric_version"],
                               "rules": res["rules"], "filters_applied": res["filters_applied"],
                               "value_type": res["value_type"], "source_tables": res["source"]["tables"],
                               "executed_at": res["executed_at"]}}
        return _Result(payload, fields)

    def _owned_row(self, query_id, user_id) -> dict:
        row = self.audit.get_query(str(query_id), user_id)
        if row is None:  # outro usuário equivale a inexistente
            raise ToolError("query_not_found", "query_id não encontrado para este usuário.")
        return row

    def _tool_show_sql(self, args, qid, user_id):
        row = self._owned_row(args.query_id, user_id)
        if not row["sql_text"]:
            raise ToolError("no_sql_available", "Esta chamada não executou SQL (foi rejeitada ou não é uma consulta de métrica).")
        return _Result({"referenced_query_id": row["query_id"], "metric": row["metric"], "sql": row["sql_text"],
                        "params": row["sql_params"], "source": row["source"]},
                       {"metric": row["metric"], "row_count": 1})

    def _tool_get_evidence(self, args, qid, user_id):
        row = self._owned_row(args.query_id, user_id)
        keep = ("tool_name", "metric", "dimensions", "filters", "status", "error_code", "row_count", "source", "etl_run_id",
                "catalog_version", "created_at", "cosmos_episode_id", "cosmos_decision_id", "evidence", "result")
        return _Result({"referenced_query_id": row["query_id"], **{k: row[k] for k in keep}},
                       {"metric": row["metric"], "row_count": 1})


def err_fields(err: ToolError) -> dict:
    return {"evidence": {"error": {"code": err.code, "message": err.message, **({"details": err.details} if err.details else {})}},
            "row_count": 0}
