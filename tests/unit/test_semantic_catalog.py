"""Catálogo semântico: esquema, matriz métrica x dimensão, responsáveis, versões, testes declarados e glossário."""
from __future__ import annotations

import shutil

import pytest
import yaml

from semantic.loader import SEMANTIC_DIR, CatalogError, load_catalog

METRICS = ["gross_revenue", "net_revenue", "order_count", "average_order_value", "active_customers",
           "cancellation_rate", "refund_amount", "monthly_revenue_growth"]
DIMENSIONS = ["date", "month", "year", "region", "segment", "category", "product", "payment_method", "order_status"]

# Cópia da tabela da seção 6 do ARCHITECTURE: S = permitida, N = rejeitada.
MATRIX = {
    "gross_revenue": "SSSSSSSSS", "net_revenue": "SSSSSSSSS", "order_count": "SSSSSSSSS",
    "average_order_value": "SSSSSSSSS", "active_customers": "NNNSSNNNN", "cancellation_rate": "SSSSSNNSN",
    "refund_amount": "SSSSSSSSS", "monthly_revenue_growth": "NSNSSNNNN",
}


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_eight_metrics_and_nine_dimensions(catalog):
    assert sorted(catalog.metrics) == sorted(METRICS)
    assert sorted(catalog.dimensions) == sorted(DIMENSIONS)


def test_matrix_equals_architecture_table(catalog):
    for metric, row in MATRIX.items():
        expected = {d for d, flag in zip(DIMENSIONS, row) if flag == "S"}
        assert set(catalog.metrics[metric]["allowed_dimensions"]) == expected, metric
        assert set(catalog.metrics[metric]["applicable_filters"]["dimensions"]) == expected, metric


def test_every_metric_has_required_governance_fields(catalog):
    for m in catalog.metrics.values():
        for key in ("business_name", "description", "formula", "source", "owner", "version", "denominator",
                    "status_rule", "time_basis", "allowed_dimensions", "applicable_filters", "tests"):
            assert m[key], (m["name"], key)
        assert any(t["type"] == "reconciliation" for t in m["tests"]), m["name"]


def test_glossary_receita_maps_to_both_candidates(catalog):
    by_name = {t["term"].lower(): t for t in catalog.glossary}
    receita = by_name["receita"]
    assert {r["name"] for r in receita["maps_to"]} == {"gross_revenue", "net_revenue"}
    assert "Faturamento" in receita["synonyms"]


def test_glossary_required_synonyms(catalog):
    pairs = {s.lower(): t["maps_to"][0]["name"] for t in catalog.glossary for s in t["synonyms"] + [t["term"]]}
    assert pairs["ticket médio"] == "average_order_value"
    assert pairs["cliente ativo"] == "active_customers"
    assert pairs["cancelamento"] == "cancellation_rate"
    assert pairs["faturamento líquido"] == "net_revenue"


def test_every_metric_has_rules_for_denominator_and_status(catalog):
    for name in catalog.metrics:
        cats = {r["category"] for r in catalog.rules_for(name)}
        assert "status" in cats and "time" in cats, name
    assert {"denominator", "window"} <= {r["category"] for r in catalog.rules}


def test_seven_tools(catalog):
    assert [t["name"] for t in catalog.capabilities["tools"]] == [
        "search_concepts", "explain_metric", "list_metrics", "list_dimensions", "query_metric", "show_sql", "get_evidence"]


def test_catalog_version_is_stable_and_content_sensitive(tmp_path, catalog):
    assert load_catalog().version == catalog.version
    copy = tmp_path / "semantic"
    shutil.copytree(SEMANTIC_DIR, copy, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    assert load_catalog(copy).version == catalog.version
    p = copy / "metrics" / "gross_revenue.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    doc["version"] = "1.0.1"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    assert load_catalog(copy).version != catalog.version


@pytest.mark.parametrize("mutation, message", [
    (lambda d: d.pop("owner"), "owner"),
    (lambda d: d.update(version="v1"), "version"),
    (lambda d: d.update(allowed_dimensions=["inexistente"]), "inexistente"),
])
def test_invalid_metric_is_rejected(tmp_path, mutation, message):
    copy = tmp_path / "semantic"
    shutil.copytree(SEMANTIC_DIR, copy, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    p = copy / "metrics" / "order_count.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    mutation(doc)
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    with pytest.raises(CatalogError) as exc:
        load_catalog(copy)
    assert message in str(exc.value)
