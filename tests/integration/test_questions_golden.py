"""Perguntas golden via API (POST /tools/{name}), comparadas com SQL independente no PostgreSQL.
Valida os números do Query Engine e as regras, NÃO a escolha de ferramenta do Gemini (ver tests/live/test_live_gemini.py)."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from semantic.loader import load_catalog

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
QUESTIONS = json.loads((GOLDEN_DIR / "questions.json").read_text(encoding="utf-8"))["questions"]
CASES = {c["id"]: c for c in json.loads((GOLDEN_DIR / "expected.json").read_text(encoding="utf-8"))["cases"]}
RATIO = {"average_order_value", "cancellation_rate", "monthly_revenue_growth"}


def expected_rows(q: dict) -> list[dict]:
    case = CASES[q["expect"]["golden"]]
    rows = case["rows"]
    if "top" in q["expect"]:
        rows = sorted(rows, key=lambda r: float(r["value"]), reverse=True)[: q["expect"]["top"]]
    return rows


def assert_rows_equal(metric: str, dims: list[str], got: list[dict], exp: list[dict]) -> None:
    key = lambda r: tuple(str(r[d]) for d in dims)  # noqa: E731
    e, g = {key(r): r["value"] for r in exp}, {key(r): r["value"] for r in got}
    assert set(g) == set(e), set(g) ^ set(e)
    for k, v in e.items():
        if v is None or g[k] is None:
            assert v is None and g[k] is None
        elif metric in RATIO:
            assert abs(float(g[k]) - float(v)) <= 1e-9, (k, v, g[k])
        else:
            assert Decimal(str(g[k])) == Decimal(str(v)), (k, v, g[k])


def test_at_least_15_questions_cover_task_examples():
    assert len(QUESTIONS) >= 15
    kinds = {next(iter(q["expect"])) for q in QUESTIONS}
    assert {"golden", "explain", "maps_to", "error"} <= kinds


@pytest.mark.parametrize("q", QUESTIONS, ids=[q["id"] for q in QUESTIONS])
def test_question(client, q):
    r = client.post(f"/tools/{q['tool']}", json=q["tool_args"])
    body = r.json()
    exp = q["expect"]
    if "error" in exp:
        assert (r.status_code, body["error"]["code"]) == (exp["http"], exp["error"])
        ev = client.post("/tools/get_evidence", json={"query_id": body["error"]["query_id"]}).json()
        assert ev["status"] == "rejected" and ev["error_code"] == exp["error"]
        nosql = client.post("/tools/show_sql", json={"query_id": body["error"]["query_id"]})
        assert (nosql.status_code, nosql.json()["error"]["code"]) == (409, "no_sql_available")
        return
    assert r.status_code == 200, body
    if "golden" in exp:
        dims = q["tool_args"].get("dimensions", [])
        assert_rows_equal(q["tool_args"]["metric"], dims, body["rows"], expected_rows(q))
        assert "sql" not in body  # o SQL não vai ao modelo no resultado; só por show_sql
        sql = client.post("/tools/show_sql", json={"query_id": body["query_id"]}).json()
        assert sql["referenced_query_id"] == body["query_id"] and sql["sql"].lstrip().upper().startswith(("SELECT", "WITH"))
        ev = client.post("/tools/get_evidence", json={"query_id": body["query_id"]}).json()
        assert ev["status"] == "ok" and ev["cosmos_decision_id"] and ev["etl_run_id"] == body["etl_run_id"]
        assert ev["evidence"]["rules"]["denominator"] and ev["result"]["rows"] == body["rows"]
    elif "explain" in exp:
        m = load_catalog().metrics[exp["explain"]]
        assert body["formula"] == m["formula"] and body["denominator"] == m["denominator"]
        assert body["version"] == m["version"] and body["owner"] == m["owner"]
        assert set(exp["rule_titles"]) <= {r["title"] for r in body["rules"]}
    elif "maps_to" in exp:
        mapped = {name for res in body["results"] for name in res.get("maps_to", [])}
        assert set(exp["maps_to"]) <= mapped


def test_injection_did_not_change_data(client):
    r = client.post("/tools/query_metric", json={"metric": "order_count"})
    assert r.status_code == 200 and r.json()["rows"][0]["value"] == 20000
