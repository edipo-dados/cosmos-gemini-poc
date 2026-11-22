"""Serviço do Query Engine: valida, constrói o SQL, executa em DuckDB e devolve dados mais evidências.

Não faz parte do Cosmos. O Cosmos guarda o significado e a política; este serviço calcula (ver docs/ARCHITECTURE.md, seção 2).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from semantic.loader import Catalog, load_catalog

from . import sql_builder, validation
from .errors import QueryEngineError
from .executor import DuckDBExecutor


def _jsonable(v):
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


class QueryEngine:
    def __init__(self, duckdb_path: Path | str, default_as_of: date, catalog: Catalog | None = None,
                 timeout_s: float = 10.0):
        self.catalog = catalog or load_catalog()
        self.executor = DuckDBExecutor(duckdb_path, timeout_s)
        self.default_as_of = default_as_of

    def query(self, raw: dict) -> dict:
        """Executa uma consulta de métrica. Levanta QueryEngineError com código estável em qualquer rejeição."""
        req = validation.parse_request(raw)
        with self.executor.connection() as con:
            ctx = self.executor.context(con, self.catalog)
            q = validation.validate(req, self.catalog, ctx.domain, ctx.data_range, self.default_as_of)
            built = sql_builder.build(self.catalog, q)
            result = self.executor.execute(con, built.sql, built.params)
        metric = self.catalog.metrics[q.metric]
        rows = result.rows
        truncated = len(rows) > q.limit or result.truncated_at_hard_limit
        rows = rows[: q.limit]
        return {
            "query_id": str(uuid.uuid4()),
            "metric": metric["name"],
            "business_name": metric["business_name"],
            "metric_version": metric["version"],
            "catalog_version": self.catalog.version,
            "columns": built.columns,
            "rows": [{c: _jsonable(v) for c, v in zip(built.columns, r)} for r in rows],
            "row_count": len(rows),
            "truncated": truncated,
            "value_type": metric["value_type"],
            "filters_applied": built.filters_applied,
            "source": {"system": "duckdb", "tables": metric["source"]["tables"], "etl_run_id": ctx.etl_run_id},
            "etl_run_id": ctx.etl_run_id,
            "rules": {"denominator": metric["denominator"], "status_rule": metric["status_rule"],
                      "time_basis": metric["time_basis"]},
            "sql": built.sql,
            "sql_params": built.params,
            "duration_ms": result.duration_ms,
            "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
