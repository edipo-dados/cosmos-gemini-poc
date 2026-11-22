"""Reconciliação das 8 métricas: Query Engine (DuckDB) contra SQL independente no PostgreSQL.

Duas fontes de esperado: (1) tests/golden/expected.json, gerado por scripts/compute_golden.py (SQL em oltp, por métrica e
por recorte); (2) os `tests` declarados em cada métrica do catálogo (SQL de referência da Fase 2 e invariantes).
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.db import make_engine
from app.services.query_engine import QueryEngine
from semantic.metric_tests import run_metric_tests

GOLDEN = json.loads((Path(__file__).resolve().parents[1] / "golden" / "expected.json").read_text(encoding="utf-8"))
RATIO = {"average_order_value", "cancellation_rate", "monthly_revenue_growth"}


@pytest.fixture(scope="module")
def engine(pg_env):
    return QueryEngine(pg_env.duckdb_file, pg_env.data_end_date)


def _key(row: dict, dims: list[str]) -> tuple:
    return tuple(str(row[d]) for d in dims)


def test_golden_covers_all_metrics_and_slices():
    metrics = {c["request"]["metric"] for c in GOLDEN["cases"]}
    assert len(metrics) == 8
    assert len(GOLDEN["cases"]) >= 50
    assert any(c["request"].get("filters") for c in GOLDEN["cases"])


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=[c["id"] for c in GOLDEN["cases"]])
def test_engine_equals_independent_postgres_sql(engine, case):
    req = case["request"]
    got = engine.query(req)
    dims = req["dimensions"]
    expected = {_key(r, dims): r["value"] for r in case["rows"]}
    actual = {_key(r, dims): r["value"] for r in got["rows"]}
    assert set(actual) == set(expected), (set(actual) ^ set(expected))
    for k, exp in expected.items():
        act = actual[k]
        if exp is None or act is None:
            assert exp is None and act is None, (k, exp, act)
        elif req["metric"] in RATIO:
            assert abs(float(act) - float(exp)) <= 1e-9, (k, exp, act)
        else:
            assert Decimal(str(act)) == Decimal(str(exp)), (k, exp, act)  # dinheiro e contagens: tolerância 0


def test_declared_metric_tests_pass(engine, pg_env):
    pg = make_engine("reader", pg_env)
    try:
        results = run_metric_tests(engine, pg, pg_env.data_end_date)
    finally:
        pg.dispose()
    failed = [r for r in results if not r.ok]
    assert not failed, failed
    declared = sum(len(m["tests"]) for m in engine.catalog.metrics.values())
    assert len(results) == declared >= 16
    assert {r.metric for r in results if r.type == "reconciliation"} == set(engine.catalog.metrics)


def test_reconciliation_detects_a_wrong_expression(pg_env, tmp_path):
    """Prova negativa: uma fórmula errada no catálogo (sem descontar reembolsos) faz o teste declarado falhar."""
    import shutil

    import yaml

    from semantic.loader import SEMANTIC_DIR, load_catalog

    copy = tmp_path / "semantic"
    shutil.copytree(SEMANTIC_DIR, copy, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    p = copy / "metrics" / "net_revenue.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    doc["expression"] = "COALESCE(SUM(i.line_total), 0)"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    broken = QueryEngine(pg_env.duckdb_file, pg_env.data_end_date, catalog=load_catalog(copy))
    pg = make_engine("reader", pg_env)
    try:
        results = run_metric_tests(broken, pg, pg_env.data_end_date)
    finally:
        pg.dispose()
    failed = {(r.metric, r.test_id) for r in results if not r.ok}
    assert ("net_revenue", "total_vs_reference_sql") in failed
