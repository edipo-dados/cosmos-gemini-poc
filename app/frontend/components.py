"""Blocos de tela compartilhados: resultado de uma consulta, regras, SQL e evidências."""
from __future__ import annotations
import pandas as pd
import streamlit as st
from app.frontend import charts
from app.frontend.formatting import format_value

RULE_LABELS = {"denominator": "Denominador", "status_rule": "Tratamento de status", "time_basis": "Base de tempo"}
FILTER_LABELS = {"date_from": "data inicial", "date_to": "data final"}


def view_from_audit(row: dict) -> dict:
    """Converte uma linha de `audit.query_audit` (GET /audit/queries/{id}) no formato `queries[]` do /chat."""
    ev, res, flt = row.get("evidence") or {}, row.get("result") or {}, row.get("filters") or {}
    return {"query_id": row["query_id"], "tool": row["tool_name"], "status": row["status"], "error_code": row.get("error_code"),
            "metric": row.get("metric"), "business_name": ev.get("business_name"), "metric_version": ev.get("metric_version"),
            "dimensions": row.get("dimensions"), "filters": flt, "rules": ev.get("rules"), "sql": row.get("sql_text"),
            "sql_params": row.get("sql_params"), "source": row.get("source"), "catalog_version": row.get("catalog_version"),
            "etl_run_id": row.get("etl_run_id"), "row_count": row.get("row_count"), "columns": res.get("columns"),
            "rows": res.get("rows"), "truncated": res.get("truncated"), "cosmos_episode_id": row.get("cosmos_episode_id"),
            "cosmos_decision_id": row.get("cosmos_decision_id"), "error": ev.get("error"),
            "value_type": ev.get("value_type")}


def rows_frame(q: dict) -> pd.DataFrame:
    rows = q.get("rows") or []
    df = pd.DataFrame(rows)
    if not df.empty and "value" in df.columns:
        df["value"] = [format_value(v, q.get("metric"), q.get("value_type")) for v in df["value"]]
        df = df.rename(columns={"value": q.get("business_name") or "valor"})
    return df


def filters_summary(q: dict) -> list[str]:
    """Filtros efetivamente aplicados (`filters.applied`): regra-base da métrica, período e filtros pedidos."""
    flt = q.get("filters")
    applied = flt.get("applied") if isinstance(flt, dict) else None
    lines = []
    for f in applied or []:
        if not isinstance(f, dict):
            lines.append(str(f))
        elif f.get("type") == "base_filter":
            lines.append(f"regra da métrica: {f.get('rule')}")
        elif "dimension" in f:
            lines.append(f"{f['dimension']} {f.get('op', '=')} {f.get('value')}")
        else:
            label = FILTER_LABELS.get(str(f.get("type")), str(f.get("type")))
            lines.append(f"{label}: {f.get('value')}")
    return lines


def render_query(q: dict, key: str, show_chart: bool = True) -> None:
    """Resultado, gráfico, regras de negócio, filtros, SQL executado e evidências de uma chamada de ferramenta."""
    if q.get("status") != "ok":
        err = q.get("error") or {}
        st.warning(f"A chamada `{q.get('tool')}` foi {q.get('status')}: {err.get('message') or q.get('error_code') or 'sem detalhes'}")
        return
    if q.get("tool") != "query_metric":
        st.caption(f"Ferramenta `{q.get('tool')}` · query_id `{q['query_id']}`")
        return
    title = f"{q.get('business_name') or q['metric']} (`{q['metric']}` v{q.get('metric_version')})"
    st.markdown(f"**{title}**")
    rows = q.get("rows") or []
    if len(rows) == 1 and set(rows[0]) == {"value"}:
        st.metric(q.get("business_name") or q["metric"], format_value(rows[0]["value"], q["metric"], q.get("value_type")))
    else:
        st.dataframe(rows_frame(q), hide_index=True, width="stretch")
        fig = charts.result_chart(rows, q["metric"], q.get("value_type")) if show_chart else None
        if fig is not None:
            st.plotly_chart(fig, width="stretch", key=f"chart-{key}")
    if q.get("truncated"):
        st.caption("Resultado truncado pelo limite de linhas.")
    with st.expander("Métrica, regras de negócio, dimensões e filtros"):
        st.write(f"**Métrica:** {q.get('business_name')} (`{q['metric']}`), versão {q.get('metric_version')}")
        st.write("**Dimensões:** " + (", ".join(q.get("dimensions") or []) or "nenhuma (total)"))
        flt = filters_summary(q)
        st.write("**Filtros:** " + ("; ".join(flt) if flt else "nenhum além das regras da métrica"))
        for k, label in RULE_LABELS.items():
            if (q.get("rules") or {}).get(k):
                st.write(f"**{label}:** {q['rules'][k]}")
    with st.expander("SQL executado"):
        if q.get("sql"):
            st.code(q["sql"], language="sql")
            st.write("Parâmetros:")
            st.json(q.get("sql_params") or [])
        else:
            st.write("Sem SQL para esta chamada.")
    with st.expander("Evidências e rastreabilidade"):
        st.write(f"**Fonte:** `{q.get('source')}`")
        st.write(f"**Versão do catálogo:** `{q.get('catalog_version')}` · **carga ETL:** #{q.get('etl_run_id')}")
        st.write(f"**Linhas retornadas:** {q.get('row_count')}")
        st.write(f"**query_id:** `{q['query_id']}`")
        st.write(f"**Episódio Cosmos:** `{q.get('cosmos_episode_id')}` · **decisão de autorização:** `{q.get('cosmos_decision_id')}`")
