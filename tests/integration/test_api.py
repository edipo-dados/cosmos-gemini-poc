"""API FastAPI contra bancos e Cosmos reais, sem Gemini configurado (fronteira: /chat sem chave -> 503)."""
from __future__ import annotations

import json
import threading
import time
import uuid

from sqlalchemy import text

from app.db import make_engine


def _events(client, episode_id: str) -> list[str]:
    store = client.app.state.poc.runtime.services.store
    return [e.event_type for e in store.list_events(episode_id)]


def _audit(settings, query_id: str) -> dict:
    eng = make_engine("app", settings)
    try:
        with eng.connect() as c:
            return dict(c.execute(text("SELECT * FROM audit.query_audit WHERE query_id=:q"), {"q": query_id}).mappings().one())
    finally:
        eng.dispose()


def test_health_without_gemini(client):
    h = client.get("/health").json()
    assert h["gemini"] == "not_configured" and h["status"] == "ok"
    assert h["postgres"] == h["duckdb"] == h["cosmos"] == "ok"
    assert h["catalog_version"] and isinstance(h["etl_run_id"], int)


def test_chat_and_ask_without_key_return_503(client):
    for path in ("/chat", "/ask"):
        r = client.post(path, json={"question": "Qual foi o faturamento dos últimos 30 dias?"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "gemini_not_configured"


def test_catalog_endpoints(client):
    m = client.get("/catalog/metrics").json()
    assert m["count"] == 8
    for metric in m["metrics"]:
        for f in ("name", "business_name", "description", "formula", "source", "allowed_dimensions", "applicable_filters",
                  "owner", "version", "tests", "denominator", "status_rule", "rules"):
            assert metric[f] not in (None, "", []), (metric["name"], f)
    assert client.get("/catalog/dimensions").json()["count"] == 9
    g = client.get("/catalog/glossary").json()
    syn = {t["term"]: t["synonyms"] for t in g["terms"]}
    assert "Faturamento" in syn["Receita"] and g["language"] == "pt-BR"
    assert any("Average order value" in s for s in syn.values())


def test_query_metric_is_audited_with_cosmos_decision(client, api_settings):
    r = client.post("/tools/query_metric", json={"metric": "net_revenue", "dimensions": ["region"]})
    assert r.status_code == 200
    qid = r.json()["query_id"]
    row = _audit(api_settings, qid)
    assert row["status"] == "ok" and row["tool_name"] == "query_metric" and row["user_id"] == "demo"
    assert row["sql_text"].startswith("SELECT") and row["source"] == "duckdb:analytics.duckdb"
    store = client.app.state.poc.runtime.services.store
    events = store.list_events(row["cosmos_episode_id"])
    decisions = [e for e in events if e.event_type == "runtime.authorization.decision"]
    results = [e for e in events if e.event_type == "runtime.adapter.result"]
    assert len(decisions) == 1 and len(results) == 1
    assert decisions[0].payload["decision"]["decision_id"] == row["cosmos_decision_id"]
    assert results[0].payload["result"]["output"] == {"query_id": qid, "row_count": 5, "status": "ok"}
    assert store.get_episode(row["cosmos_episode_id"]).state.value == "completed"
    assert client.app.state.poc.runtime.pending == {}
    ev = client.get(f"/evidence/{qid}").json()
    assert ev["referenced_query_id"] == qid and ev["cosmos_decision_id"] == row["cosmos_decision_id"]


def test_schema_failure_never_reaches_cosmos(client, api_settings):
    for tool, args in (("show_sql", {"query_id": "abc"}), ("search_concepts", {"query": ""}),
                       ("explain_metric", {"metric": "X-1"}), ("query_metric", {"metric": "net_revenue", "sql": "DROP"})):
        r = client.post(f"/tools/{tool}", json=args)
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_arguments", (tool, r.json())
        row = _audit(api_settings, r.json()["error"]["query_id"])
        assert row["status"] == "rejected" and row["cosmos_decision_id"] is None and row["cosmos_episode_id"] is None


def test_domain_failure_has_one_decision_and_one_result(client, api_settings):
    r = client.post("/tools/explain_metric", json={"metric": "metrica_x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_metric"
    row = _audit(api_settings, r.json()["error"]["query_id"])
    ev = _events(client, row["cosmos_episode_id"])
    assert ev.count("runtime.authorization.decision") == 1 and ev.count("runtime.adapter.result") == 1
    assert row["status"] == "rejected" and row["cosmos_decision_id"]


def test_error_codes_to_http(client):
    assert client.post("/tools/execute_sql", json={"sql": "select 1"}).json()["error"]["code"] == "unknown_tool"
    assert client.post("/tools/execute_sql", json={}).status_code == 404
    r = client.post("/tools/query_metric", json={"metric": "active_customers", "dimensions": ["category"]})
    assert (r.status_code, r.json()["error"]["code"]) == (422, "dimension_not_allowed")
    assert "region" in r.json()["error"]["details"]["allowed_dimensions"]
    r = client.post("/tools/show_sql", json={"query_id": str(uuid.uuid4())})
    assert (r.status_code, r.json()["error"]["code"]) == (404, "query_not_found")
    sc = client.post("/tools/search_concepts", json={"query": "ticket médio"}).json()
    r = client.post("/tools/show_sql", json={"query_id": sc["query_id"]})
    assert (r.status_code, r.json()["error"]["code"]) == (409, "no_sql_available")
    r = client.post("/tools/query_metric", content=b"{not json", headers={"content-type": "application/json"})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")


def test_request_validation(client):
    r = client.post("/chat", json={"question": "x", "extra": 1})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_request")
    r = client.post("/chat", json={"question": "   "})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_question")
    r = client.post("/chat", json={"question": "a" * 2001})
    assert r.json()["error"]["code"] == "invalid_question"
    r = client.post("/chat", json={"question": "oi", "session_id": "bad id!"})
    assert r.json()["error"]["code"] == "invalid_session_id"
    r = client.post("/tools/list_metrics", json={}, headers={"X-User-Id": "a b"})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_user_id")
    r = client.post("/chat", content=json.dumps({"question": "a" * 17000}), headers={"content-type": "application/json"})
    assert (r.status_code, r.json()["error"]["code"]) == (413, "payload_too_large")


def test_user_cannot_read_other_users_query(client):
    qid = client.post("/tools/query_metric", json={"metric": "order_count"}, headers={"X-User-Id": "alice"}).json()["query_id"]
    assert client.post("/tools/show_sql", json={"query_id": qid}, headers={"X-User-Id": "alice"}).status_code == 200
    r = client.post("/tools/show_sql", json={"query_id": qid}, headers={"X-User-Id": "bob"})
    assert (r.status_code, r.json()["error"]["code"]) == (404, "query_not_found")
    assert client.get(f"/evidence/{qid}", headers={"X-User-Id": "bob"}).status_code == 404


def test_tool_denied_when_capability_removed(client, cosmos_world, api_settings):
    gp = cosmos_world / ".cosmos" / "graph.json"
    original = gp.read_text(encoding="utf-8")
    graph = [r for r in json.loads(original)
             if not (r.get("node_type") == "capability" and any(x.get("uri") == "tool:list_metrics" for x in r.get("resources", [])))]
    gp.write_text(json.dumps(graph), encoding="utf-8")
    try:
        r = client.post("/tools/list_metrics", json={})
        assert (r.status_code, r.json()["error"]["code"]) == (403, "tool_not_authorized")
        row = _audit(api_settings, r.json()["error"]["query_id"])
        ev = _events(client, row["cosmos_episode_id"])
        assert ev.count("runtime.authorization.decision") == 1 and ev.count("runtime.adapter.result") == 0
        assert client.post("/tools/list_dimensions", json={}).status_code == 200
    finally:
        gp.write_text(original, encoding="utf-8")
    assert client.post("/tools/list_metrics", json={}).status_code == 200


def test_semantic_catalog_unavailable_and_divergence(client, cosmos_world, api_settings):
    gp = cosmos_world / ".cosmos" / "graph.json"
    original = gp.read_text(encoding="utf-8")
    try:
        gp.write_text("{quebrado", encoding="utf-8")  # provider não lê o grafo: nega tudo (fail closed)
        r = client.post("/tools/search_concepts", json={"query": "receita"})
        assert (r.status_code, r.json()["error"]["code"]) == (403, "tool_not_authorized")
        no_metrics = [r for r in json.loads(original) if r.get("entity_type") != "poc.metric"]
        gp.write_text(json.dumps(no_metrics), encoding="utf-8")  # capacidades presentes, sem poc.metric
        r = client.post("/tools/search_concepts", json={"query": "receita"})
        assert (r.status_code, r.json()["error"]["code"]) == (503, "semantic_catalog_unavailable")
        assert _audit(api_settings, r.json()["error"]["query_id"])["status"] == "error"
        assert client.get("/health").json()["status"] == "degraded"
        graph = [r for r in json.loads(original) if r.get("display_name") != "refund_amount"]
        gp.write_text(json.dumps(graph), encoding="utf-8")
        r = client.post("/tools/explain_metric", json={"metric": "refund_amount"})  # existe no YAML, falta no grafo
        assert (r.status_code, r.json()["error"]["code"]) == (500, "internal_error")
    finally:
        gp.write_text(original, encoding="utf-8")


def test_health_answers_during_slow_query(client):
    engine = client.app.state.poc.engine
    real = engine.query

    def slow(raw):
        time.sleep(1.5)
        return real(raw)

    engine.query = slow
    try:
        t = threading.Thread(target=lambda: client.post("/tools/query_metric", json={"metric": "order_count"}))
        t.start()
        time.sleep(0.2)
        start = time.perf_counter()
        assert client.get("/health").status_code == 200
        assert time.perf_counter() - start < 1.0
        t.join()
    finally:
        engine.query = real
