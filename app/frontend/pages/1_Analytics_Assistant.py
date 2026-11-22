"""Página 1: chat com o Gemini (ferramentas governadas) e consulta direta de métricas (não depende de chave)."""
from __future__ import annotations
import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # raiz do projeto: `app.*`

import streamlit as st  # noqa: E402
from app.frontend import api_client, components, theme  # noqa: E402

EXAMPLES = [
    "Qual foi o faturamento dos últimos 30 dias?",
    "Qual região teve a maior receita?",
    "Qual categoria possui o maior ticket médio?",
    "Quantos clientes ativos temos?",
    "Compare o faturamento dos últimos dois meses.",
    "Qual é a taxa de cancelamento?",
    "Explique como o faturamento líquido é calculado.",
]

theme.setup("Analytics Assistant", "Pergunte em português. Cada número vem de uma métrica governada, com SQL e evidências.", "💬")
health = theme.api_status()
theme.sidebar(health)
st.title("Analytics Assistant")


@st.cache_data(ttl=300, show_spinner=False)
def load_metrics(url: str) -> list[dict]:
    return api_client.get("/catalog/metrics")["metrics"]


def run_chat(has_key: bool) -> None:
    if not has_key:
        st.warning("O chat está indisponível: a variável `GEMINI_API_KEY` não está definida na API. "
                   "Use a aba **Consulta direta de métrica**, que funciona sem o Gemini.")
        return
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("session_id", str(uuid.uuid4()))
    st.caption("Exemplos de perguntas")
    cols = st.columns(2)
    clicked = None
    for i, example in enumerate(EXAMPLES):
        if cols[i % 2].button(example, key=f"ex{i}", width="stretch"):
            clicked = example
    prompt = st.chat_input("Pergunte sobre receita, pedidos, clientes, cancelamentos...") or clicked
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        try:
            with st.spinner("Consultando o catálogo e os dados..."):
                resp = api_client.chat(prompt, st.session_state.session_id)
            st.session_state.messages.append({"role": "assistant", "content": resp["answer"], "queries": resp.get("queries", []),
                                              "status": resp["status"], "model": resp.get("model")})
        except api_client.ApiError as exc:
            st.session_state.messages.append({"role": "assistant", "content": f"Não foi possível responder: {exc.message} "
                                              f"(código: {exc.code})", "queries": [], "status": "error"})
    for n, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            for j, q in enumerate(msg.get("queries", [])):
                components.render_query(q, key=f"{n}-{j}")


def run_direct() -> None:
    st.write("Consulte uma métrica cadastrada sem passar pelo Gemini. A chamada usa `POST /tools/query_metric` "
             "(autorizada no Cosmos e auditada), como o agente faria.")
    try:
        metrics = load_metrics(api_client.api_url())
    except api_client.ApiError as exc:
        theme.show_error(exc)
        return
    by_name = {m["name"]: m for m in metrics}
    name = st.selectbox("Métrica", list(by_name), format_func=lambda n: f"{by_name[n]['business_name']} ({n})", key="dm_metric")
    metric = by_name[name]
    st.caption(metric["description"])
    dims = st.multiselect("Dimensões", metric["allowed_dimensions"], max_selections=3, key=f"dm_dims_{name}")
    c1, c2, c3 = st.columns(3)
    use_from = c1.checkbox("Data inicial", key="dm_use_from")
    date_from = c1.date_input("De", value=date(2026, 1, 1), disabled=not use_from, key="dm_from")
    use_to = c2.checkbox("Data final", key="dm_use_to")
    date_to = c2.date_input("Até", value=date(2026, 10, 31), disabled=not use_to, key="dm_to")
    limit = c3.number_input("Limite de linhas", min_value=1, max_value=1000, value=100, key="dm_limit")
    if st.button("Consultar", type="primary", key="dm_run"):
        args: dict = {"metric": name, "dimensions": dims, "limit": int(limit)}
        if use_from:
            args["date_from"] = date_from.isoformat()
        if use_to:
            args["date_to"] = date_to.isoformat()
        try:
            out = api_client.query_metric(args)
            st.session_state["direct_view"] = components.view_from_audit(api_client.get(f"/audit/queries/{out['query_id']}"))
            st.session_state.pop("direct_error", None)
        except api_client.ApiError as exc:
            st.session_state["direct_error"] = exc
            st.session_state.pop("direct_view", None)
    if "direct_error" in st.session_state:
        theme.show_error(st.session_state["direct_error"])
    if "direct_view" in st.session_state:
        components.render_query(st.session_state["direct_view"], key="direct")


tab_chat, tab_direct = st.tabs(["Chat", "Consulta direta de métrica"])
with tab_chat:
    run_chat(bool(health) and health["gemini"] == "configured")
with tab_direct:
    run_direct()
