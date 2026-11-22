import json
from pathlib import Path

from sqlalchemy import text

from app.db import make_engine
from data.generators.run import count_rows, run

ROOT = Path(__file__).resolve().parents[2]


def _sql(pg_env, role, sql):
    e = make_engine(role, pg_env)
    try:
        with e.connect() as c:
            return c.execute(text(sql)).all()
    finally:
        e.dispose()


def test_volumes_read_from_postgres(pg_env):
    n = count_rows(make_engine("reader", pg_env), "oltp")
    assert n["customers"] == 5000 and n["products"] == 500 and n["categories"] == 20 and n["regions"] == 5
    assert n["orders"] == 20000 and n["payments"] == 20000 and n["order_items"] >= 35000 and n["refunds"] > 0


def test_statuses_methods_and_24_months(pg_env):
    assert {r[0] for r in _sql(pg_env, "reader", "SELECT DISTINCT status FROM oltp.orders")} == {"pending", "paid", "cancelled", "refunded"}
    assert len(_sql(pg_env, "reader", "SELECT DISTINCT method FROM oltp.payments")) == 4
    assert _sql(pg_env, "reader", "SELECT count(DISTINCT date_trunc('month', order_date)) FROM oltp.orders")[0][0] == 24
    assert _sql(pg_env, "reader", "SELECT count(DISTINCT region_id) FROM oltp.customers")[0][0] == 5


def test_rerun_does_not_duplicate(pg_env, tmp_path):
    before = count_rows(make_engine("reader", pg_env), "oltp")
    lab_before = count_rows(make_engine("dq", pg_env), "dq_lab")
    assert run(settings=pg_env, manifest_path=tmp_path / "m.json") == 0
    assert count_rows(make_engine("reader", pg_env), "oltp") == before
    assert count_rows(make_engine("dq", pg_env), "dq_lab") == lab_before


def test_other_seed_without_reset_exits_2_and_changes_nothing(pg_env, tmp_path):
    before = count_rows(make_engine("reader", pg_env), "oltp")
    assert run(seed=7, settings=pg_env, manifest_path=tmp_path / "m.json") == 2
    assert count_rows(make_engine("reader", pg_env), "oltp") == before


def test_reset_reload_is_deterministic(pg_env, tmp_path):
    sig = "SELECT sum(total_amount), count(*) FROM oltp.orders"
    before = _sql(pg_env, "reader", sig)
    assert run(settings=pg_env, do_reset=True, manifest_path=tmp_path / "m.json") == 0
    assert _sql(pg_env, "reader", sig) == before


def test_manifest_matches_committed_golden(pg_env, tmp_path):
    out = tmp_path / "m.json"
    run(settings=pg_env, manifest_path=out)
    assert json.loads(out.read_text()) == json.loads((ROOT / "tests/golden/dq_expected.json").read_text())
