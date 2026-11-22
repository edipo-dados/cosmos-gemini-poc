"""Reembolsos por item. `refunded` = todos os itens reembolsados integralmente (completed)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from .config import GenConfig

COLUMNS = ["refund_id", "order_item_id", "refund_amount", "status", "refunded_at", "reason"]
REASONS = ["Produto com defeito", "Arrependimento", "Produto diferente do anunciado", "Atraso na entrega", "Cobrança em duplicidade"]


def build_refunds(cfg: GenConfig, rng: np.random.Generator, orders: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    items_by_order = {oid: g for oid, g in items.groupby("order_id", sort=False)}
    rows = []
    rid = 0

    def add(item, amount_cents: int, status: str, odate):
        nonlocal rid
        rid += 1
        when = min(odate + timedelta(days=int(rng.integers(2, 31))), cfg.end_date)
        rows.append((rid, int(item["order_item_id"]), Decimal(amount_cents) / 100, status, when,
                     REASONS[int(rng.integers(0, len(REASONS)))]))

    for order in orders.itertuples(index=False):
        if order.status not in ("paid", "refunded"):
            continue
        g = items_by_order[order.order_id]
        recs = list(g.to_dict("records"))
        if order.status == "refunded":
            for it in recs:
                add(it, int(it["line_total"] * 100), "completed", order.order_date)
            continue
        u = rng.random()
        if u < 0.12:
            it = recs[int(rng.integers(0, len(recs)))]
            line = int(it["line_total"] * 100)
            if len(recs) > 1 and rng.random() < 0.4:
                add(it, line, "completed", order.order_date)  # um item inteiro; os demais ficam
            else:
                add(it, max(1, int(line * rng.uniform(0.1, 0.9))), "completed", order.order_date)
        elif u < 0.16:
            it = recs[int(rng.integers(0, len(recs)))]
            add(it, int(it["line_total"] * 100), "pending", order.order_date)
        elif u < 0.19:
            it = recs[int(rng.integers(0, len(recs)))]
            add(it, int(it["line_total"] * 100), "rejected", order.order_date)
    return pd.DataFrame(rows, columns=COLUMNS, dtype=object)
