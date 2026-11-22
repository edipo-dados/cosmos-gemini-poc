"""Constrói o arquivo DuckDB analítico a partir dos DataFrames extraídos.

Escreve em `<arquivo>.tmp` e troca por os.replace (atômico). Reexecutar recria o arquivo do zero.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

from .schema import DDL, TABLES

log = logging.getLogger("poc.etl")

MONTHS_PT = "['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']"
WEEKDAYS_PT = "['Segunda','Terça','Quarta','Quinta','Sexta','Sábado','Domingo']"

# Pagamentos duplicados só existem no dq_lab; para não duplicar pedidos, agrega-se por pedido.
TRANSFORMS = [
    ("dim_region", "INSERT INTO dim_region SELECT region_id, name, states FROM raw_regions"),
    ("dim_customer", """INSERT INTO dim_customer
        SELECT c.customer_id, c.name, c.email, c.segment, c.region_id, r.name, c.city, c.state, CAST(c.created_at AS DATE)
        FROM raw_customers c LEFT JOIN raw_regions r ON r.region_id = c.region_id"""),
    ("dim_product", """INSERT INTO dim_product
        SELECT p.product_id, p.sku, p.name, p.category_id, c.name, CAST(p.unit_price AS DECIMAL(12,2)), p.is_active
        FROM raw_products p LEFT JOIN raw_categories c ON c.category_id = p.category_id"""),
    ("fact_orders", """INSERT INTO fact_orders
        WITH pay AS (SELECT order_id, MIN(method) AS method, MIN(status) AS status FROM raw_payments GROUP BY order_id)
        SELECT o.order_id, o.customer_id, c.region_id, CAST(o.order_date AS DATE), o.status,
               o.status IN ('paid', 'refunded'), CAST(o.total_amount AS DECIMAL(12,2)), pay.method, pay.status
        FROM raw_orders o
        LEFT JOIN raw_customers c ON c.customer_id = o.customer_id
        LEFT JOIN pay ON pay.order_id = o.order_id"""),
    ("fact_order_items", """INSERT INTO fact_order_items
        SELECT i.order_item_id, i.order_id, i.product_id, p.category_id, CAST(o.order_date AS DATE), i.quantity,
               CAST(i.unit_price AS DECIMAL(12,2)), CAST(i.line_total AS DECIMAL(12,2))
        FROM raw_order_items i
        LEFT JOIN raw_orders o ON o.order_id = i.order_id
        LEFT JOIN raw_products p ON p.product_id = i.product_id"""),
    ("fact_payments", """INSERT INTO fact_payments
        SELECT payment_id, order_id, method, status, CAST(amount AS DECIMAL(12,2)), CAST(paid_at AS DATE)
        FROM raw_payments"""),
    ("fact_refunds", """INSERT INTO fact_refunds
        SELECT r.refund_id, r.order_item_id, i.order_id, i.product_id, CAST(o.order_date AS DATE),
               CAST(r.refund_amount AS DECIMAL(12,2)), r.status, CAST(r.refunded_at AS DATE), r.reason
        FROM raw_refunds r
        LEFT JOIN raw_order_items i ON i.order_item_id = r.order_item_id
        LEFT JOIN raw_orders o ON o.order_id = i.order_id"""),
]


def _dim_date_sql(end_date: date) -> str:
    return f"""INSERT INTO dim_date
        WITH bounds AS (
            SELECT LEAST(MIN(CAST(order_date AS DATE)), DATE '{end_date.isoformat()}') AS lo,
                   GREATEST(MAX(CAST(order_date AS DATE)), DATE '{end_date.isoformat()}') AS hi FROM raw_orders),
        days AS (SELECT CAST(UNNEST(generate_series(lo, hi, INTERVAL 1 DAY)) AS DATE) AS d FROM bounds)
        SELECT d, year(d), quarter(d), month(d), strftime(d, '%Y-%m'), CAST(date_trunc('month', d) AS DATE),
               list_extract({MONTHS_PT}, month(d)), day(d), isodow(d), list_extract({WEEKDAYS_PT}, isodow(d)),
               isodow(d) >= 6
        FROM days"""


def build(frames: dict[str, pd.DataFrame], out_path: Path, etl_run_id: int, end_date: date) -> dict[str, int]:
    """Gera o arquivo DuckDB e devolve as contagens por tabela de destino."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    for stale in (tmp, tmp.with_name(tmp.name + ".wal")):
        stale.unlink(missing_ok=True)
    source_counts = {t: int(len(df)) for t, df in frames.items()}
    con = duckdb.connect(str(tmp))
    try:
        for t, df in frames.items():
            con.register(f"df_{t}", df)
            con.execute(f"CREATE TEMP TABLE raw_{t} AS SELECT * FROM df_{t}")
            con.unregister(f"df_{t}")
        for stmt in DDL:
            con.execute(stmt)
        for name, sql in TRANSFORMS:
            con.execute(sql)
        con.execute(_dim_date_sql(end_date))
        con.execute("INSERT INTO etl_meta VALUES (?, ?, ?)",
                    [etl_run_id, datetime.now().replace(microsecond=0), json.dumps(source_counts)])
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
        con.execute("CHECKPOINT")
    finally:
        con.close()
    for t, n in counts.items():
        log.info("  %-17s %8d linhas", t, n)
    tmp.with_name(tmp.name + ".wal").unlink(missing_ok=True)
    out_path.with_name(out_path.name + ".wal").unlink(missing_ok=True)
    os.replace(tmp, out_path)
    return counts
