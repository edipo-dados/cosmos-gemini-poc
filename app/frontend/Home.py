"""Página inicial: estado dos serviços e guia das páginas."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # raiz do projeto: `app.*`

import streamlit as st  # noqa: E402
from app.frontend import theme  # noqa: E402

theme.setup("Início", "Analytics conversacional sobre dados corporativos, com semântica governada pelo Cosmos e respostas do Gemini.", "🌌")
health = theme.api_status()
theme.sidebar(health)

st.title("Cosmos Analytics POC")
st.write("As respostas vêm de métricas cadastradas no catálogo semântico, consultadas por um Query Engine controlado "
         "(DuckDB). O Gemini nunca executa SQL: ele só pede ferramentas, e cada chamada é autorizada no Cosmos e auditada.")
if health:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("API", health["status"])
    c2.metric("Gemini", "configurado" if health["gemini"] == "configured" else "não configurado")
    c3.metric("Catálogo", health["catalog_version"])
    c4.metric("Carga ETL", f"#{health['etl_run_id']}")
    if health["gemini"] != "configured":
        st.info("O chat com o Gemini está desativado porque `GEMINI_API_KEY` não está definida. "
                "As demais páginas e a consulta direta de métricas funcionam normalmente.")
st.subheader("Páginas")
st.markdown("""
- **Analytics Assistant**: perguntas em português, resposta com números, gráfico, regras, SQL e evidências.
- **Semantic Catalog**: métricas, fórmulas, dimensões, regras de negócio e glossário.
- **Data Quality**: volumes, regras de qualidade, reconciliação e histórico das cargas.
- **SQL and Evidence**: consultas executadas, SQL, resultado e rastreabilidade no Cosmos.
- **Data Overview**: indicadores e séries por mês, região e categoria.
""")
