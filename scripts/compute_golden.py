"""Calcula os valores esperados das métricas com SQL independente no PostgreSQL (oltp, papel poc_reader).

Independência: não usa o Query Engine, o DuckDB nem o YAML de métricas. Parte das tabelas `oltp.*` e recompõe cada métrica
a partir de uma visão por item de pedido (CTE `line`). Crescimento mensal é calculado em Python sobre a série líquida do PostgreSQL.
Grava tests/golden/expected.json. Uso: python scripts/compute_golden.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import make_engine  # noqa: E402

OUT = ROOT / "tests" / "golden" / "expected.json"

LINE_CTE = """
WITH line AS (
  SELECT o.order_id, o.customer_id, o.status AS order_status, o.order_date AS "date",
         to_char(o.order_date, 'YYYY-MM') AS "month", extract(year FROM o.order_date)::int AS "year",
         r.name AS region, c.segment, cat.name AS category, p.name AS product, pay.method AS payment_method,
         i.line_total,
         COALESCE((SELECT sum(rf.refund_amount) FROM oltp.refunds rf
                   WHERE rf.order_item_id = i.order_item_id AND rf.status = 'completed'), 0) AS refunded,
         EXISTS (SELECT 1 FROM oltp.refunds rf
                 WHERE rf.order_item_id = i.order_item_id AND rf.status = 'completed') AS has_refund
  FROM oltp.orders o
  JOIN oltp.order_items i ON i.order_id = o.order_id
  JOIN oltp.customers c ON c.customer_id = o.customer_id
  JOIN oltp.regions r ON r.region_id = c.region_id
  JOIN oltp.products p ON p.product_id = i.product_id
  JOIN oltp.categories cat ON cat.category_id = p.category_id
  JOIN oltp.payments pay ON pay.order_id = o.order_id
)
"""
PAID = "order_status IN ('paid', 'refunded')"
AGG = {
    "gross_revenue": ("sum(line_total)", PAID),
    "net_revenue": ("sum(line_total) - sum(refunded)", PAID),
    "order_count": ("count(DISTINCT order_id)", "true"),
    "average_order_value": ("(sum(line_total) - sum(refunded))::float8 / nullif(count(DISTINCT order_id), 0)", PAID),
    "active_customers": ("count(DISTINCT customer_id)", PAID),
    "cancellation_rate": ("count(DISTINCT order_id) FILTER (WHERE order_status = 'cancelled')::float8 "
                          "/ nullif(count(DISTINCT order_id), 0)", "true"),
    "refund_amount": ("sum(refunded)", "has_refund"),
}


def _where(filters: list[dict], date_from, date_to, extra: str, params: dict) -> str:
    parts = [extra]
    for n, f in enumerate(filters):
        col = {"order_status": "order_status"}.get(f["dimension"], f["dimension"])
        values = f["value"] if f["op"] == "in" else [f["value"]]
        keys = []
        for k, v in enumerate(values):
            params[f"f{n}_{k}"] = v
            keys.append(f":f{n}_{k}")
        parts.append(f'"{col}" IN ({", ".join(keys)})')
    if date_from:
        params["df"] = date_from
        parts.append('"date" >= CAST(:df AS date)')
    if date_to:
        params["dt"] = date_to
        parts.append('"date" <= CAST(:dt AS date)')
    return " AND ".join(parts)


def _query(conn, metric: str, dims: list[str], filters: list[dict], date_from, date_to, as_of: date) -> list[dict]:
    agg, base = AGG[metric]
    params: dict = {}
    extra = base
    if metric == "active_customers":
        params["as_start"] = (as_of - timedelta(days=89)).isoformat()
        params["as_end"] = as_of.isoformat()
        extra = f'{base} AND "date" BETWEEN CAST(:as_start AS date) AND CAST(:as_end AS date)'
        date_from = date_to = None
    where = _where(filters, date_from, date_to, extra, params)
    cols = ", ".join(f'"{d}"' for d in dims)
    sql = LINE_CTE + f"SELECT {cols + ', ' if dims else ''}({agg})::text AS value FROM line WHERE {where}"
    if dims:
        sql += f" GROUP BY {cols}"
    return [{**{d: (str(r._mapping[d]) if d in ("date",) else r._mapping[d]) for d in dims}, "value": r._mapping["value"]}
            for r in conn.execute(text(sql), params)]


def _growth(conn, dims: list[str], filters: list[dict], date_from, date_to) -> list[dict]:
    part = [d for d in dims if d != "month"]
    net = _query(conn, "net_revenue", ["month", *part], filters, None, None, date.today())
    months = [r[0] for r in conn.execute(text("SELECT DISTINCT to_char(d, 'YYYY-MM') FROM generate_series("
                                               "(SELECT date_trunc('month', min(order_date)) FROM oltp.orders), "
                                               "(SELECT max(order_date) FROM oltp.orders), interval '1 day') d ORDER BY 1"))]
    values = {tuple(r[d] for d in ["month", *part]): Decimal(r["value"]) for r in net}
    pools = {d: sorted({r[d] for r in net}) for d in part}
    if part:  # partições: todas as combinações existentes no domínio completo
        dom = {d: [r[0] for r in conn.execute(text(
            {"region": "SELECT name FROM oltp.regions", "segment": "SELECT DISTINCT segment FROM oltp.customers"}[d]))] for d in part}
        for d in part:
            for f in filters:
                if f["dimension"] == d:
                    allowed = f["value"] if f["op"] == "in" else [f["value"]]
                    dom[d] = [v for v in dom[d] if v in allowed]
        pools = dom
    combos = [()]
    for d in part:
        combos = [c + (v,) for c in combos for v in pools[d]]
    out = []
    for combo in combos:
        prev = None
        for m in months:
            cur = values.get((m, *combo), Decimal(0))
            val = None if prev in (None, Decimal(0)) else float(cur) / float(prev) - 1
            prev = cur
            if (date_from and m < date_from[:7]) or (date_to and m > date_to[:7]):
                continue
            out.append({"month": m, **dict(zip(part, combo)), "value": None if val is None else repr(val)})
    return out


def _case(conn, cid: str, metric: str, dims: list[str], filters=None, date_from=None, date_to=None, as_of=None, end=None) -> dict:
    filters = filters or []
    if metric == "monthly_revenue_growth":
        rows = _growth(conn, dims, filters, date_from, date_to)
    else:
        rows = _query(conn, metric, dims, filters, date_from, date_to, date.fromisoformat(as_of) if as_of else end)
    req = {"metric": metric, "dimensions": dims, "filters": filters, "limit": 1000}
    if date_from:
        req["date_from"] = date_from
    if date_to:
        req["date_to"] = date_to
    return {"id": cid, "request": req, "rows": rows}


def main() -> int:
    settings = get_settings()
    end = settings.data_end_date
    pg = make_engine("reader", settings)
    cases: list[dict] = []
    all_metrics = list(AGG) + ["monthly_revenue_growth"]
    slices = {
        "total": [], "region": ["region"], "segment": ["segment"], "month": ["month"],
        "category": ["category"], "payment_method": ["payment_method"], "order_status": ["order_status"], "year": ["year"],
    }
    allowed = {
        "active_customers": {"total", "region", "segment"},
        "cancellation_rate": {"total", "region", "segment", "month", "payment_method", "year"},
        "monthly_revenue_growth": {"month"},
    }
    with pg.connect() as conn:
        for metric in all_metrics:
            for name, dims in slices.items():
                if name in allowed.get(metric, set(slices)):
                    cases.append(_case(conn, f"{metric}.by_{name}", metric, dims, end=end))
        cases.append(_case(conn, "gross_revenue.by_product", "gross_revenue", ["product"], end=end))
        cases.append(_case(conn, "monthly_revenue_growth.by_region_month", "monthly_revenue_growth", ["month", "region"], end=end))
        cases.append(_case(conn, "monthly_revenue_growth.by_segment_month", "monthly_revenue_growth", ["month", "segment"], end=end))
        cases.append(_case(conn, "gross_revenue.oct2026_by_region", "gross_revenue", ["region"],
                           date_from="2026-10-01", date_to="2026-10-31", end=end))
        cases.append(_case(conn, "net_revenue.games_by_month_2026", "net_revenue", ["month"],
                           [{"dimension": "category", "op": "eq", "value": "Games"}], date_from="2026-01-01", end=end))
        cases.append(_case(conn, "active_customers.asof_2026_06_30_by_segment", "active_customers", ["segment"],
                           date_to="2026-06-30", as_of="2026-06-30", end=end))
        cases.append(_case(conn, "order_count.pix_boleto_by_status", "order_count", ["order_status"],
                           [{"dimension": "payment_method", "op": "in", "value": ["pix", "boleto"]}], end=end))
        cases.append(_case(conn, "refund_amount.premium_by_category", "refund_amount", ["category"],
                           [{"dimension": "segment", "op": "eq", "value": "Premium"}], end=end))
        cases.append(_case(conn, "cancellation_rate.sul_by_month", "cancellation_rate", ["month"],
                           [{"dimension": "region", "op": "eq", "value": "Sul"}], end=end))
        cases.append(_case(conn, "monthly_revenue_growth.sudeste_window", "monthly_revenue_growth", ["month"],
                           [{"dimension": "region", "op": "eq", "value": "Sudeste"}], date_from="2026-09-01", date_to="2026-10-31", end=end))
        cases.append(_case(conn, "average_order_value.pix_by_category", "average_order_value", ["category"],
                           [{"dimension": "payment_method", "op": "eq", "value": "pix"}], end=end))
        # perguntas exemplo da Fase 4 (tests/golden/questions.json): janelas relativas a DATA_END_DATE
        cases.append(_case(conn, "net_revenue.last_30_days", "net_revenue", [],
                           date_from=(end - timedelta(days=29)).isoformat(), date_to=end.isoformat(), end=end))
        cases.append(_case(conn, "net_revenue.last_two_months_by_month", "net_revenue", ["month"],
                           date_from=(end.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat(),
                           date_to=end.isoformat(), end=end))
        totals = {r[0]: r[1] for r in conn.execute(text("SELECT 'orders', count(*) FROM oltp.orders"))}
    pg.dispose()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "PostgreSQL oltp via poc_reader, SQL independente (scripts/compute_golden.py)",
                               "seed": settings.seed, "data_end_date": end.isoformat(), "orders_total": totals["orders"],
                               "cases": cases}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(cases)} casos gravados em {OUT.relative_to(ROOT)}")
    for metric in all_metrics:
        print(f"  {metric:24s} {sum(c['request']['metric'] == metric for c in cases)} casos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
