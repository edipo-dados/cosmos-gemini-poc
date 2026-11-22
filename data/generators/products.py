from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd

from .config import GenConfig
from .reference import ADJECTIVES, CATEGORIES

COLUMNS = ["product_id", "sku", "name", "category_id", "unit_price", "is_active"]


def build_products(cfg: GenConfig, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    per_cat = cfg.n_products // cfg.n_categories
    pid = 0
    for ci, (cat, nouns, (lo, hi)) in enumerate(CATEGORIES):
        for k in range(per_cat):
            pid += 1
            noun = nouns[k % len(nouns)]
            adj = ADJECTIVES[int(rng.integers(0, len(ADJECTIVES)))]
            # preços log-uniformes dentro da faixa da categoria, terminados em ,90 ou ,00
            cents = int(np.exp(rng.uniform(np.log(lo), np.log(hi)))) * 100 + (90 if rng.random() < 0.6 else 0)
            rows.append((pid, f"SKU-{pid:05d}", f"{noun} {adj} {k + 1}", ci + 1, Decimal(cents) / 100, bool(rng.random() > 0.03)))
    return pd.DataFrame(rows, columns=COLUMNS, dtype=object)
