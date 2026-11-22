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
sys.path.insert(0, str(ROOT / "tests"))

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


FAKE_GEMINI_KEY = "fake-key-for-scripted-transport-0000000000"


@pytest.fixture(scope="session")
def cosmos_world(tmp_path_factory) -> Path:
    """World real do Cosmos, descartável, com o catálogo sincronizado (o World do projeto não é tocado)."""
    from support.cosmos_world import make_synced_world
    return make_synced_world(tmp_path_factory.mktemp("cosmos") / "world")


@pytest.fixture(scope="session")
def api_settings(pg_env, cosmos_world):
    """Settings da API sem chave Gemini (independe do ambiente do shell)."""
    from pydantic import SecretStr
    return pg_env.model_copy(update={"cosmos_world_dir": str(cosmos_world), "gemini_api_key": SecretStr("")})


@pytest.fixture(scope="session")
def client(api_settings):
    """API real (bancos e Cosmos reais), sem Gemini configurado."""
    from fastapi.testclient import TestClient
    from app.api.main import create_app
    with TestClient(create_app(api_settings)) as c:
        yield c


@pytest.fixture(scope="session")
def fake_gemini():
    from support.fake_gemini import ScriptedGemini
    return ScriptedGemini()


@pytest.fixture(scope="session")
def chat_client(api_settings, fake_gemini):
    """API real com o SDK google-genai real; só o transporte HTTP do SDK é um roteiro falso (não é o Gemini)."""
    from fastapi.testclient import TestClient
    from pydantic import SecretStr
    from app.api.main import create_app
    settings = api_settings.model_copy(update={"gemini_api_key": SecretStr(FAKE_GEMINI_KEY), "gemini_model": "scripted-model"})
    with TestClient(create_app(settings, gemini_http_options=fake_gemini.http_options())) as c:
        yield c
