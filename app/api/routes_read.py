"""Leituras para o frontend (somente leitura): qualidade, cargas, auditoria e visão geral.
Qualidade e cargas vêm de `ops.*` e a auditoria de `audit.query_audit`, ambas com o papel `poc_app` (só SELECT).
A visão geral usa as mesmas ferramentas governadas (Cosmos + Query Engine + auditoria), sob o usuário interno `overview`."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from app.api.deps import InvalidRequest, get_state, user_id
from app.api.state import AppState
from app.services.audit import _plain
router = APIRouter()
OVERVIEW_USER = "overview"
KPIS = ("gross_revenue", "net_revenue", "average_order_value", "active_customers", "order_count", "cancellation_rate")
SERIES = (("month", "net_revenue", "month"), ("region", "net_revenue", "region"), ("category", "net_revenue", "category"))


def _rows(state: AppState, sql: str, params: dict) -> list[dict]:
    with state.audit.engine.connect() as con:
        return [_plain(r) for r in con.execute(text(sql), params).mappings().all()]


@router.get("/etl/runs")
def etl_runs(limit: int = Query(20, ge=1, le=100), state: AppState = Depends(get_state)):
    rows = _rows(state, "SELECT id, started_at, finished_at, status, source_row_counts, duckdb_path, duration_ms, error "
                        "FROM ops.etl_run ORDER BY id DESC LIMIT :n", {"n": limit})
    return {"count": len(rows), "runs": rows}


@router.get("/quality/runs")
def quality_runs(limit: int = Query(20, ge=1, le=100), state: AppState = Depends(get_state)):
    rows = _rows(state, "SELECT id, started_at, finished_at, target, trigger, etl_run_id, status, summary "
                        "FROM ops.dq_run ORDER BY id DESC LIMIT :n", {"n": limit})
    return {"count": len(rows), "runs": rows}


@router.get("/quality/results")
def quality_results(run_id: int | None = Query(None, ge=1), state: AppState = Depends(get_state)):
    """Resultados de uma execução; sem `run_id`, da execução mais recente de `oltp` (e de `dq_lab`)."""
    if run_id is not None:
        ids = [run_id]
    else:
        ids = [r["id"] for r in _rows(state, "SELECT max(id) AS id FROM ops.dq_run GROUP BY target", {}) if r["id"]]
    if not ids:
        return {"count": 0, "results": []}
    rows = _rows(state, "SELECT r.id, r.dq_run_id, d.target, r.kind, r.name, r.violations, r.expected, r.actual, r.passed, "
                        "r.detail FROM ops.dq_result r JOIN ops.dq_run d ON d.id = r.dq_run_id "
                        "WHERE r.dq_run_id = ANY(:ids) ORDER BY r.dq_run_id, r.id", {"ids": ids})
    return {"count": len(rows), "results": rows}


@router.get("/audit/queries")
def audit_queries(limit: int = Query(50, ge=1, le=200), uid: str = Depends(user_id), state: AppState = Depends(get_state)):
    rows = state.audit.list_queries(uid, limit)
    return {"user_id": uid, "count": len(rows), "queries": rows}


@router.get("/audit/queries/{query_id}")
def audit_query(query_id: str, uid: str = Depends(user_id), state: AppState = Depends(get_state)):
    from uuid import UUID
    try:
        UUID(query_id)
    except ValueError as exc:
        raise InvalidRequest("invalid_arguments", "query_id deve ser um UUID.") from exc
    row = state.audit.get_query(query_id, uid)
    if row is None:
        from agent.tools.errors import ToolError
        raise ToolError("query_not_found", "query_id não encontrado para este usuário.")
    return row


@router.get("/overview")
def overview(state: AppState = Depends(get_state)):
    kpis, series, errors = {}, {}, []
    for metric in KPIS:
        out = state.executor.execute("query_metric", {"metric": metric}, OVERVIEW_USER)
        if out.http_status != 200:
            errors.append({"metric": metric, "error": out.payload.get("error")})
            continue
        p = out.payload
        kpis[metric] = {"business_name": p["business_name"], "value": p["rows"][0]["value"] if p["rows"] else None,
                        "value_type": p["value_type"], "query_id": p["query_id"]}
    for dim, metric, _ in SERIES:
        args = {"metric": metric, "dimensions": [dim], "limit": 1000}
        if dim == "month":
            args["order_by"] = {"field": "month", "direction": "asc"}
        out = state.executor.execute("query_metric", args, OVERVIEW_USER)
        if out.http_status != 200:
            errors.append({"metric": metric, "dimension": dim, "error": out.payload.get("error")})
            continue
        series[dim] = {"metric": metric, "business_name": out.payload["business_name"], "value_type": out.payload["value_type"],
                       "rows": out.payload["rows"], "query_id": out.payload["query_id"]}
    return {"catalog_version": state.engine.catalog.version, "kpis": kpis, "series": series, "errors": errors}
