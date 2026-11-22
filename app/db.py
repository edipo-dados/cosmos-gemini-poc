"""Engines SQLAlchemy por papel do PostgreSQL."""
from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL

from app.config import ROLE_USERS, Settings, get_settings


def pg_url(role: str, settings: Settings | None = None, database: str | None = None) -> URL:
    settings = settings or get_settings()
    return URL.create(
        "postgresql+psycopg",
        username=ROLE_USERS[role],
        password=settings.password(role),
        host=settings.pg_host,
        port=settings.pg_port,
        database=database or settings.pg_database,
    )


def make_engine(role: str, settings: Settings | None = None) -> Engine:
    connect_args = {}
    if role == "reader":
        connect_args["options"] = "-c default_transaction_read_only=on"
    return create_engine(pg_url(role, settings), connect_args=connect_args, pool_pre_ping=True)
