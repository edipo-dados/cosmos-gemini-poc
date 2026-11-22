"""Validação do Query Engine sem banco: esquema, matriz de dimensões, filtros, datas, ordenação e limite."""
from __future__ import annotations

from datetime import date

import pytest

from app.services.query_engine import validation
from app.services.query_engine.errors import QueryEngineError
from semantic.loader import load_catalog

CATALOG = load_catalog()
DOMAIN = {"region": {"Norte", "Sul", "Sudeste"}, "segment": {"Premium", "Varejo"}, "category": {"Games"},
          "product": {"P1"}, "payment_method": {"pix", "boleto"}, "order_status": {"paid", "cancelled", "pending", "refunded"}}
RANGE = (date(2024, 11, 1), date(2026, 10, 31))
AS_OF = date(2026, 10, 31)


def check(raw: dict):
    return validation.validate(validation.parse_request(raw), CATALOG, DOMAIN, RANGE, AS_OF)


def code(raw: dict) -> str:
    with pytest.raises(QueryEngineError) as exc:
        check(raw)
    return exc.value.code


def test_valid_minimal():
    q = check({"metric": "gross_revenue"})
    assert q.dimensions == [] and q.limit == 100


@pytest.mark.parametrize("raw", [
    {"metric": "gross_revenue; DROP TABLE x"}, {"metric": "Gross"}, {"metric": ""}, {"metric": "gross_revenue", "extra": 1},
    {"metric": "gross_revenue", "dimensions": "region"}, {"metric": "gross_revenue", "limit": "10"},
    {"metric": "gross_revenue", "date_from": "ontem"}, {"metric": "gross_revenue", "dimensions": ["a", "b", "c", "d"]},
    {"metric": "gross_revenue", "filters": [{"dimension": "region", "op": "like", "value": "S%"}]},
    {"metric": "gross_revenue", "filters": [{"dimension": "region", "op": "eq", "value": True}]},
])
def test_schema_failures_are_invalid_arguments(raw):
    assert code(raw) == "invalid_arguments"


def test_unknown_metric_lists_available_and_suggests():
    with pytest.raises(QueryEngineError) as exc:
        check({"metric": "gross_revenu"})
    assert exc.value.code == "unknown_metric"
    assert "gross_revenue" in exc.value.details["suggestions"]
    assert len(exc.value.details["available_metrics"]) == 8
    assert code({"metric": "lucro"}) == "unknown_metric"


def test_dimension_not_allowed_for_metric():
    assert code({"metric": "active_customers", "dimensions": ["category"]}) == "dimension_not_allowed"
    assert code({"metric": "cancellation_rate", "dimensions": ["order_status"]}) == "dimension_not_allowed"
    assert code({"metric": "gross_revenue", "dimensions": ["customer_email"]}) == "dimension_not_allowed"


def test_dimension_combinations():
    assert code({"metric": "gross_revenue", "dimensions": ["month", "year"]}) == "invalid_dimension_combination"
    assert code({"metric": "gross_revenue", "dimensions": ["region", "region"]}) == "invalid_dimension_combination"
    assert check({"metric": "gross_revenue", "dimensions": ["month", "region", "segment"]}).dimensions == ["month", "region", "segment"]


def test_growth_requires_month():
    assert code({"metric": "monthly_revenue_growth"}) == "missing_required_dimension"
    assert code({"metric": "monthly_revenue_growth", "dimensions": ["region"]}) == "missing_required_dimension"
    assert code({"metric": "monthly_revenue_growth", "dimensions": ["month", "year"]}) == "dimension_not_allowed"


def test_filters():
    assert code({"metric": "gross_revenue", "filters": [{"dimension": "region", "op": "eq", "value": "Atlantida"}]}) == "invalid_filter"
    assert code({"metric": "gross_revenue", "filters": [{"dimension": "region", "op": "gte", "value": "A"}]}) == "invalid_filter"
    assert code({"metric": "gross_revenue", "filters": [{"dimension": "month", "op": "eq", "value": "2026-13"}]}) == "invalid_filter"
    assert code({"metric": "gross_revenue", "filters": [{"dimension": "year", "op": "eq", "value": 1999}]}) == "invalid_filter"
    assert code({"metric": "gross_revenue", "filters": [{"dimension": "date", "op": "between", "value": ["2026-02-01"]}]}) == "invalid_filter"
    assert code({"metric": "gross_revenue", "filters": [{"dimension": "region", "op": "in", "value": "Sul"}]}) == "invalid_filter"
    assert code({"metric": "active_customers", "filters": [{"dimension": "month", "op": "eq", "value": "2026-01"}]}) == "invalid_filter"
    assert code({"metric": "gross_revenue", "filters": [{"dimension": "x", "op": "eq", "value": "a"}] * 6}) == "invalid_arguments"
    q = check({"metric": "gross_revenue", "filters": [{"dimension": "date", "op": "between", "value": ["2026-01-01", "2026-02-01"]},
                                                       {"dimension": "region", "op": "in", "value": ["Sul", "Norte"]}]})
    assert q.filters[0].value == [date(2026, 1, 1), date(2026, 2, 1)]


def test_injection_in_filter_value_is_rejected_by_domain_check():
    for evil in ("Sul' OR '1'='1", "Sul'; DROP TABLE fact_orders; --", "x" * 65):
        assert code({"metric": "gross_revenue", "filters": [{"dimension": "region", "op": "eq", "value": evil}]}) == "invalid_filter"


def test_dates():
    assert code({"metric": "gross_revenue", "date_from": "2026-02-30"}) == "invalid_date_range"
    assert code({"metric": "gross_revenue", "date_from": "2026-05-02", "date_to": "2026-05-01"}) == "invalid_date_range"
    assert code({"metric": "gross_revenue", "date_from": "2020-01-01"}) == "invalid_date_range"
    assert code({"metric": "gross_revenue", "date_to": "2030-01-01"}) == "invalid_date_range"


def test_active_customers_window():
    assert code({"metric": "active_customers", "date_from": "2026-01-01"}) == "invalid_date_range"
    assert check({"metric": "active_customers"}).as_of == AS_OF
    assert check({"metric": "active_customers", "date_to": "2026-06-30"}).as_of == date(2026, 6, 30)


def test_order_and_limit():
    assert code({"metric": "gross_revenue", "dimensions": ["region"], "order_by": {"field": "segment"}}) == "invalid_order"
    assert code({"metric": "gross_revenue", "order_by": {"field": "region"}}) == "invalid_order"
    assert check({"metric": "gross_revenue", "dimensions": ["region"], "order_by": {"field": "metric"}}).order_field == "value"
    for bad in (0, -1, 1001):
        assert code({"metric": "gross_revenue", "limit": bad}) == "invalid_limit"
    assert check({"metric": "gross_revenue", "limit": 1000}).limit == 1000
