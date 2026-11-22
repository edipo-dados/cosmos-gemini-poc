"""Gráficos Plotly. Os valores chegam como string/número da API e só aqui viram float para desenhar."""
from __future__ import annotations
import plotly.graph_objects as go
from app.frontend.formatting import format_value, kind_of, to_decimal

PALETTE = ["#1F4E79", "#2E86AB", "#6C8EAD", "#A3B8CC", "#C97B2B", "#7A9E7E"]
TIME_DIMS = {"date", "month", "year"}


def _num(v) -> float | None:
    d = to_decimal(v)
    return None if d is None else float(d)


def _layout(fig: go.Figure, title: str | None) -> go.Figure:
    fig.update_layout(title=title, template="simple_white", height=340, margin=dict(l=10, r=10, t=50 if title else 10, b=10),
                      font=dict(family="sans-serif", color="#1B2430"), showlegend=False)
    return fig


def result_chart(rows: list[dict], metric: str | None, value_type: str | None = None, title: str | None = None):
    """Barras (ou linha para dimensões de tempo) quando há exatamente uma dimensão; `None` se não couber gráfico."""
    if not rows:
        return None
    dims = [k for k in rows[0] if k != "value"]
    if len(dims) != 1 or "value" not in rows[0]:
        return None
    dim = dims[0]
    data = [(str(r[dim]), _num(r["value"])) for r in rows if _num(r["value"]) is not None]
    if not data:
        return None
    if dim in TIME_DIMS:
        data.sort(key=lambda x: x[0])
    x, y = [d[0] for d in data], [d[1] for d in data]
    kind = kind_of(metric, value_type)
    scale = 100 if kind == "percent" else 1
    y = [v * scale for v in y]
    text = [format_value(v / scale, metric, value_type) for v in y]
    if dim in TIME_DIMS:
        fig = go.Figure(go.Scatter(x=x, y=y, mode="lines+markers", line=dict(color=PALETTE[0], width=2), hovertext=text,
                                   hoverinfo="text+x"))
    else:
        fig = go.Figure(go.Bar(x=x, y=y, marker_color=PALETTE[0], hovertext=text, hoverinfo="text+x"))
    fig.update_yaxes(ticksuffix="%" if kind == "percent" else "")
    return _layout(fig, title)
