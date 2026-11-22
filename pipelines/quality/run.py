"""Qualidade e reconciliação. Uso: python -m pipelines.quality.run

1. regras em oltp: esperado 0 violações
2. regras em dq_lab: esperado = tests/golden/dq_expected.json
3. reconciliação oltp x analytics.duckdb: esperado 8/8
4. divergência demonstrada: dq_lab x dq_lab.duckdb (adulterado) deve divergir nas métricas do manifesto
Saída 0 se todas as expectativas se cumprem.
"""
from __future__ import annotations

import json
import sys

import duckdb

from app.config import ROOT, Settings, get_settings
from app.db import make_engine
from app.logging_setup import configure_logging
from pipelines.extract.postgres_extract import extract_all
from pipelines.transform.build_duckdb import build

from . import reconcile, runner

MANIFEST = ROOT / "tests" / "golden" / "dq_expected.json"


def build_dq_lab_duckdb(settings: Settings, manifest: dict) -> None:
    """Constrói dq_lab.duckdb a partir de dq_lab e adultera 1 item (divergência controlada)."""
    dq = make_engine("dq", settings)
    try:
        frames = extract_all(dq, "dq_lab")
    finally:
        dq.dispose()
    path = settings.dq_lab_duckdb_file
    build(frames, path, 0, settings.data_end_date)
    con = duckdb.connect(str(path))
    try:
        con.execute("DELETE FROM fact_order_items WHERE order_item_id = ?", [manifest["divergence"]["tampered_order_item_id"]])
        con.execute("CHECKPOINT")
    finally:
        con.close()


def run(settings: Settings | None = None, manifest_path=MANIFEST, trigger: str = "cli") -> bool:
    settings = settings or get_settings()
    log = configure_logging("poc.quality", settings, "quality.log")
    manifest = json.loads(manifest_path.read_text())
    dq = make_engine("dq", settings)
    reader = make_engine("reader", settings)
    all_ok = True
    try:
        end = settings.data_end_date
        # 1. oltp
        rid = runner.start_run(dq, "oltp", trigger)
        ok = True
        for r in runner.run_rules(dq, "oltp", end):
            passed = r.violations == 0
            ok &= passed
            log.info("oltp  regra %-34s violações=%d %s", r.name, r.violations, "OK" if passed else "FALHA")
            runner.record_result(dq, rid, "rule", r.name, passed, violations=r.violations, expected="0", actual=str(r.violations), detail=r.sample)
        for rr in reconcile.reconcile_all(reader, settings.duckdb_file, "oltp", end):
            ok &= rr.ok
            log.info("oltp  reconciliação %-24s pg=%s duckdb=%s %s", rr.metric, rr.pg_summary, rr.duckdb_summary, "OK" if rr.ok else "DIVERGE")
            runner.record_result(dq, rid, "reconciliation", rr.metric, rr.ok, violations=rr.mismatches, expected=rr.pg_summary, actual=rr.duckdb_summary)
        runner.finish_run(dq, rid, ok, {"target": "oltp"})
        all_ok &= ok

        # 2. dq_lab: cada regra deve detectar exatamente o manifesto
        rid = runner.start_run(dq, "dq_lab", trigger)
        ok = True
        for r in runner.run_rules(dq, "dq_lab", end):
            exp = manifest["rules"][r.name]
            passed = r.violations == exp
            ok &= passed
            log.info("dq_lab regra %-34s violações=%d esperado=%d %s", r.name, r.violations, exp, "DETECTADO" if passed else "FALHA")
            runner.record_result(dq, rid, "rule", r.name, passed, violations=r.violations, expected=str(exp), actual=str(r.violations), detail=r.sample)

        # 3. divergência controlada
        build_dq_lab_duckdb(settings, manifest)
        expected_div = set(manifest["divergence"]["divergent_metrics"])
        got = set()
        for rr in reconcile.reconcile_all(dq, settings.dq_lab_duckdb_file, "dq_lab", end):
            if not rr.ok:
                got.add(rr.metric)
            log.info("dq_lab reconciliação %-24s %s", rr.metric, "DIVERGE" if not rr.ok else "igual")
        passed = got == expected_div
        ok &= passed
        log.info("dq_lab divergência detectada=%s esperado=%s %s", sorted(got), sorted(expected_div), "OK" if passed else "FALHA")
        runner.record_result(dq, rid, "reconciliation", "dq_lab_divergence", passed, expected=",".join(sorted(expected_div)), actual=",".join(sorted(got)))
        runner.finish_run(dq, rid, ok, {"target": "dq_lab", "divergent": sorted(got)})
        all_ok &= ok
    finally:
        dq.dispose()
        reader.dispose()
    log.info("qualidade: %s", "TUDO OK" if all_ok else "FALHOU")
    return all_ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
