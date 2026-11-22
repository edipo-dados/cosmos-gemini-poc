import json
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import make_engine
from pipelines.quality import reconcile, runner
from pipelines.quality.run import run as run_quality

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests/golden/dq_expected.json"


@pytest.fixture(scope="module")
def dq(pg_env):
    e = make_engine("dq", pg_env)
    yield e
    e.dispose()


def test_rules_in_dq_lab_match_golden_manifest(pg_env, dq):
    manifest = json.loads(GOLDEN.read_text())["rules"]
    got = {r.name: r.violations for r in runner.run_rules(dq, "dq_lab", pg_env.data_end_date)}
    assert got == manifest
    assert all(v > 0 for v in got.values())
    assert len(got) == 7


def test_oltp_has_zero_violations(pg_env, dq):
    assert {r.name: r.violations for r in runner.run_rules(dq, "oltp", pg_env.data_end_date)} == {n: 0 for n in runner.rule_names()}


def test_reconciliation_oltp_vs_duckdb_8_of_8(pg_env, duckdb_path):
    reader = make_engine("reader", pg_env)
    res = reconcile.reconcile_all(reader, duckdb_path, "oltp", pg_env.data_end_date)
    reader.dispose()
    assert len(res) == 8 and all(r.ok for r in res), res


def test_full_quality_run_succeeds_and_is_recorded(pg_env, dq):
    assert run_quality(pg_env, trigger="pytest") is True
    with dq.connect() as c:
        runs = c.execute(text("SELECT target, status FROM ops.dq_run WHERE trigger='pytest' ORDER BY id")).all()
        results = c.execute(text(
            "SELECT count(*) FROM ops.dq_result r JOIN ops.dq_run d ON d.id=r.dq_run_id WHERE d.trigger='pytest'")).scalar_one()
    assert runs == [("oltp", "passed"), ("dq_lab", "passed")]
    assert results == 7 + 8 + 7 + 1


def test_tampered_dq_lab_duckdb_diverges(pg_env, dq):
    manifest = json.loads(GOLDEN.read_text())
    res = reconcile.reconcile_all(dq, pg_env.dq_lab_duckdb_file, "dq_lab", pg_env.data_end_date)
    assert {r.metric for r in res if not r.ok} == set(manifest["divergence"]["divergent_metrics"])
