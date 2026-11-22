"""Construção do SQL sem banco: parâmetros, identificadores só do catálogo e checagem de instrução única."""
from __future__ import annotations

import pytest

from app.services.query_engine import sql_builder, validation
from app.services.query_engine.errors import QueryEngineError
from semantic.loader import load_catalog
from tests.unit.test_validation import AS_OF, DOMAIN, RANGE

CATALOG = load_catalog()


def build(raw):
    q = validation.validate(validation.parse_request(raw), CATALOG, DOMAIN, RANGE, AS_OF)
    return sql_builder.build(CATALOG, q)


def test_values_become_parameters_not_sql_text():
    b = build({"metric": "net_revenue", "dimensions": ["region"],
               "filters": [{"dimension": "segment", "op": "in", "value": ["Premium", "Varejo"]}],
               "date_from": "2026-01-01", "date_to": "2026-03-31"})
    assert "Premium" not in b.sql and "2026-01-01" not in b.sql
    assert b.sql.count("?") == len(b.params)
    assert b.params == ["Premium", "Varejo", "2026-01-01", "2026-03-31", 101]
    assert b.sql.startswith("SELECT ")


def test_identifiers_come_from_catalog_only():
    b = build({"metric": "gross_revenue", "dimensions": ["category", "month"]})
    for token in ("p.category_name", "strftime(o.order_date, '%Y-%m')", "dim_product p", "fact_order_items i"):
        assert token in b.sql
    assert b.sql.count("fact_order_items") == 1  # grão item não repete a junção


def test_order_grain_adds_items_join_only_when_needed():
    assert "fact_order_items" not in build({"metric": "order_count", "dimensions": ["region"]}).sql
    assert "fact_order_items" in build({"metric": "order_count", "dimensions": ["category"]}).sql


def test_active_customers_window_params():
    b = build({"metric": "active_customers", "date_to": "2026-06-30"})
    assert b.params[:2] == ["2026-04-02", "2026-06-30"]  # 90 dias corridos: as_of - 89 .. as_of
    assert any(f["type"] == "window" for f in b.filters_applied)


def test_growth_uses_calendar_and_lag_before_date_filter():
    b = build({"metric": "monthly_revenue_growth", "dimensions": ["month", "region"], "date_from": "2026-09-01"})
    assert "dim_date" in b.sql and "LAG(net) OVER (PARTITION BY \"region\" ORDER BY \"month\")" in b.sql
    assert b.sql.index("LAG(") < b.sql.index('WHERE "month" >= ?')
    assert "2026-09" in b.params


def test_default_and_explicit_order():
    assert 'ORDER BY "month" ASC' in build({"metric": "gross_revenue", "dimensions": ["month"]}).sql
    assert 'ORDER BY "value" DESC NULLS LAST, "region" ASC' in build({"metric": "gross_revenue", "dimensions": ["region"]}).sql
    b = build({"metric": "gross_revenue", "dimensions": ["region"], "order_by": {"field": "region", "direction": "asc"}})
    assert 'ORDER BY "region" ASC NULLS LAST' in b.sql


@pytest.mark.parametrize("sql", ["DELETE FROM fact_orders", "SELECT 1; DROP TABLE x", "  INSERT INTO t VALUES (1)",
                                 "ATTACH 'x.db'", "COPY t TO 'f'"])
def test_assert_single_select_rejects(sql):
    with pytest.raises(QueryEngineError):
        sql_builder.assert_single_select(sql)


def test_assert_single_select_accepts_semicolon_in_literal_and_with():
    sql_builder.assert_single_select("WITH a AS (SELECT ';' AS x) SELECT * FROM a")
