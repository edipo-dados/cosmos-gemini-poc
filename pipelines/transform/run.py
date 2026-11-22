"""ETL PostgreSQL (oltp) -> DuckDB analítico. Uso: python -m pipelines.transform.run

Fluxo: registra ops.etl_run -> extrai (poc_reader) -> verifica qualidade em oltp (aborta se houver
violação) -> constrói arquivo temporário -> troca atômica. Em falha o arquivo anterior fica intacto.
"""
from __future__ import annotations

import json
import sys
import time

from sqlalchemy import text

from app.config import Settings, get_settings
from app.db import make_engine
from app.logging_setup import configure_logging
from pipelines.extract.postgres_extract import extract_all
from pipelines.quality import runner

from .build_duckdb import build


class QualityGateError(RuntimeError):
    pass


def quality_gate(dq_engine, settings: Settings, etl_run_id: int) -> None:
    rid = runner.start_run(dq_engine, "oltp", "etl", etl_run_id)
    results = runner.run_rules(dq_engine, "oltp", settings.data_end_date)
    for r in results:
        runner.record_result(dq_engine, rid, "rule", r.name, r.violations == 0, violations=r.violations,
                             expected="0", actual=str(r.violations), detail=r.sample)
    bad = {r.name: r.violations for r in results if r.violations}
    runner.finish_run(dq_engine, rid, not bad, {"target": "oltp", "violations": bad})
    if bad:
        raise QualityGateError(f"qualidade falhou em oltp, ETL abortado: {bad}")


def run(settings: Settings | None = None) -> int:
    """Retorna o etl_run_id gerado. Lança exceção em falha."""
    settings = settings or get_settings()
    log = configure_logging("poc.etl", settings, "etl.log")
    loader, reader, dq = make_engine("loader", settings), make_engine("reader", settings), make_engine("dq", settings)
    t0 = time.monotonic()
    with loader.begin() as c:
        etl_run_id = c.execute(text(
            "INSERT INTO ops.etl_run (status, duckdb_path) VALUES ('running', :p) RETURNING id"),
            {"p": str(settings.duckdb_file)}).scalar_one()
    log.info("ETL %d iniciado: oltp -> %s", etl_run_id, settings.duckdb_file)
    try:
        frames = extract_all(reader, "oltp")
        counts = {t: int(len(df)) for t, df in frames.items()}
        log.info("extraído de oltp: %s", counts)
        quality_gate(dq, settings, etl_run_id)
        log.info("qualidade de oltp: 0 violações, construindo DuckDB")
        built = build(frames, settings.duckdb_file, etl_run_id, settings.data_end_date)
        dur = int((time.monotonic() - t0) * 1000)
        with loader.begin() as c:
            c.execute(text("UPDATE ops.etl_run SET status='success', finished_at=now(), duration_ms=:d, "
                           "source_row_counts=CAST(:j AS jsonb) WHERE id=:i"),
                      {"d": dur, "j": json.dumps(counts), "i": etl_run_id})
        log.info("ETL %d concluído em %d ms; destino: %s", etl_run_id, dur, built)
        return etl_run_id
    except Exception as exc:
        dur = int((time.monotonic() - t0) * 1000)
        with loader.begin() as c:
            c.execute(text("UPDATE ops.etl_run SET status='failed', finished_at=now(), duration_ms=:d, error=:e WHERE id=:i"),
                      {"d": dur, "e": str(exc)[:2000], "i": etl_run_id})
        log.error("ETL %d falhou: %s (arquivo anterior preservado)", etl_run_id, exc)
        raise
    finally:
        for e in (loader, reader, dq):
            e.dispose()


if __name__ == "__main__":
    try:
        run()
    except Exception:
        sys.exit(1)
