"""Laboratório de defeitos (schema dq_lab). NUNCA grava em oltp.

dq_lab = cópia válida de uma amostra de pedidos + defeitos determinísticos.
Cada defeito usa pedidos novos (ids >= 1_000_001), então as contagens por regra são exatas.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from . import orders as O
from . import refunds as R
from .config import GenConfig

BASE = 1_000_000
ORPHAN = 9_000_000

# defeitos por regra (contagem de linhas violadoras esperada)
N_NO_CUSTOMER = 7
N_NO_PRODUCT = 6
N_DUP_PAYMENT = 5
N_CANCELLED_CAPTURED = 4
N_REFUND_EXCEEDS = 3
N_NEG = {"order_items": 2, "payments": 2, "products": 1, "refunds": 1}
N_DATE = {"refund_before_order": 3, "order_in_future": 2, "payment_before_order": 2}

# métricas que divergem quando o item adulterado é removido do dq_lab.duckdb
DIVERGENT_METRICS = ["average_order_value", "gross_revenue", "net_revenue"]


class _Builder:
    def __init__(self, cfg: GenConfig, rng: np.random.Generator, customers: pd.DataFrame, products: pd.DataFrame):
        self.cfg, self.rng = cfg, rng
        self.cust_ids = customers["customer_id"].tolist()
        self.prod = products[["product_id", "unit_price"]].to_dict("records")
        self.orders, self.items, self.payments, self.refunds, self.extra_products = [], [], [], [], []
        self.n_order = self.n_item = self.n_pay = self.n_ref = 0
        self.all_days = cfg.days()

    def day(self):
        # meio do histórico: nem futuro nem perto do fim
        return self.all_days[int(self.rng.integers(60, len(self.all_days) - 60))]

    def order(self, *, status="paid", customer=None, items=1, odate=None, pay_status=None, pay_amount=None,
              paid_at="auto", line_override=None, product_override=None, method="pix", total_override=None):
        self.n_order += 1
        oid = BASE + self.n_order
        odate = odate or self.day()
        customer = customer if customer is not None else self.cust_ids[int(self.rng.integers(0, len(self.cust_ids)))]
        total = Decimal(0)
        item_ids = []
        for _ in range(items):
            p = self.prod[int(self.rng.integers(0, len(self.prod)))]
            q = int(self.rng.integers(1, 4))
            line = p["unit_price"] * q
            if line_override is not None:
                line = line_override
            self.n_item += 1
            iid = BASE + self.n_item
            item_ids.append(iid)
            pid = product_override if product_override is not None else p["product_id"]
            self.items.append((iid, oid, pid, q, p["unit_price"], line))
            total += line
        if total_override is not None:
            total = total_override
        self.orders.append((oid, customer, odate, status, total))
        pay_status = pay_status or {"paid": "captured", "refunded": "captured", "pending": "pending", "cancelled": "voided"}[status]
        if paid_at == "auto":
            paid_at = odate + timedelta(days=1) if pay_status == "captured" else None
        self.payment(oid, method, pay_status, total if pay_amount is None else pay_amount, paid_at)
        return oid, item_ids, total

    def payment(self, oid, method, status, amount, paid_at):
        self.n_pay += 1
        self.payments.append((BASE + self.n_pay, oid, method, status, amount, paid_at))

    def refund(self, item_id, amount, status, when):
        self.n_ref += 1
        self.refunds.append((BASE + self.n_ref, item_id, amount, status, when, "defeito controlado"))


def build_dq_lab(cfg: GenConfig, rng: np.random.Generator, frames: dict[str, pd.DataFrame]):
    """Retorna (frames do dq_lab, manifesto de contagens esperadas)."""
    cust, prod = frames["customers"], frames["products"]
    keep = frames["orders"].sort_values("order_id").head(cfg.dq_lab_orders)
    ids = set(keep["order_id"])
    items = frames["order_items"][frames["order_items"]["order_id"].isin(ids)]
    payments = frames["payments"][frames["payments"]["order_id"].isin(ids)]
    refunds = frames["refunds"][frames["refunds"]["order_item_id"].isin(set(items["order_item_id"]))]

    b = _Builder(cfg, rng, cust, prod)
    # 1. pedidos sem cliente
    for i in range(N_NO_CUSTOMER):
        b.order(customer=ORPHAN + i)
    # 2. itens sem produto
    for i in range(N_NO_PRODUCT):
        b.order(product_override=ORPHAN + i)
    # 3. pagamentos duplicados (segundo pagamento do mesmo pedido)
    for _ in range(N_DUP_PAYMENT):
        oid, _, total = b.order()
        b.payment(oid, "credit_card", "captured", total, b.orders[-1][2] + timedelta(days=1))
    # 4. cancelados com pagamento capturado
    for _ in range(N_CANCELLED_CAPTURED):
        b.order(status="cancelled", pay_status="captured")
    # 5. reembolso acima do valor pago
    for _ in range(N_REFUND_EXCEEDS):
        oid, iids, total = b.order(line_override=Decimal("100.00"))
        b.refund(iids[0], Decimal("150.00"), "completed", b.orders[-1][2] + timedelta(days=3))
    # 6. valores negativos
    for _ in range(N_NEG["order_items"]):
        b.order(line_override=Decimal("-50.00"), total_override=Decimal("50.00"))
    for _ in range(N_NEG["payments"]):
        b.order(status="pending", pay_amount=Decimal("-25.00"))
    pneg = (BASE + 1, "SKU-NEG-1", "Produto com preço negativo", 1, Decimal("-9.90"), True)
    b.extra_products.append(pneg)
    for _ in range(N_NEG["refunds"]):
        oid, iids, total = b.order(line_override=Decimal("80.00"))
        b.refund(iids[0], Decimal("-5.00"), "rejected", b.orders[-1][2] + timedelta(days=2))
    # 7. datas inconsistentes
    for _ in range(N_DATE["refund_before_order"]):
        oid, iids, total = b.order(line_override=Decimal("60.00"))
        b.refund(iids[0], Decimal("10.00"), "completed", b.orders[-1][2] - timedelta(days=5))
    for _ in range(N_DATE["order_in_future"]):
        b.order(status="pending", odate=cfg.end_date + timedelta(days=20))
    for _ in range(N_DATE["payment_before_order"]):
        odate = b.day()
        b.order(odate=odate, paid_at=odate - timedelta(days=3))

    out = {
        "categories": frames["categories"], "regions": frames["regions"], "customers": cust,
        "products": pd.concat([prod, pd.DataFrame(b.extra_products, columns=prod.columns, dtype=object)], ignore_index=True),
        "orders": pd.concat([keep, pd.DataFrame(b.orders, columns=O.ORDER_COLS, dtype=object)], ignore_index=True),
        "order_items": pd.concat([items, pd.DataFrame(b.items, columns=O.ITEM_COLS, dtype=object)], ignore_index=True),
        "payments": pd.concat([payments, pd.DataFrame(b.payments, columns=O.PAYMENT_COLS, dtype=object)], ignore_index=True),
        "refunds": pd.concat([refunds, pd.DataFrame(b.refunds, columns=R.COLUMNS, dtype=object)], ignore_index=True),
    }

    # item adulterado no dq_lab.duckdb: primeiro item de pedido pago da linha de base sem reembolso
    refunded = set(refunds["order_item_id"])
    paid_ids = set(keep.loc[keep["status"].isin(["paid", "refunded"]), "order_id"])
    cand = items[items["order_id"].isin(paid_ids) & ~items["order_item_id"].isin(refunded)].sort_values("order_item_id")
    manifest = {
        "rules": {
            "orders_without_customer": N_NO_CUSTOMER,
            "items_without_product": N_NO_PRODUCT,
            "duplicate_payments": N_DUP_PAYMENT,
            "cancelled_with_captured_payment": N_CANCELLED_CAPTURED,
            "refund_exceeds_paid": N_REFUND_EXCEEDS,
            "negative_values": sum(N_NEG.values()),
            "inconsistent_dates": sum(N_DATE.values()),
        },
        "divergence": {
            "tampered_order_item_id": int(cand.iloc[0]["order_item_id"]),
            "divergent_metrics": DIVERGENT_METRICS,
        },
    }
    return out, manifest
