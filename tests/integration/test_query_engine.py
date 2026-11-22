"""Query Engine contra o DuckDB real gerado pelo ETL (fixture de sessão com PostgreSQL real)."""
from __future__ import annotations

import time
from datetime import date

import duckdb
import pytest

from app.services.query_engine import QueryEngine, QueryEngineError
from app.services.query_engine.executor import DuckDBExecutor


@pytest.fixture(scope="module")
def engine(pg_env):
    return QueryEngine(pg_env.duckdb_file, pg_env.data_end_date)


def err(engine, raw) -> QueryEngineError:
    with pytest.raises(QueryEngineError) as exc:
        engine.query(raw)
    return exc.value


def test_result_contains_data_and_evidence(engine, pg_env):
    r = engine.query({"metric": "net_revenue", "dimensions": ["region"], "filters": [{"dimension": "segment", "op": "eq", "value": "Premium"}]})
    assert r["metric"] == "net_revenue" and r["metric_version"] == "1.0.0"
    assert r["catalog_version"] == engine.catalog.version
    assert r["etl_run_id"] >= 1 and r["source"]["system"] == "duckdb"
    assert r["sql"].startswith("SELECT") and r["sql"].count("?") == len(r["sql_params"])
    assert {"type": "filter", "dimension": "segment", "op": "eq", "value": "Premium"} in r["filters_applied"]
    assert any(f["type"] == "base_filter" for f in r["filters_applied"])
    assert r["rows"] and set(r["rows"][0]) == {"region", "value"}
    assert r["row_count"] == len(r["rows"]) and not r["truncated"]


def test_etl_run_id_matches_etl_meta(engine, pg_env):
    con = duckdb.connect(str(pg_env.duckdb_file), read_only=True)
    try:
        assert con.execute("SELECT etl_run_id FROM etl_meta").fetchone()[0] == engine.query({"metric": "order_count"})["etl_run_id"]
    finally:
        con.close()


@pytest.mark.parametrize("evil", ["Sul' OR '1'='1", "'; DROP TABLE fact_orders; --", "Sul\" --", "%", "Sul/*"])
def test_sql_injection_in_filter_values_never_reaches_sql(engine, evil):
    e = err(engine, {"metric": "gross_revenue", "filters": [{"dimension": "region", "op": "eq", "value": evil}]})
    assert e.code == "invalid_filter"


def test_sql_injection_in_dimensions_metric_and_order(engine):
    assert err(engine, {"metric": "gross_revenue", "dimensions": ["region\" ; DROP TABLE fact_orders; --"]}).code == "dimension_not_allowed"
    assert err(engine, {"metric": "gross_revenue; SELECT 1"}).code == "invalid_arguments"
    assert err(engine, {"metric": "gross_revenue", "dimensions": ["region"], "order_by": {"field": "1; --"}}).code == "invalid_arguments"
    assert engine.query({"metric": "order_count"})["rows"][0]["value"] == 20000  # tabelas intactas


def test_rejections(engine):
    assert err(engine, {"metric": "active_customers", "dimensions": ["category"]}).code == "dimension_not_allowed"
    assert err(engine, {"metric": "lucro"}).code == "unknown_metric"
    assert err(engine, {"metric": "gross_revenue", "limit": 5000}).code == "invalid_limit"
    assert err(engine, {"metric": "gross_revenue", "date_from": "2020-01-01"}).code == "invalid_date_range"
    assert err(engine, {"metric": "monthly_revenue_growth"}).code == "missing_required_dimension"


def test_active_customers_as_of(engine, pg_env):
    default = engine.query({"metric": "active_customers"})
    assert default["rows"][0]["value"] > 0
    window = next(f for f in default["filters_applied"] if f["type"] == "window")
    assert window["as_of"] == pg_env.data_end_date.isoformat() and window["start"] == "2026-08-03"
    early = engine.query({"metric": "active_customers", "date_to": "2025-03-31"})
    assert next(f for f in early["filters_applied"] if f["type"] == "window")["as_of"] == "2025-03-31"
    assert err(engine, {"metric": "active_customers", "date_from": "2026-01-01"}).code == "invalid_date_range"


def test_growth_window_order_limit_and_previous_month(engine):
    full = engine.query({"metric": "monthly_revenue_growth", "dimensions": ["month"], "limit": 1000})
    assert full["row_count"] == 24 and full["rows"][0]["value"] is None
    win = engine.query({"metric": "monthly_revenue_growth", "dimensions": ["month"], "date_from": "2026-09-15", "date_to": "2026-10-10"})
    assert [r["month"] for r in win["rows"]] == ["2026-09", "2026-10"]
    by_month = {r["month"]: r["value"] for r in full["rows"]}
    assert {r["month"]: r["value"] for r in win["rows"]} == {m: by_month[m] for m in ("2026-09", "2026-10")}  # usa o mês anterior real
    top = engine.query({"metric": "monthly_revenue_growth", "dimensions": ["month"], "order_by": {"field": "metric", "direction": "desc"}, "limit": 3})
    values = [r["value"] for r in top["rows"]]
    assert top["row_count"] == 3 and values == sorted(values, reverse=True) and top["truncated"]
    regional = engine.query({"metric": "monthly_revenue_growth", "dimensions": ["month", "region"], "limit": 1000})
    assert regional["row_count"] == 24 * 5


def test_limit_and_truncated_flag(engine):
    r = engine.query({"metric": "gross_revenue", "dimensions": ["product"], "limit": 10})
    assert r["row_count"] == 10 and r["truncated"] is True
    r = engine.query({"metric": "gross_revenue", "dimensions": ["product"], "limit": 1000})
    assert r["row_count"] <= 500 and r["truncated"] is False


def test_connection_is_read_only(pg_env):
    ex = DuckDBExecutor(pg_env.duckdb_file)
    with ex.connection() as con:
        with pytest.raises(duckdb.Error):
            con.execute("CREATE TABLE hacked (x INT)")
        with pytest.raises(duckdb.Error):
            con.execute("DELETE FROM fact_orders")
    with ex.connection() as con:
        assert con.execute("SELECT count(*) FROM fact_orders").fetchone()[0] == 20000


def test_query_timeout_interrupts_real_long_query(pg_env):
    ex = DuckDBExecutor(pg_env.duckdb_file, timeout_s=0.5)
    start = time.perf_counter()
    with ex.connection() as con:
        with pytest.raises(QueryEngineError) as exc:
            ex.execute(con, "SELECT count(*) FROM range(10000000000) a, range(1000000) b", [])
        assert exc.value.code == "query_timeout"
        # a conexão continua utilizável depois do interrupt
        assert con.execute("SELECT 1").fetchone()[0] == 1
    assert time.perf_counter() - start < 5


def test_executor_rejects_non_select(pg_env):
    ex = DuckDBExecutor(pg_env.duckdb_file)
    with ex.connection() as con:
        with pytest.raises(QueryEngineError):
            ex.execute(con, "DROP TABLE fact_orders", [])


def test_two_requests_in_sequence_use_fresh_connections(engine):
    a = engine.query({"metric": "gross_revenue"})
    b = engine.query({"metric": "gross_revenue"})
    assert a["query_id"] != b["query_id"] and a["rows"] == b["rows"]


def test_new_etl_run_is_picked_up_without_restart(pg_env):
    from pipelines.transform.run import run as run_etl
    engine = QueryEngine(pg_env.duckdb_file, pg_env.data_end_date)
    before = engine.query({"metric": "order_count"})
    run_etl(pg_env)
    after = engine.query({"metric": "order_count"})
    assert after["etl_run_id"] > before["etl_run_id"] and after["rows"] == before["rows"]
