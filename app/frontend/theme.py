"""Identidade visual: cabeçalho, estilo e verificação do estado da API (todas as páginas)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # `streamlit run app/frontend/Home.py` põe só a pasta do script no sys.path
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402
from app.frontend import api_client  # noqa: E402

CSS = """
<style>
h1, h2, h3 { color: #1F4E79; letter-spacing: -0.01em; }
[data-testid="stMetricValue"] { color: #1F4E79; }
.poc-banner { border-left: 4px solid #1F4E79; background: #F1F4F8; padding: .6rem 1rem; border-radius: 4px; margin-bottom: 1rem; }
.poc-banner small { color: #4A5868; }
</style>
"""


def setup(title: str, subtitle: str, icon: str = "📊") -> None:
    st.set_page_config(page_title=f"{title} · Cosmos Analytics POC", page_icon=icon, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(f'<div class="poc-banner"><strong>Cosmos Analytics POC</strong> · {title}<br><small>{subtitle}</small></div>',
                unsafe_allow_html=True)


def api_status() -> dict | None:
    """`/health` da API, ou `None` (com aviso na tela) se a API estiver fora do ar."""
    try:
        return api_client.health()
    except api_client.ApiError as exc:
        st.error(f"API indisponível: {exc.message}")
        return None


def show_error(exc: api_client.ApiError) -> None:
    st.error(f"{exc.message} (código: {exc.code})")


def sidebar(health: dict | None) -> None:
    with st.sidebar:
        st.caption("Estado dos serviços")
        if not health:
            st.write("API: indisponível")
            return
        st.write(f"API: {health['status']}")
        st.write(f"PostgreSQL: {health['postgres']} · DuckDB: {health['duckdb']} · Cosmos: {health['cosmos']}")
        st.write("Gemini: " + ("configurado" if health["gemini"] == "configured" else "não configurado"))
        st.caption(f"Catálogo {health['catalog_version']} · carga ETL #{health['etl_run_id']}")
