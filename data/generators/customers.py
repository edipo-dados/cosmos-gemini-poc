from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

import numpy as np
import pandas as pd
from faker import Faker

from .config import GenConfig
from .reference import REGIONS, SEGMENT_WEIGHTS, SEGMENTS

COLUMNS = ["customer_id", "name", "email", "segment", "region_id", "city", "state", "created_at"]


def _slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", ".", ascii_.lower()).strip(".")


def build_customers(cfg: GenConfig, fake: Faker, rng: np.random.Generator) -> pd.DataFrame:
    n = cfg.n_customers
    region_idx = rng.choice(len(REGIONS), size=n, p=[r[2] for r in REGIONS])
    segments = rng.choice(len(SEGMENTS), size=n, p=SEGMENT_WEIGHTS)
    created_offsets = rng.integers(0, 3 * 365, size=n)
    rows = []
    for i in range(n):
        cid = i + 1
        name = fake.company() if SEGMENTS[segments[i]] in ("Corporativo", "Pequena Empresa") else fake.name()
        states = REGIONS[region_idx[i]][1].split(",")
        state = states[int(rng.integers(0, len(states)))]
        # e-mails em example.com (domínio reservado): nenhum dado pessoal real
        email = f"{_slug(name)[:40]}.{cid}@example.com"
        created = cfg.start_date - timedelta(days=int(created_offsets[i]) + 1)
        rows.append((cid, name, email, SEGMENTS[segments[i]], int(region_idx[i]) + 1, fake.city(), state, created))
    return pd.DataFrame(rows, columns=COLUMNS, dtype=object)
