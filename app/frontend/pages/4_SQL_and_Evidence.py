"""Página 4: consultas auditadas, SQL executado, resultado e rastreabilidade no Cosmos."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # raiz do projeto: `app.*`

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from app.frontend import api_client, components, theme  # noqa: E402

theme.setup("SQL and Evidence", "Cada chamada de ferramenta é auditada: SQL, parâmetros, resultado e decisão de autorização do Cosmos.", "🔎")
theme.sidebar(theme.api_status())
st.title("SQL and Evidence")
st.caption(f"Consultas do usuário `{api_client.user_id()}`.")

try:
    items = api_client.get("/audit/queries", limit=100)["queries"]
except api_client.ApiError as exc:
    theme.show_error(exc)
    st.stop()

if not items:
    st.info("Nenhuma consulta auditada ainda. Faça uma pergunta no Analytics Assistant ou use a consulta direta de métrica.")
    st.stop()

st.dataframe(pd.DataFrame([{"Quando": i["created_at"], "Ferramenta": i["tool_name"], "Métrica": i["metric"], "Status": i["status"],
                            "Linhas": i["row_count"], "Duração (ms)": i["duration_ms"], "query_id": i["query_id"]} for i in items]),
             hide_index=True, width="stretch")
labels = {i["query_id"]: f"{i['created_at'][:19]} · {i['tool_name']} · {i['metric'] or '-'} · {i['status']}" for i in items}
chosen = st.selectbox("Detalhar consulta", list(labels), format_func=labels.get, key="audit_pick")
try:
    q = components.view_from_audit(api_client.get(f"/audit/queries/{chosen}"))
except api_client.ApiError as exc:
    theme.show_error(exc)
    st.stop()
components.render_query(q, key="audit")
if q["tool"] == "query_metric" and q["status"] == "ok" and q.get("sql"):
    st.caption("O SQL acima foi montado pelo Query Engine a partir da definição da métrica; o Gemini não o escreve.")
