"""Configuração central lida do ambiente (e de .env, ignorado pelo git)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]

ROLE_USERS = {
    "admin": "poc_admin",
    "loader": "poc_loader",
    "reader": "poc_reader",
    "dq": "poc_dq",
    "app": "poc_app",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    pg_host: str = "127.0.0.1"
    pg_port: int = 54329
    pg_database: str = "analytics_poc"
    pg_admin_password: SecretStr = SecretStr("")
    pg_loader_password: SecretStr = SecretStr("")
    pg_reader_password: SecretStr = SecretStr("")
    pg_dq_password: SecretStr = SecretStr("")
    pg_app_password: SecretStr = SecretStr("")

    duckdb_path: str = "analytics.duckdb"
    dq_lab_duckdb_path: str = "dq_lab.duckdb"
    seed: int = 42
    data_end_date: date = date(2026, 10, 31)
    log_dir: str = "logs"

    cosmos_world_dir: str = "."
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-2.5-flash"
    api_url: str = "http://localhost:8000"

    def password(self, role: str) -> str:
        value = getattr(self, f"pg_{role}_password").get_secret_value()
        if not value:
            raise RuntimeError(f"Senha do papel '{role}' ausente: defina PG_{role.upper()}_PASSWORD no ambiente.")
        return value

    def resolve(self, path: str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else ROOT / p

    @property
    def duckdb_file(self) -> Path:
        return self.resolve(self.duckdb_path)

    @property
    def dq_lab_duckdb_file(self) -> Path:
        return self.resolve(self.dq_lab_duckdb_path)

    @property
    def log_path(self) -> Path:
        return self.resolve(self.log_dir)

    def secret_values(self) -> list[str]:
        values = [self.gemini_api_key.get_secret_value()]
        values += [getattr(self, f"pg_{r}_password").get_secret_value() for r in ROLE_USERS]
        return [v for v in values if v]


def get_settings() -> Settings:
    """Nova instância a cada chamada: testes alteram o ambiente."""
    return Settings()
