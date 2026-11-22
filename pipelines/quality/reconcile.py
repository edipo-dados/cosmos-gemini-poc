"""Reconciliação PostgreSQL x DuckDB das 8 métricas.

Referência: SQL escrita à mão contra o PostgreSQL (reference_sql/*.sql). Lado DuckDB: SQL escrita à mão
contra as tabelas fato (duckdb_sql/*.sql). Independente do Query Engine (Fase 3).
Tolerância 0 para dinheiro e contagens; 1e-9 (absoluta) para razões e quocientes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
from sqlalchemy import Engine, text

from .runner import SCHEMAS

HERE = Path(__file__).resolve().parent
KINDS = {
    "gross_revenue": "money", "net_revenue": "money", "refund_amount": "money",
    "order_count": "count", "active_customers": "count",
    "average_order_value": "ratio", "cancellation_rate": "ratio", "monthly_revenue_growth": "ratio",
}
RATIO_TOL = 1e-9


@dataclass
class ReconResult:
    metric: str
    ok: bool
    pg_summary: str
    duckdb_summary: str
    mismatches: int


def _pg_values(engine: Engine, metric: str, schema: str, end: date) -> dict[str, str | None]:
    if schema not in SCHEMAS:
        raise ValueError(schema)
    sql = (HERE / "reference_sql" / f"{metric}.sql").read_text(encoding="utf-8").format(schema=schema)
    with engine.connect() as c:
        return {r.key: r.value for r in c.execute(text(sql), {"data_end_date": end.isoformat()})}


def _duck_values(con: duckdb.DuckDBPyConnection, metric: str, end: date) -> dict[str, str | None]:
    sql = (HERE / "duckdb_sql" / f"{metric}.sql").read_text(encoding="utf-8")
    params = {"data_end_date": end.isoformat()} if "$data_end_date" in sql else None
    rows = con.execute(sql, params).fetchall() if params else con.execute(sql).fetchall()
    return {k: v for k, v in rows}


def _equal(kind: str, a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if kind == "ratio":
        return abs(float(a) - float(b)) <= RATIO_TOL
    return Decimal(a) == Decimal(b)


def _summary(vals: dict[str, str | None]) -> str:
    if len(vals) == 1 and "" in vals:
        return str(vals[""])
    return f"{len(vals)} meses; último={list(vals.items())[-1]}"


def reconcile_metric(pg_engine: Engine, duck_path: Path, schema: str, metric: str, end: date) -> ReconResult:
    pg = _pg_values(pg_engine, metric, schema, end)
    con = duckdb.connect(str(duck_path), read_only=True)
    try:
        dk = _duck_values(con, metric, end)
    finally:
        con.close()
    kind = KINDS[metric]
    keys = set(pg) | set(dk)
    bad = sum(1 for k in keys if not _equal(kind, pg.get(k), dk.get(k)))
    return ReconResult(metric, bad == 0, _summary(pg), _summary(dk), bad)


def reconcile_all(pg_engine: Engine, duck_path: Path, schema: str, end: date) -> list[ReconResult]:
    return [reconcile_metric(pg_engine, duck_path, schema, m, end) for m in KINDS]
