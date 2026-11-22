"""Gera dados sintéticos determinísticos e carrega no PostgreSQL de forma idempotente.

Uso: python -m data.generators.run --seed 42 [--reset]
Saída 0 = ok, 2 = seed/parâmetros diferentes dos já carregados sem --reset.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker
from sqlalchemy import Engine, text

from app.config import ROOT, Settings, get_settings
from app.db import make_engine
from app.logging_setup import configure_logging

from . import customers as C
from . import defects, orders as O, products as P, refunds as R
from .config import GenConfig
from .reference import categories_df, regions_df

TABLE_ORDER = ["categories", "regions", "customers", "products", "orders", "order_items", "payments", "refunds"]
MANIFEST_PATH = ROOT / "tests" / "golden" / "dq_expected.json"
BATCH = 5000


def generate(cfg: GenConfig) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict]:
    """Retorna (frames oltp, frames dq_lab, manifesto). Puro: mesmo cfg => mesmos DataFrames."""
    Faker.seed(cfg.seed)
    fake = Faker("pt_BR")
    rng = np.random.default_rng(cfg.seed)
    cats, regs = categories_df(cfg.n_categories), regions_df()
    customers = C.build_customers(cfg, fake, rng)
    products = P.build_products(cfg, rng)
    orders, items, payments = O.build_orders(cfg, rng, customers, products)
    refunds = R.build_refunds(cfg, rng, orders, items)
    oltp = {"categories": cats, "regions": regs, "customers": customers, "products": products,
            "orders": orders, "order_items": items, "payments": payments, "refunds": refunds}
    lab, manifest = defects.build_dq_lab(cfg, np.random.default_rng(cfg.seed + 1), oltp)
    return oltp, lab, manifest


def _rows(df: pd.DataFrame) -> list[dict]:
    clean = df.astype(object).where(df.notna(), None)
    return clean.to_dict("records")


def count_rows(engine: Engine, schema: str) -> dict[str, int]:
    with engine.connect() as c:
        return {t: c.execute(text(f"SELECT count(*) FROM {schema}.{t}")).scalar_one() for t in TABLE_ORDER}


def load_schema(engine: Engine, schema: str, frames: dict[str, pd.DataFrame]) -> None:
    with engine.begin() as c:
        for t in TABLE_ORDER:
            df = frames[t]
            cols = list(df.columns)
            stmt = text(
                f"INSERT INTO {schema}.{t} ({', '.join(cols)}) VALUES ({', '.join(':' + k for k in cols)}) "
                "ON CONFLICT DO NOTHING"
            )
            rows = _rows(df)
            for i in range(0, len(rows), BATCH):
                c.execute(stmt, rows[i:i + BATCH])


def reset(engine: Engine) -> None:
    with engine.begin() as c:
        tables = ", ".join(f"{s}.{t}" for s in ("oltp", "dq_lab") for t in TABLE_ORDER)
        c.execute(text(f"TRUNCATE {tables}"))
        c.execute(text("DELETE FROM ops.generator_state"))


def write_manifest(manifest: dict, path: Path = MANIFEST_PATH) -> None:
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != payload:
        path.write_text(payload)


def run(seed: int | None = None, do_reset: bool = False, settings: Settings | None = None,
        manifest_path: Path | None = MANIFEST_PATH) -> int:
    settings = settings or get_settings()
    log = configure_logging("poc.generator", settings, "generator.log")
    cfg = GenConfig(seed=settings.seed if seed is None else seed, end_date=settings.data_end_date)
    engine = make_engine("loader", settings)
    h = cfg.params_hash()
    try:
        with engine.begin() as c:
            state = c.execute(text("SELECT seed, params_hash FROM ops.generator_state WHERE id = 1")).first()
        if state and state.params_hash != h and not do_reset:
            log.error("dados já carregados com seed=%s hash=%s; pedido seed=%s hash=%s. Use --reset para recarregar.",
                      state.seed, state.params_hash, cfg.seed, h)
            return 2
        if do_reset:
            log.info("--reset: truncando oltp e dq_lab")
            reset(engine)
        log.info("gerando dados seed=%s fim=%s (hash %s)", cfg.seed, cfg.end_date, h)
        oltp, lab, manifest = generate(cfg)
        before = count_rows(engine, "oltp")
        load_schema(engine, "oltp", oltp)
        load_schema(engine, "dq_lab", lab)
        after = count_rows(engine, "oltp")
        lab_counts = count_rows(engine, "dq_lab")
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO ops.generator_state (id, seed, params_hash) VALUES (1, :s, :h) "
                "ON CONFLICT (id) DO UPDATE SET seed = :s, params_hash = :h, loaded_at = now()"), {"s": cfg.seed, "h": h})
        if manifest_path:
            write_manifest(manifest, manifest_path)
        log.info("oltp (linhas por tabela): %s", after)
        log.info("dq_lab (linhas por tabela): %s", lab_counts)
        log.info("linhas novas inseridas em oltp: %s", sum(after.values()) - sum(before.values()))
        return 0
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=None, help="padrão: SEED do ambiente (42)")
    ap.add_argument("--reset", action="store_true", help="apaga oltp/dq_lab e recarrega")
    a = ap.parse_args(argv)
    return run(a.seed, a.reset)


if __name__ == "__main__":
    sys.exit(main())
