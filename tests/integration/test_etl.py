import hashlib
import json

import duckdb
import pytest
from sqlalchemy import text

from app.db import make_engine
from pipelines.extract.postgres_extract import ALLOWED_SCHEMAS, extract_queries
from pipelines.transform.run import QualityGateError, run as run_etl
from pipelines.transform.schema import TABLES

SRC = {"dim_customer": "customers", "dim_product": "products", "dim_region": "regions",
       "fact_orders": "orders", "fact_order_items": "order_items", "fact_payments": "payments", "fact_refunds": "refunds"}


def _duck(path):
    return duckdb.connect(str(path), read_only=True)


def _content_signature(path):
    con = _duck(path)
    try:
        h = hashlib.sha256()
        for t in TABLES:
            h.update(repr(con.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()).encode())
        return h.hexdigest()
    finally:
        con.close()


def test_eight_tables_match_postgres_counts(pg_env, duckdb_path):
    pg = make_engine("reader", pg_env)
    con = _duck(duckdb_path)
    try:
        existing = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        assert set(TABLES) <= existing
        with pg.connect() as c:
            for dt, st in SRC.items():
                assert con.execute(f"SELECT count(*) FROM {dt}").fetchone()[0] == c.execute(text(f"SELECT count(*) FROM oltp.{st}")).scalar_one(), dt
        assert con.execute("SELECT count(*) FROM dim_date").fetchone()[0] == 730
        assert con.execute("SELECT typeof(line_total) FROM fact_order_items LIMIT 1").fetchone()[0] == "DECIMAL(12,2)"
    finally:
        con.close()
        pg.dispose()


def test_etl_meta_matches_ops_etl_run(pg_env, duckdb_path):
    con = _duck(duckdb_path)
    try:
        run_id, counts = con.execute("SELECT etl_run_id, source_row_counts FROM etl_meta").fetchone()
    finally:
        con.close()
    pg = make_engine("reader", pg_env)
    with pg.connect() as c:
        row = c.execute(text("SELECT status, source_row_counts FROM ops.etl_run WHERE id = :i"), {"i": run_id}).one()
        last = c.execute(text("SELECT max(id) FROM ops.etl_run WHERE status = 'success'")).scalar_one()
    pg.dispose()
    assert row.status == "success" and run_id == last
    assert json.loads(counts) == row.source_row_counts


def test_second_etl_changes_run_id_keeps_content(pg_env, duckdb_path):
    con = _duck(duckdb_path)
    first_id = con.execute("SELECT etl_run_id FROM etl_meta").fetchone()[0]
    con.close()
    sig = _content_signature(duckdb_path)
    new_id = run_etl(pg_env)
    con = _duck(duckdb_path)
    assert con.execute("SELECT etl_run_id FROM etl_meta").fetchone()[0] == new_id > first_id
    con.close()
    assert _content_signature(duckdb_path) == sig
    assert not duckdb_path.with_name(duckdb_path.name + ".tmp").exists()


def test_etl_aborts_on_defect_and_keeps_previous_file(pg_env, duckdb_path):
    loader = make_engine("loader", pg_env)
    file_hash = hashlib.sha256(duckdb_path.read_bytes()).hexdigest()
    with loader.begin() as c:
        oid = c.execute(text("SELECT order_id FROM oltp.orders WHERE status='cancelled' ORDER BY order_id LIMIT 1")).scalar_one()
        c.execute(text("UPDATE oltp.payments SET status='captured', paid_at=(SELECT order_date FROM oltp.orders WHERE order_id=:o) WHERE order_id=:o"), {"o": oid})
    try:
        with pytest.raises(QualityGateError, match="cancelled_with_captured_payment"):
            run_etl(pg_env)
    finally:
        with loader.begin() as c:
            c.execute(text("UPDATE oltp.payments SET status='voided', paid_at=NULL WHERE order_id=:o"), {"o": oid})
    assert hashlib.sha256(duckdb_path.read_bytes()).hexdigest() == file_hash
    assert not duckdb_path.with_name(duckdb_path.name + ".tmp").exists()
    with loader.connect() as c:
        status, err = c.execute(text("SELECT status, error FROM ops.etl_run ORDER BY id DESC LIMIT 1")).one()
    loader.dispose()
    assert status == "failed" and "cancelled_with_captured_payment" in err
    run_etl(pg_env)  # volta ao estado saudável


def test_extraction_sql_only_references_oltp():
    for sql in extract_queries("oltp").values():
        assert "FROM oltp." in sql and "dq_lab" not in sql
    assert len(extract_queries("oltp")) == 8
    with pytest.raises(ValueError):
        extract_queries("public")
    assert ALLOWED_SCHEMAS == ("oltp", "dq_lab")


def test_etl_log_file_written(pg_env):
    log = pg_env.log_path / "etl.log"
    text_ = log.read_text()
    assert "ETL" in text_ and "fact_order_items" in text_ and pg_env.password("reader") not in text_
