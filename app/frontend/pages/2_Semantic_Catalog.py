"""Página 2: catálogo semântico (métricas, fórmulas, dimensões, regras, glossário e responsáveis)."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # raiz do projeto: `app.*`

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from app.frontend import api_client, theme  # noqa: E402

theme.setup("Semantic Catalog", "Definições governadas: o agente só consulta o que está cadastrado aqui.", "📚")
theme.sidebar(theme.api_status())
st.title("Semantic Catalog")

try:
    metrics = api_client.get("/catalog/metrics")
    dims = api_client.get("/catalog/dimensions")
    gloss = api_client.get("/catalog/glossary")
except api_client.ApiError as exc:
    theme.show_error(exc)
    st.stop()

st.caption(f"Versão do catálogo: `{metrics['catalog_version']}` · glossário `{gloss['glossary_version']}` · {metrics['count']} métricas")
tab_m, tab_d, tab_g = st.tabs(["Métricas", "Dimensões", "Glossário"])
with tab_m:
    st.dataframe(pd.DataFrame([{"Métrica": m["name"], "Nome de negócio": m["business_name"], "Responsável": m["owner"],
                                "Versão": m["version"], "Fonte": ", ".join(m["source"]) if isinstance(m["source"], list) else m["source"],
                                "Dimensões": ", ".join(m["allowed_dimensions"])} for m in metrics["metrics"]]),
                 hide_index=True, width="stretch")
    for m in metrics["metrics"]:
        with st.expander(f"{m['business_name']} (`{m['name']}`) · v{m['version']}"):
            st.write(m["description"])
            st.write("**Fórmula:**")
            st.code(m["formula"], language="text")
            st.write(f"**Denominador:** {m['denominator']}")
            st.write(f"**Tratamento de status:** {m['status_rule']}")
            st.write(f"**Base de tempo:** {m['time_basis']}")
            st.write(f"**Responsável:** {m['owner']}")
            st.write("**Dimensões permitidas:** " + ", ".join(m["allowed_dimensions"]))
            st.write("**Filtros aplicáveis:** " + ", ".join(str(f) for f in m["applicable_filters"]))
            st.write("**Regras de negócio:**")
            for r in m["rules"]:
                st.markdown(f"- **{r['title']}**: {r['statement']}")
            st.write("**Testes de validação:** " + ", ".join(f"{t['id']} ({t['type']})" for t in m["tests"]))
with tab_d:
    st.dataframe(pd.DataFrame([{"Dimensão": d["name"], "Nome de negócio": d["business_name"], "Tipo": d["type"],
                                "Descrição": d["description"], "Métricas que aceitam": ", ".join(d["allowed_for_metrics"])}
                               for d in dims["dimensions"]]), hide_index=True, width="stretch")
with tab_g:
    st.dataframe(pd.DataFrame([{"Termo": t["term"], "Sinônimos": ", ".join(t["synonyms"]), "Definição": t["definition"],
                                "Aponta para": ", ".join(f"{x['type']}:{x['name']}" for x in t["maps_to"])}
                               for t in gloss["terms"]]), hide_index=True, width="stretch")
