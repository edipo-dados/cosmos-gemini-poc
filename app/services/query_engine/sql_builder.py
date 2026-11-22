"""Construção do SQL controlado.

Regras:
- Identificadores (tabelas, colunas, expressões, junções, aliases) vêm só do catálogo YAML.
- Valores de filtro, datas e limite entram como parâmetros `?` do DuckDB. Texto do usuário nunca vira SQL.
- O resultado é uma única instrução SELECT/WITH (conferida por `assert_single_select`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from semantic.loader import Catalog

from .errors import QueryEngineError
from .validation import ValidFilter, ValidQuery

TIME_DIMENSIONS = ("date", "month", "year")


@dataclass(frozen=True)
class BuiltQuery:
    sql: str
    params: list
    columns: list[str]
    filters_applied: list[dict]


def assert_single_select(sql: str) -> None:
    """Defesa extra: uma instrução só, começando em SELECT ou WITH, sem `;` fora de literais.
    A garantia real de somente leitura é a conexão DuckDB com read_only=True."""
    without_literals = re.sub(r"'(?:[^']|'')*'", "''", sql)
    if ";" in without_literals:
        raise QueryEngineError("internal_error", "SQL com mais de uma instrução.")
    if not re.match(r"^\s*(SELECT|WITH)\b", without_literals, re.IGNORECASE):
        raise QueryEngineError("internal_error", "O SQL deve começar com SELECT ou WITH.")


def _param(dim: dict, value):
    """Valor do parâmetro e o marcador SQL correspondente."""
    if dim["type"] == "date":
        return value.isoformat(), "CAST(? AS DATE)"
    return value, "?"


def _predicate(dim: dict, expr: str, f: ValidFilter, params: list) -> str:
    if f.op in ("eq", "gte", "lte"):
        v, ph = _param(dim, f.value)
        params.append(v)
        return f"{expr} {({'eq': '=', 'gte': '>=', 'lte': '<='})[f.op]} {ph}"
    if f.op == "between":
        marks = []
        for item in f.value:
            v, ph = _param(dim, item)
            params.append(v)
            marks.append(ph)
        return f"{expr} BETWEEN {marks[0]} AND {marks[1]}"
    marks = []
    for item in f.value:
        v, ph = _param(dim, item)
        params.append(v)
        marks.append(ph)
    return f"{expr} IN ({', '.join(marks)})"


def _closure(catalog: Catalog, names: list[str]) -> list[str]:
    """Junções pedidas mais as exigidas, na ordem de declaração em sources.yaml."""
    joins = catalog.sources["joins"]
    needed: set[str] = set()

    def add(n: str):
        if n in needed:
            return
        needed.add(n)
        for r in joins[n]["requires"]:
            add(r)

    for n in names:
        add(n)
    return [n for n in joins if n in needed]


def _from_clause(catalog: Catalog, grain: str, join_names: list[str]) -> str:
    base = catalog.sources["grains"][grain]
    names = [n for n in join_names if not (grain == "item" and n == "items")]
    parts = [base] + [catalog.sources["joins"][n]["clause"] for n in _closure(catalog, names)
                      if not (grain == "item" and n == "items")]
    return " ".join(parts)


def _describe(f: ValidFilter) -> dict:
    def fmt(v):
        return v.isoformat() if isinstance(v, date) else v
    value = [fmt(x) for x in f.value] if isinstance(f.value, list) else fmt(f.value)
    return {"dimension": f.dimension, "op": f.op, "value": value}


def _default_order(dims: list[str]) -> list[str]:
    time_dims = [d for d in dims if d in TIME_DIMENSIONS]
    if time_dims:
        rest = [d for d in dims if d not in time_dims]
        return [f'"{time_dims[0]}" ASC'] + [f'"{d}" ASC' for d in rest]
    if dims:
        return ['"value" DESC NULLS LAST'] + [f'"{d}" ASC' for d in dims]
    return []


def _order_by(q: ValidQuery) -> str:
    if q.order_field:
        first = f'"{q.order_field}" {q.order_direction.upper()} NULLS LAST'
        rest = [f'"{d}" ASC' for d in q.dimensions if d != q.order_field]
        items = [first] + rest
    else:
        items = _default_order(q.dimensions)
    return f" ORDER BY {', '.join(items)}" if items else ""


def build(catalog: Catalog, q: ValidQuery) -> BuiltQuery:
    metric = catalog.metrics[q.metric]
    built = _build_growth(catalog, metric, q) if metric.get("kind") == "growth" else _build_standard(catalog, metric, q)
    assert_single_select(built.sql)
    return built


def _build_standard(catalog: Catalog, metric: dict, q: ValidQuery) -> BuiltQuery:
    dims = [catalog.dimensions[d] for d in q.dimensions]
    filter_dims = [catalog.dimensions[f.dimension] for f in q.filters]
    join_names = list(metric["joins"])
    for d in dims + filter_dims:
        join_names += d["requires_joins"]
    params: list = []
    where: list[str] = []
    applied: list[dict] = []
    if metric["base_filter"]:
        where.append(metric["base_filter"])
        applied.append({"type": "base_filter", "sql": metric["base_filter"], "rule": metric["status_rule"]})
    for f in q.filters:
        where.append(_predicate(catalog.dimensions[f.dimension], catalog.dimensions[f.dimension]["expression"], f, params))
        applied.append({"type": "filter", **_describe(f)})
    if metric.get("window"):
        start = q.as_of - timedelta(days=metric["window"]["days"] - 1)
        where.append("o.order_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)")
        params += [start.isoformat(), q.as_of.isoformat()]
        applied.append({"type": "window", "days": metric["window"]["days"], "start": start.isoformat(),
                        "as_of": q.as_of.isoformat()})
    else:
        if q.date_from:
            where.append("o.order_date >= CAST(? AS DATE)")
            params.append(q.date_from.isoformat())
            applied.append({"type": "date_from", "value": q.date_from.isoformat()})
        if q.date_to:
            where.append("o.order_date <= CAST(? AS DATE)")
            params.append(q.date_to.isoformat())
            applied.append({"type": "date_to", "value": q.date_to.isoformat()})
    select = [f'{d["expression"]} AS "{d["name"]}"' for d in dims] + [f'{metric["expression"]} AS "value"']
    sql = f"SELECT {', '.join(select)} FROM {_from_clause(catalog, metric['grain'], join_names)}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if dims:
        sql += " GROUP BY " + ", ".join(str(i + 1) for i in range(len(dims)))
    sql += _order_by(q) + " LIMIT ?"
    params.append(q.limit + 1)
    return BuiltQuery(sql, params, [d["name"] for d in dims] + ["value"], applied)


def _build_growth(catalog: Catalog, metric: dict, q: ValidQuery) -> BuiltQuery:
    base = catalog.metrics[metric["base_metric"]]
    part_dims = [d for d in q.dimensions if d != "month"]
    pdefs = [catalog.dimensions[d] for d in part_dims]
    month_dim = catalog.dimensions["month"]
    applied: list[dict] = [{"type": "base_filter", "sql": base["base_filter"], "rule": metric["status_rule"]}]

    # Filtros categóricos (região, segmento) valem na série e no esqueleto; filtro de mês vale depois do LAG.
    cat_filters = [f for f in q.filters if f.dimension != "month"]
    month_filters = [f for f in q.filters if f.dimension == "month"]
    join_names = list(base["joins"])
    for d in pdefs + [catalog.dimensions[f.dimension] for f in cat_filters]:
        join_names += d["requires_joins"]

    # esqueleto: calendário completo x valores de cada dimensão de partição
    skeleton_from = "(SELECT DISTINCT strftime(date_key, '%Y-%m') AS \"month\" FROM dim_date) cal"
    for i, d in enumerate(pdefs):
        dom = d["domain"]
        skeleton_from += f' CROSS JOIN (SELECT DISTINCT {dom["column"]} AS "{d["name"]}" FROM {dom["table"]}) p{i}'
    skel_cols = ['cal."month"'] + [f'p{i}."{d["name"]}"' for i, d in enumerate(pdefs)]
    skel_where: list[str] = []
    skel_params: list = []
    for f in cat_filters:
        if f.dimension in part_dims:
            i = part_dims.index(f.dimension)
            skel_where.append(_predicate(catalog.dimensions[f.dimension], f'p{i}."{f.dimension}"', f, skel_params))
    skeleton = f"SELECT {', '.join(skel_cols)} FROM {skeleton_from}"
    if skel_where:
        skeleton += " WHERE " + " AND ".join(skel_where)

    net_where = [base["base_filter"]] if base["base_filter"] else []
    net_params: list = []
    for f in cat_filters:
        net_where.append(_predicate(catalog.dimensions[f.dimension], catalog.dimensions[f.dimension]["expression"], f, net_params))
        applied.append({"type": "filter", **_describe(f)})
    net_cols = [f'{month_dim["expression"]} AS "month"'] + [f'{d["expression"]} AS "{d["name"]}"' for d in pdefs]
    group = ", ".join(str(i + 1) for i in range(len(net_cols)))
    net = (f"SELECT {', '.join(net_cols)}, {base['expression']} AS net FROM "
           f"{_from_clause(catalog, base['grain'], join_names)} WHERE {' AND '.join(net_where)} GROUP BY {group}")

    on = " AND ".join(['n."month" = s."month"'] + [f'n."{d["name"]}" = s."{d["name"]}"' for d in pdefs])
    series_cols = ['s."month"'] + [f's."{d["name"]}"' for d in pdefs]
    series = (f"SELECT {', '.join(series_cols)}, COALESCE(n.net, 0) AS net FROM skeleton s "
              f"LEFT JOIN net n ON {on}")
    partition = f"PARTITION BY {', '.join(chr(34) + d['name'] + chr(34) for d in pdefs)} " if pdefs else ""
    out_cols = ['"month"'] + [f'"{d["name"]}"' for d in pdefs]
    growth = (f"SELECT {', '.join(out_cols)}, CAST(net AS DOUBLE) / NULLIF(LAG(net) OVER ({partition}ORDER BY \"month\"), 0) - 1 "
              f'AS "value" FROM series')

    outer_where: list[str] = []
    outer_params: list = []
    if q.date_from:
        outer_where.append('"month" >= ?')
        outer_params.append(q.date_from.strftime("%Y-%m"))
        applied.append({"type": "date_from", "value": q.date_from.isoformat(), "note": "restringe só os meses devolvidos"})
    if q.date_to:
        outer_where.append('"month" <= ?')
        outer_params.append(q.date_to.strftime("%Y-%m"))
        applied.append({"type": "date_to", "value": q.date_to.isoformat(), "note": "restringe só os meses devolvidos"})
    for f in month_filters:
        outer_where.append(_predicate(month_dim, '"month"', f, outer_params))
        applied.append({"type": "filter", **_describe(f)})

    # ordem dos parâmetros = ordem dos marcadores no texto: skeleton, net, outer, limit
    params = skel_params + net_params + outer_params
    q_dims = q.dimensions
    select_cols = ", ".join([f'"{c}"' for c in q_dims] + ['"value"'])
    sql = f"WITH skeleton AS ({skeleton}), net AS ({net}), series AS ({series}), growth AS ({growth}) SELECT {select_cols} FROM growth"
    if outer_where:
        sql += " WHERE " + " AND ".join(outer_where)
    sql += _order_by(q) + " LIMIT ?"
    params.append(q.limit + 1)
    return BuiltQuery(sql, params, q_dims + ["value"], applied)
