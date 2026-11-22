"""Pedidos, itens e pagamentos (sempre consistentes: o dataset oficial não tem defeitos)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from .config import GenConfig
from .reference import METHODS, METHOD_WEIGHTS, SEGMENTS

ORDER_COLS = ["order_id", "customer_id", "order_date", "status", "total_amount"]
ITEM_COLS = ["order_item_id", "order_id", "product_id", "quantity", "unit_price", "line_total"]
PAYMENT_COLS = ["payment_id", "order_id", "method", "status", "amount", "paid_at"]

# Sazonalidade por mês do calendário (Dia das Mães, Black Friday, Natal)
SEASON = {1: 0.85, 2: 0.8, 3: 0.95, 4: 0.95, 5: 1.15, 6: 1.0, 7: 0.95, 8: 1.0, 9: 1.0, 10: 1.05, 11: 1.45, 12: 1.4}
WEEKDAY = [1.0, 1.0, 1.0, 1.05, 1.1, 0.9, 0.85]
# expoente de preço por segmento: Premium escolhe produtos caros, Varejo os baratos
PRICE_ALPHA = {"Varejo": -0.15, "Premium": 0.7, "Corporativo": 0.3, "Pequena Empresa": 0.0}
QTY_P = {
    "Varejo": [0.70, 0.20, 0.07, 0.02, 0.01],
    "Premium": [0.75, 0.17, 0.05, 0.02, 0.01],
    "Corporativo": [0.25, 0.25, 0.20, 0.15, 0.15],
    "Pequena Empresa": [0.45, 0.25, 0.15, 0.10, 0.05],
}
ITEMS_P = [0.30, 0.30, 0.20, 0.12, 0.08]


def _day_weights(cfg: GenConfig) -> tuple[list[date], np.ndarray]:
    days = cfg.days()
    n = len(days)
    w = np.array([
        (1.0 + 0.6 * i / n) * SEASON[d.month] * WEEKDAY[d.weekday()] for i, d in enumerate(days)
    ])
    return days, w / w.sum()


def build_orders(cfg: GenConfig, rng: np.random.Generator, customers: pd.DataFrame, products: pd.DataFrame):
    days, day_p = _day_weights(cfg)
    day_idx = np.sort(rng.choice(len(days), size=cfg.n_orders, p=day_p))

    seg_of = customers["segment"].tolist()
    cust_ids = customers["customer_id"].to_numpy(dtype=int)
    # frequência de compra distinta: gamma por cliente, Premium/Corporativo compram mais
    freq = rng.gamma(0.7, 1.0, size=len(cust_ids))
    freq *= np.array([{"Premium": 1.6, "Corporativo": 1.3}.get(s, 1.0) for s in seg_of])
    cust_p = freq / freq.sum()
    order_customers = rng.choice(cust_ids, size=cfg.n_orders, p=cust_p)

    prod_ids = products["product_id"].to_numpy(dtype=int)
    prod_cents = np.array([int(Decimal(p) * 100) for p in products["unit_price"]], dtype=np.int64)
    seg_prod_p = {}
    for seg, alpha in PRICE_ALPHA.items():
        w = prod_cents.astype(float) ** alpha
        seg_prod_p[seg] = w / w.sum()
    seg_by_cust = dict(zip(cust_ids.tolist(), seg_of))

    n_items_all = rng.choice([1, 2, 3, 4, 5], size=cfg.n_orders, p=ITEMS_P)
    status_u = rng.random(cfg.n_orders)
    method_all = rng.choice(len(METHODS), size=cfg.n_orders, p=METHOD_WEIGHTS)
    pay_lag = rng.integers(0, 3, size=cfg.n_orders)

    orders, items, payments = [], [], []
    item_id = 0
    for k in range(cfg.n_orders):
        oid = k + 1
        cid = int(order_customers[k])
        seg = seg_by_cust[cid]
        odate = days[day_idx[k]]
        n_items = int(n_items_all[k])
        picks = rng.choice(len(prod_ids), size=n_items, replace=False, p=seg_prod_p[seg])
        qtys = rng.choice([1, 2, 3, 4, 5], size=n_items, p=QTY_P[seg])
        total_cents = 0
        for pi, q in zip(picks, qtys):
            item_id += 1
            cents = int(prod_cents[pi])
            line = cents * int(q)
            total_cents += line
            items.append((item_id, oid, int(prod_ids[pi]), int(q), Decimal(cents) / 100, Decimal(line) / 100))

        age = (cfg.end_date - odate).days
        pending_p = 0.40 if age <= 20 else 0.04
        u = status_u[k]
        if u < pending_p:
            status = "pending"
        elif u < pending_p + 0.12:
            status = "cancelled"
        elif u < pending_p + 0.12 + 0.09:
            status = "refunded"
        else:
            status = "paid"
        orders.append((oid, cid, odate, status, Decimal(total_cents) / 100))

        pstatus = {"paid": "captured", "refunded": "captured", "pending": "pending", "cancelled": "voided"}[status]
        paid_at = min(odate + timedelta(days=int(pay_lag[k])), cfg.end_date) if pstatus == "captured" else None
        payments.append((oid, oid, METHODS[int(method_all[k])], pstatus, Decimal(total_cents) / 100, paid_at))

    return (
        pd.DataFrame(orders, columns=ORDER_COLS, dtype=object),
        pd.DataFrame(items, columns=ITEM_COLS, dtype=object),
        pd.DataFrame(payments, columns=PAYMENT_COLS, dtype=object),
    )
