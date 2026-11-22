"""Página 5: indicadores e séries por mês, região e categoria (Query Engine, via GET /overview)."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # raiz do projeto: `app.*`

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from app.frontend import api_client, charts, theme  # noqa: E402
from app.frontend.formatting import format_value  # noqa: E402

theme.setup("Data Overview", "Indicadores calculados pelas métricas governadas, sobre todo o histórico carregado.", "📈")
theme.sidebar(theme.api_status())
st.title("Data Overview")


@st.cache_data(ttl=300, show_spinner="Calculando indicadores...")
def load_overview(url: str) -> dict:
    return api_client.get("/overview")


try:
    data = load_overview(api_client.api_url())
except api_client.ApiError as exc:
    theme.show_error(exc)
    st.stop()

for err in data.get("errors", []):
    st.warning(f"Indicador indisponível: {err['metric']} ({(err.get('error') or {}).get('code')})")
order = ["gross_revenue", "net_revenue", "average_order_value", "active_customers", "order_count", "cancellation_rate"]
cols = st.columns(3)
for i, name in enumerate([m for m in order if m in data["kpis"]]):
    k = data["kpis"][name]
    cols[i % 3].metric(k["business_name"], format_value(k["value"], name, k["value_type"]))
st.caption(f"Catálogo `{data['catalog_version']}`. Os indicadores usam as mesmas regras de negócio do assistente "
           "(por exemplo, receita só de pedidos pagos).")

TITLES = {"month": "Receita líquida por mês", "region": "Receita líquida por região", "category": "Receita líquida por categoria"}
for dim, title in TITLES.items():
    s = data["series"].get(dim)
    if not s:
        continue
    st.subheader(title)
    fig = charts.result_chart(s["rows"], s["metric"], s["value_type"])
    if fig is not None:
        st.plotly_chart(fig, width="stretch", key=f"ov-{dim}")
    with st.expander("Ver tabela"):
        st.dataframe(pd.DataFrame([{dim: r[dim], s["business_name"]: format_value(r["value"], s["metric"], s["value_type"])}
                                   for r in s["rows"]]), hide_index=True, width="stretch")
