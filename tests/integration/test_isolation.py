import duckdb
import pytest
from sqlalchemy.exc import ProgrammingError
from sqlalchemy import text

from app.db import make_engine
from data.generators.config import GenConfig
from data.generators.run import generate, load_schema
from pipelines.quality import reconcile


def test_reader_cannot_see_dq_lab(pg_env):
    e = make_engine("reader", pg_env)
    with e.connect() as c, pytest.raises(ProgrammingError):
        c.execute(text("SELECT count(*) FROM dq_lab.orders"))
    e.dispose()


def test_official_metrics_unchanged_after_reloading_dq_lab(pg_env, duckdb_path):
    def snapshot():
        con = duckdb.connect(str(duckdb_path), read_only=True)
        try:
            return {m: reconcile._duck_values(con, m, pg_env.data_end_date) for m in reconcile.KINDS}
        finally:
            con.close()

    before = snapshot()
    _, lab, _ = generate(GenConfig(seed=pg_env.seed, end_date=pg_env.data_end_date))
    loader = make_engine("loader", pg_env)
    with loader.begin() as c:
        c.execute(text("TRUNCATE dq_lab.refunds, dq_lab.payments, dq_lab.order_items, dq_lab.orders"))
    load_schema(loader, "dq_lab", lab)
    loader.dispose()
    assert snapshot() == before


def test_oltp_metrics_equal_pg_reference_not_dq_lab(pg_env, duckdb_path):
    reader = make_engine("reader", pg_env)
    oltp = reconcile._pg_values(reader, "order_count", "oltp", pg_env.data_end_date)
    reader.dispose()
    dq = make_engine("dq", pg_env)
    lab = reconcile._pg_values(dq, "order_count", "dq_lab", pg_env.data_end_date)
    dq.dispose()
    assert oltp[""] == "20000" and lab[""] != oltp[""]
