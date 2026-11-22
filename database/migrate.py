"""Aplica database/migrations/*.sql em ordem como poc_admin. Idempotente.

Uso: python -m database.migrate
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import psycopg

from app.config import ROLE_USERS, Settings, get_settings
from app.logging_setup import configure_logging

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
LOGIN_ROLES = ("loader", "reader", "dq", "app")


def _connect(settings: Settings, database: str) -> psycopg.Connection:
    return psycopg.connect(
        host=settings.pg_host, port=settings.pg_port, dbname=database,
        user=ROLE_USERS["admin"], password=settings.password("admin"), autocommit=True,
    )


def ensure_database(settings: Settings, log: logging.Logger) -> None:
    with _connect(settings, "postgres") as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings.pg_database,)).fetchone()
        if not exists:
            conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(settings.pg_database)))
            log.info("banco %s criado", settings.pg_database)


def set_role_passwords(conn: psycopg.Connection, settings: Settings) -> None:
    """Senhas vêm do ambiente; o quoting é feito no servidor por format(%I, %L)."""
    for role in LOGIN_ROLES:
        stmt = conn.execute(
            "SELECT format('ALTER ROLE %%I PASSWORD %%L', %s::text, %s::text)",
            (ROLE_USERS[role], settings.password(role)),
        ).fetchone()[0]
        conn.execute(stmt)


def migrate(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    log = configure_logging("poc.migrate", settings)
    ensure_database(settings, log)
    applied_now: list[str] = []
    with _connect(settings, settings.pg_database) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS ops")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ops.schema_migrations ("
            "version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = dict(conn.execute("SELECT version, checksum FROM ops.schema_migrations").fetchall())
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.stem
            sql_text = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql_text.encode()).hexdigest()
            if version in done:
                if done[version] != checksum:
                    log.warning("migração %s foi alterada depois de aplicada", version)
                continue
            with conn.transaction():
                conn.execute(sql_text)
                conn.execute("INSERT INTO ops.schema_migrations (version, checksum) VALUES (%s, %s)", (version, checksum))
            applied_now.append(version)
            log.info("migração aplicada: %s", version)
        # roles existem após 001; as senhas são sempre reaplicadas do ambiente
        set_role_passwords(conn, settings)
        # re-aplica os GRANTs (tabelas criadas por migrações futuras)
        conn.execute((MIGRATIONS_DIR / "006_grants.sql").read_text(encoding="utf-8"))
    if not applied_now:
        log.info("nenhuma migração pendente")
    return applied_now


if __name__ == "__main__":
    migrate()
