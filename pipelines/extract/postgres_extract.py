"""Extração do PostgreSQL. Lista FIXA de tabelas; o schema só pode ser oltp ou dq_lab.

O ETL oficial usa sempre 'oltp' com o papel poc_reader (sem acesso a dq_lab).
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine, text

# tabela -> (chave de ordenação, colunas numeric, colunas date). Valores monetários e datas
# saem como texto e são convertidos no DuckDB (sem perda de precisão).
TABLES: dict[str, dict] = {
    "categories": {"order": "category_id", "money": [], "dates": []},
    "regions": {"order": "region_id", "money": [], "dates": []},
    "customers": {"order": "customer_id", "money": [], "dates": ["created_at"]},
    "products": {"order": "product_id", "money": ["unit_price"], "dates": []},
    "orders": {"order": "order_id", "money": ["total_amount"], "dates": ["order_date"]},
    "order_items": {"order": "order_item_id", "money": ["unit_price", "line_total"], "dates": []},
    "payments": {"order": "payment_id", "money": ["amount"], "dates": ["paid_at"]},
    "refunds": {"order": "refund_id", "money": ["refund_amount"], "dates": ["refunded_at"]},
}
ALLOWED_SCHEMAS = ("oltp", "dq_lab")

COLUMNS: dict[str, list[str]] = {
    "categories": ["category_id", "name"],
    "regions": ["region_id", "name", "states"],
    "customers": ["customer_id", "name", "email", "segment", "region_id", "city", "state", "created_at"],
    "products": ["product_id", "sku", "name", "category_id", "unit_price", "is_active"],
    "orders": ["order_id", "customer_id", "order_date", "status", "total_amount"],
    "order_items": ["order_item_id", "order_id", "product_id", "quantity", "unit_price", "line_total"],
    "payments": ["payment_id", "order_id", "method", "status", "amount", "paid_at"],
    "refunds": ["refund_id", "order_item_id", "refund_amount", "status", "refunded_at", "reason"],
}


def extract_queries(schema: str) -> dict[str, str]:
    if schema not in ALLOWED_SCHEMAS:
        raise ValueError(f"schema não permitido: {schema}")
    out = {}
    for table, meta in TABLES.items():
        cols = []
        for c in COLUMNS[table]:
            cols.append(f"{c}::text AS {c}" if c in meta["money"] + meta["dates"] else c)
        out[table] = f"SELECT {', '.join(cols)} FROM {schema}.{table} ORDER BY {meta['order']}"
    return out


def extract_all(engine: Engine, schema: str = "oltp") -> dict[str, pd.DataFrame]:
    frames = {}
    with engine.connect() as conn:
        for table, sql in extract_queries(schema).items():
            frames[table] = pd.read_sql(text(sql), conn)
    return frames
