"""Executa os testes de validação declarados em cada métrica do catálogo (campo `tests`).

- reconciliation: resultado do Query Engine (DuckDB) contra o SQL de referência escrito à mão e executado no PostgreSQL (oltp).
- invariant: propriedades que o resultado precisa cumprir (aditividade, limites, comparação com outra métrica).
Uso: python -m semantic.metric_tests   (precisa de PostgreSQL no ar e do DuckDB gerado pelo ETL)
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine, text

from app.services.query_engine import QueryEngine
from semantic.loader import Catalog

log = logging.getLogger("poc.metric_tests")


@dataclass
class TestResult:
    __test__ = False  # não é um teste do pytest
    metric: str
    test_id: str
    type: str
    ok: bool
    detail: str


def _pg_reference(pg: Engine, catalog: Catalog, ref: str, end_date: date) -> dict[str, str | None]:
    sql = (catalog.root / ref).read_text(encoding="utf-8").format(schema="oltp")
    with pg.connect() as c:
        return {r.key: r.value for r in c.execute(text(sql), {"data_end_date": end_date.isoformat()})}


def _equal(a, b, tol: Decimal) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(Decimal(str(a)) - Decimal(str(b))) <= tol


def _reconcile(engine: QueryEngine, pg: Engine, catalog: Catalog, metric: str, t: dict, end: date) -> tuple[bool, str]:
    dims = t.get("dimensions", [])
    ref = _pg_reference(pg, catalog, t["reference_sql"], end)
    res = engine.query({"metric": metric, "dimensions": dims, "limit": 1000})
    got = {(r[dims[0]] if dims else ""): r["value"] for r in res["rows"]}
    tol = Decimal(t.get("tolerance", "0"))
    bad = [k for k in set(ref) | set(got) if not _equal(ref.get(k), got.get(k), tol)]
    summary = f"{len(ref)} chave(s) comparada(s), {len(bad)} divergência(s)"
    if len(ref) == 1:
        summary += f"; referência={next(iter(ref.values()))} motor={next(iter(got.values()), None)}"
    return not bad, summary


def _invariant(engine: QueryEngine, metric: str, t: dict) -> tuple[bool, str]:
    kind = t["invariant"]
    total = engine.query({"metric": metric})["rows"][0]["value"] if kind != "first_row_null" else None
    if kind == "additive_by_dimension":
        by = engine.query({"metric": metric, "dimensions": [t["dimension"]], "limit": 1000})["rows"]
        s = sum(Decimal(str(r["value"])) for r in by)
        return s == Decimal(str(total)), f"soma por {t['dimension']}={s} total={total}"
    if kind == "min_value":
        return Decimal(str(total)) >= Decimal(t["min"]), f"valor={total} mínimo={t['min']}"
    if kind == "between":
        return Decimal(t["min"]) <= Decimal(str(total)) <= Decimal(t["max"]), f"valor={total} faixa=[{t['min']},{t['max']}]"
    if kind == "not_greater_than":
        other = engine.query({"metric": t["other_metric"]})["rows"][0]["value"]
        return Decimal(str(total)) <= Decimal(str(other)), f"valor={total} {t['other_metric']}={other}"
    if kind == "first_row_null":
        rows = engine.query({"metric": metric, "dimensions": ["month"], "order_by": {"field": "month", "direction": "asc"},
                             "limit": 1000})["rows"]
        return rows[0]["value"] is None and all(r["value"] is not None for r in rows[1:2]), \
            f"primeiro mês {rows[0]['month']}={rows[0]['value']}"
    raise ValueError(kind)


def run_metric_tests(engine: QueryEngine, pg: Engine, end_date: date) -> list[TestResult]:
    catalog = engine.catalog
    results: list[TestResult] = []
    for name, m in catalog.metrics.items():
        for t in m["tests"]:
            if t["type"] == "reconciliation":
                ok, detail = _reconcile(engine, pg, catalog, name, t, end_date)
            else:
                ok, detail = _invariant(engine, name, t)
            results.append(TestResult(name, t["id"], t["type"], ok, detail))
    return results


def main() -> int:
    from app.config import get_settings
    from app.db import make_engine
    settings = get_settings()
    engine = QueryEngine(settings.duckdb_file, settings.data_end_date)
    pg = make_engine("reader", settings)
    try:
        results = run_metric_tests(engine, pg, settings.data_end_date)
    finally:
        pg.dispose()
    for r in results:
        print(f"{'OK  ' if r.ok else 'FAIL'} {r.metric:24s} {r.test_id:28s} {r.detail}")
    failed = sum(not r.ok for r in results)
    print(f"{len(results) - failed}/{len(results)} testes de métrica passaram (catalog_version={engine.catalog.version})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
