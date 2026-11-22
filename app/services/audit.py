"""Auditoria no PostgreSQL com o papel `poc_app` (INSERT/SELECT; UPDATE só nas colunas finais de `chat_turn`).
Esquema e permissões: database/migrations/004_audit.sql e 006_grants.sql (docs/ARCHITECTURE.md, seção 9)."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Engine, text

JSON_COLUMNS = ("dimensions", "filters", "sql_params", "result", "evidence")
INSERT_QUERY = text("""
INSERT INTO audit.query_audit (query_id, turn_id, user_id, tool_name, metric, dimensions, filters, row_limit, sql_text,
    sql_params, source, etl_run_id, catalog_version, status, error_code, row_count, duration_ms, result, evidence,
    cosmos_episode_id, cosmos_decision_id)
VALUES (:query_id, :turn_id, :user_id, :tool_name, :metric, CAST(:dimensions AS jsonb), CAST(:filters AS jsonb),
    :row_limit, :sql_text, CAST(:sql_params AS jsonb), :source, :etl_run_id, :catalog_version, :status, :error_code,
    :row_count, :duration_ms, CAST(:result AS jsonb), CAST(:evidence AS jsonb), :cosmos_episode_id, :cosmos_decision_id)
""")
QUERY_COLUMNS = ("query_id, turn_id, created_at, user_id, tool_name, metric, dimensions, filters, row_limit, sql_text, "
                 "sql_params, source, etl_run_id, catalog_version, status, error_code, row_count, duration_ms, result, "
                 "evidence, cosmos_episode_id, cosmos_decision_id")


def _dump(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


class AuditStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def ping(self) -> None:
        with self.engine.connect() as con:
            con.execute(text("SELECT 1 FROM audit.chat_turn LIMIT 1"))

    def insert_turn(self, turn_id: str, user_id: str, session_id: str, question: str, request_id: str) -> None:
        with self.engine.begin() as con:
            con.execute(text("INSERT INTO audit.chat_turn (turn_id, user_id, session_id, question, status, request_id) "
                             "VALUES (:t, :u, :s, :q, 'started', :r)"),
                        {"t": turn_id, "u": user_id, "s": session_id, "q": question, "r": request_id})

    def finish_turn(self, turn_id: str, status: str, answer: str | None, model: str | None, episode_id: str | None) -> None:
        with self.engine.begin() as con:
            con.execute(text("UPDATE audit.chat_turn SET status=:st, answer=:a, gemini_model=:m, cosmos_episode_id=:e "
                             "WHERE turn_id=:t"), {"st": status, "a": answer, "m": model, "e": episode_id, "t": turn_id})

    def insert_query(self, row: dict) -> None:
        params = {k: row.get(k) for k in ("query_id", "turn_id", "user_id", "tool_name", "metric", "row_limit", "sql_text",
                                          "source", "etl_run_id", "catalog_version", "status", "error_code", "row_count",
                                          "duration_ms", "cosmos_episode_id", "cosmos_decision_id")}
        for col in JSON_COLUMNS:
            params[col] = _dump(row.get(col))
        with self.engine.begin() as con:
            con.execute(INSERT_QUERY, params)

    def get_query(self, query_id: str, user_id: str) -> dict | None:
        """Só devolve a linha do mesmo `user_id`; outro usuário equivale a inexistente."""
        with self.engine.connect() as con:
            r = con.execute(text(f"SELECT {QUERY_COLUMNS} FROM audit.query_audit WHERE query_id=:q AND user_id=:u"),
                            {"q": query_id, "u": user_id}).mappings().first()
        return _plain(r) if r else None

    def list_queries(self, user_id: str, limit: int = 50) -> list[dict]:
        with self.engine.connect() as con:
            rows = con.execute(text("SELECT query_id, turn_id, created_at, tool_name, metric, status, error_code, row_count, "
                                    "duration_ms, cosmos_decision_id FROM audit.query_audit WHERE user_id=:u "
                                    "ORDER BY created_at DESC LIMIT :n"), {"u": user_id, "n": limit}).mappings().all()
        return [_plain(r) for r in rows]


def _plain(row) -> dict:
    out = {}
    for k, v in dict(row).items():
        out[k] = str(v) if k in ("query_id", "turn_id") and v is not None else (v.isoformat() if hasattr(v, "isoformat") else v)
    return out
