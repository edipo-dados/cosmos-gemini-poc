"""Fixtures de sessão: PostgreSQL real (pgserver, cluster temporário), geração, ETL e DuckDB reais."""
from __future__ import annotations

import secrets
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

ROLES = ["ADMIN", "LOADER", "READER", "DQ", "APP"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def pg_env(tmp_path_factory):
    """Sobe um PostgreSQL 16 real com banco, papéis, esquema e dados; devolve Settings."""
    import pg_local
    from app.config import get_settings
    from data.generators.run import run as run_generator
    from database.migrate import migrate
    from pipelines.transform.run import run as run_etl

    base = tmp_path_factory.mktemp("poc")
    port = _free_port()
    mp = pytest.MonkeyPatch()
    mp.setenv("PG_HOST", "127.0.0.1")
    mp.setenv("PG_PORT", str(port))
    mp.setenv("PG_DATABASE", "analytics_poc")
    for r in ROLES:
        mp.setenv(f"PG_{r}_PASSWORD", secrets.token_urlsafe(16))
    mp.setenv("DUCKDB_PATH", str(base / "analytics.duckdb"))
    mp.setenv("DQ_LAB_DUCKDB_PATH", str(base / "dq_lab.duckdb"))
    mp.setenv("LOG_DIR", str(base / "logs"))
    mp.setenv("SEED", "42")
    mp.setenv("DATA_END_DATE", "2026-10-31")
    settings = get_settings()
    datadir = base / "pgdata"
    pg_local.start(datadir, port, settings.password("admin"))
    try:
        migrate(settings)
        assert run_generator(settings=settings, manifest_path=base / "dq_expected.json") == 0
        run_etl(settings)
        yield settings
    finally:
        pg_local.stop(datadir)
        mp.undo()


@pytest.fixture(scope="session")
def duckdb_path(pg_env) -> Path:
    return pg_env.duckdb_file
