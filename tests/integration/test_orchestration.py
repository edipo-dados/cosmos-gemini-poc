"""Loop de Function Calling com o SDK google-genai real e um transporte HTTP roteirizado (NÃO é o Gemini).
Prova: o loop manual, a passagem de cada chamada pelo Cosmos e pelo Query Engine, a auditoria e os estados finais.
Não prova: que o Gemini real escolhe estas ferramentas ou redige estas respostas (ver tests/live)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text as sql

from app.db import make_engine
from conftest import FAKE_GEMINI_KEY
from support.fake_gemini import blocked, call, calls, function_responses, http_error, last_response, text

GOLDEN = {c["id"]: c for c in json.loads((Path(__file__).resolve().parents[1] / "golden" / "expected.json")
                                         .read_text(encoding="utf-8"))["cases"]}


def _turn(settings, turn_id):
    eng = make_engine("app", settings)
    try:
        with eng.connect() as c:
            return dict(c.execute(sql("SELECT * FROM audit.chat_turn WHERE turn_id=:t"), {"t": turn_id}).mappings().one())
    finally:
        eng.dispose()


def _episode_state(client, episode_id):
    return client.app.state.poc.runtime.services.store.get_episode(episode_id).state.value


def _events(client, episode_id):
    return [e.event_type for e in client.app.state.poc.runtime.services.store.list_events(episode_id)]


def _answer_from_query(body):
    out = function_responses(body)[1]["response"]["output"]  # 2a resposta de função: query_metric
    return text(f"A região com maior receita líquida foi {out['rows'][0]['region']}, com R$ {out['rows'][0]['value']} "
                f"(query_id {out['query_id']}).")


def test_health_reports_configured(chat_client):
    h = chat_client.get("/health").json()
    assert h["gemini"] == "configured" and h["gemini_model"] == "scripted-model"


def test_full_tool_loop(chat_client, fake_gemini, api_settings):
    fake_gemini.load(
        call("search_concepts", {"query": "receita"}),
        call("query_metric", {"metric": "net_revenue", "dimensions": ["region"],
                              "order_by": {"field": "metric", "direction": "desc"}, "limit": 1}),
        lambda body: call("show_sql", {"query_id": last_response(body)["output"]["query_id"]}),
        _answer_from_query,
    )
    r = chat_client.post("/chat", json={"question": "Qual região teve a maior receita?", "session_id": "s-loop"})
    assert r.status_code == 200, r.json()
    out = r.json()
    top = max(GOLDEN["net_revenue.by_region"]["rows"], key=lambda x: float(x["value"]))
    assert out["status"] == "ok" and top["region"] in out["answer"] and top["value"] in out["answer"]
    assert [c["tool"] for c in out["tool_calls"]] == ["search_concepts", "query_metric", "show_sql"]
    assert all(c["status"] == "ok" for c in out["tool_calls"])
    q = out["queries"][0]
    assert q["metric"] == "net_revenue" and q["rows"] == [{"region": top["region"], "value": top["value"]}]
    assert q["sql"].startswith("SELECT") and q["rules"]["denominator"] and q["cosmos_decision_id"]
    assert q["query_id"] in out["answer"]
    # o SDK real enviou as respostas de função ao "modelo"; o resultado de query_metric não leva SQL
    assert len(fake_gemini.requests) == 4
    frs = function_responses(fake_gemini.requests[-1])
    assert [f["name"] for f in frs] == ["search_concepts", "query_metric", "show_sql"]
    assert "sql" not in frs[1]["response"]["output"]
    assert set(fake_gemini.api_keys) == {FAKE_GEMINI_KEY}
    # um episódio Cosmos para a pergunta, 3 decisões e 3 resultados; chat_turn finalizado
    eid = out["cosmos_episode_id"]
    ev = _events(chat_client, eid)
    assert ev.count("runtime.authorization.decision") == 3 and ev.count("runtime.adapter.result") == 3
    assert _episode_state(chat_client, eid) == "completed"
    turn = _turn(api_settings, out["turn_id"])
    assert turn["status"] == "ok" and turn["answer"] == out["answer"] and turn["cosmos_episode_id"] == eid
    assert turn["gemini_model"] == "scripted-model"


def test_session_history_is_sent(chat_client, fake_gemini):
    fake_gemini.load(text("Primeira resposta."))
    chat_client.post("/chat", json={"question": "Pergunta um", "session_id": "s-hist"})
    fake_gemini.load(text("Segunda resposta."))
    chat_client.post("/chat", json={"question": "Pergunta dois", "session_id": "s-hist"})
    texts = [p.get("text") for c in fake_gemini.requests[0]["contents"] for p in c["parts"]]
    assert texts == ["Pergunta um", "Primeira resposta.", "Pergunta dois"]


@pytest.mark.parametrize("args,code", [
    ({"metric": "lucro"}, "unknown_metric"),
    ({"metric": "active_customers", "dimensions": ["category"]}, "dimension_not_allowed"),
])
def test_domain_errors_go_back_to_model(chat_client, fake_gemini, args, code):
    fake_gemini.load(call("query_metric", args),
                     lambda body: text(f"Não foi possível: {last_response(body)['error']['code']}."))
    out = chat_client.post("/chat", json={"question": "pergunta"}).json()
    assert out["status"] == "ok" and code in out["answer"]
    assert out["tool_calls"][0]["error_code"] == code
    err = last_response(fake_gemini.requests[1])["error"]
    assert err["code"] == code and err["details"]


def test_ambiguous_question_returns_two_candidates(chat_client, fake_gemini):
    fake_gemini.load(call("search_concepts", {"query": "receita"}),
                     lambda body: text("Receita pode ser: " + ", ".join(
                         sorted({m for r in last_response(body)["output"]["results"] for m in r.get("maps_to", [])}))))
    out = chat_client.post("/chat", json={"question": "Qual a receita?"}).json()
    assert "gross_revenue" in out["answer"] and "net_revenue" in out["answer"]


def test_parallel_calls_in_one_round(chat_client, fake_gemini):
    fake_gemini.load(calls(("query_metric", {"metric": "gross_revenue"}), ("query_metric", {"metric": "net_revenue"})),
                     text("ok"))
    out = chat_client.post("/chat", json={"question": "bruta e líquida"}).json()
    assert [q["metric"] for q in out["queries"]] == ["gross_revenue", "net_revenue"]
    assert {c["round"] for c in out["tool_calls"]} == {1}


def test_iteration_limit_is_incomplete(chat_client, fake_gemini, api_settings):
    fake_gemini.load(*[call("list_metrics")] * 7)
    out = chat_client.post("/chat", json={"question": "loop"}).json()
    assert out["status"] == "incomplete" and len(out["tool_calls"]) == 6
    assert _turn(api_settings, out["turn_id"])["status"] == "incomplete"
    assert _episode_state(chat_client, out["cosmos_episode_id"]) == "completed"


def test_blocked_response(chat_client, fake_gemini, api_settings):
    fake_gemini.load(blocked())
    out = chat_client.post("/chat", json={"question": "algo bloqueado"}).json()
    assert out["status"] == "blocked" and "segurança" in out["answer"]
    assert _turn(api_settings, out["turn_id"])["status"] == "blocked"


def _last_turn(settings):
    eng = make_engine("app", settings)
    try:
        with eng.connect() as c:
            return dict(c.execute(sql("SELECT * FROM audit.chat_turn ORDER BY created_at DESC LIMIT 1")).mappings().one())
    finally:
        eng.dispose()


@pytest.mark.parametrize("resp,http,code", [
    (http_error(401, "UNAUTHENTICATED", f"API key {FAKE_GEMINI_KEY} invalid"), 503, "gemini_auth_failed"),
    (http_error(404, "NOT_FOUND", "model not found"), 503, "gemini_model_invalid"),
])
def test_fatal_gemini_errors(chat_client, fake_gemini, api_settings, resp, http, code):
    fake_gemini.load(resp)
    r = chat_client.post("/chat", json={"question": f"erro {code}"})
    assert (r.status_code, r.json()["error"]["code"]) == (http, code)
    assert FAKE_GEMINI_KEY not in r.text
    turn = _last_turn(api_settings)
    assert turn["question"] == f"erro {code}" and turn["status"] == "error"
    assert _episode_state(chat_client, turn["cosmos_episode_id"]) == "failed"


def test_transient_errors_become_502(chat_client, fake_gemini, monkeypatch):
    monkeypatch.setattr(chat_client.app.state.poc.llm, "_sleep", lambda s: None)
    fake_gemini.load(*[http_error(503, "UNAVAILABLE", "x")] * 3)
    r = chat_client.post("/chat", json={"question": "indisponível"})
    assert (r.status_code, r.json()["error"]["code"]) == (502, "llm_unavailable")
    assert len(fake_gemini.requests) == 3


def test_key_never_in_logs(chat_client, fake_gemini, api_settings):
    """Prova do requisito "logs sem API key": o servidor devolve a chave na mensagem de erro e o log não a contém."""
    fake_gemini.load(http_error(401, "UNAUTHENTICATED", f"API key {FAKE_GEMINI_KEY} invalid"))
    chat_client.post("/chat", json={"question": "teste de log"})
    log = (api_settings.log_path / "api.log").read_text(encoding="utf-8")
    assert "gemini_auth_failed" in log  # o caso 401 (com a chave na mensagem do servidor) foi registrado
    assert FAKE_GEMINI_KEY not in log
