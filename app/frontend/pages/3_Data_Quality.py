"""Página 3: volumes, regras de qualidade, reconciliação, histórico de validações e status das cargas."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # raiz do projeto: `app.*`

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from app.frontend import api_client, theme  # noqa: E402
from app.frontend.formatting import format_int  # noqa: E402

TARGETS = {"oltp": "Dados oficiais (oltp): esperado 0 violações", "dq_lab": "Laboratório de defeitos (dq_lab): inconsistências controladas"}

theme.setup("Data Quality", "Regras de qualidade, reconciliação PostgreSQL × DuckDB e histórico das cargas.", "✅")
theme.sidebar(theme.api_status())
st.title("Data Quality")

try:
    etl = api_client.get("/etl/runs")["runs"]
    runs = api_client.get("/quality/runs")["runs"]
    results = api_client.get("/quality/results")["results"]
except api_client.ApiError as exc:
    theme.show_error(exc)
    st.stop()

st.subheader("Carga mais recente")
last = next((r for r in etl if r["status"] == "success"), None)
if last:
    st.write(f"Carga ETL #{last['id']} concluída em {last['duration_ms']} ms · arquivo analítico `{last['duckdb_path']}`")
    counts = last["source_row_counts"] or {}
    st.dataframe(pd.DataFrame([{"Tabela": t, "Registros": format_int(n)} for t, n in sorted(counts.items())]),
                 hide_index=True, width="stretch")
else:
    st.info("Nenhuma carga ETL concluída.")

st.subheader("Resultado das regras")
for target, label in TARGETS.items():
    rows = [r for r in results if r["target"] == target]
    if not rows:
        continue
    failed = [r for r in rows if not r["passed"]]
    st.markdown(f"**{label}** · execução #{rows[0]['dq_run_id']} · {len(rows) - len(failed)}/{len(rows)} verificações conforme o esperado")
    st.dataframe(pd.DataFrame([{"Tipo": "regra" if r["kind"] == "rule" else "reconciliação", "Verificação": r["name"],
                                "Violações": r["violations"], "Esperado": r["expected"], "Obtido": r["actual"],
                                "Conforme": "sim" if r["passed"] else "não"} for r in rows]),
                 hide_index=True, width="stretch")

st.subheader("Histórico de validações")
st.dataframe(pd.DataFrame([{"Execução": r["id"], "Início": r["started_at"], "Alvo": r["target"], "Origem": r["trigger"],
                            "Status": r["status"], "Resumo": str(r["summary"])} for r in runs]),
             hide_index=True, width="stretch")
st.subheader("Histórico de cargas")
st.dataframe(pd.DataFrame([{"Carga": r["id"], "Início": r["started_at"], "Status": r["status"], "Duração (ms)": r["duration_ms"],
                            "Erro": r["error"]} for r in etl]), hide_index=True, width="stretch")
