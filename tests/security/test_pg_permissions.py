"""Permissões mínimas provadas com conexões reais, um papel por vez."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import make_engine


@pytest.fixture
def conn(pg_env):
    made = []

    def _open(role):
        e = make_engine(role, pg_env)
        made.append(e)
        return e.connect()

    yield _open
    for e in made:
        e.dispose()


def denied(c, sql, params=None):
    with pytest.raises(DBAPIError):
        c.execute(text(sql), params or {})
    c.rollback()


def test_reader_is_read_only_and_blind_to_dq_lab(conn):
    c = conn("reader")
    assert c.execute(text("SELECT count(*) FROM oltp.customers")).scalar_one() == 5000
    denied(c, "INSERT INTO oltp.regions VALUES (99, 'x', 'XX')")
    denied(c, "SELECT * FROM dq_lab.orders")
    denied(c, "SELECT * FROM audit.chat_turn")
    assert c.execute(text("SHOW default_transaction_read_only")).scalar_one() == "on"


def test_loader_has_no_ddl_and_no_audit(conn):
    c = conn("loader")
    denied(c, "CREATE TABLE oltp.x (a int)")
    denied(c, "SELECT * FROM audit.query_audit")


def test_dq_cannot_write_oltp(conn):
    c = conn("dq")
    assert c.execute(text("SELECT count(*) FROM dq_lab.orders")).scalar_one() > 0
    denied(c, "DELETE FROM oltp.orders")
    denied(c, "INSERT INTO ops.etl_run (status) VALUES ('running')")


def _start_turn(c):
    tid = str(uuid.uuid4())
    c.execute(text("INSERT INTO audit.chat_turn (turn_id, user_id, session_id, question, status, request_id) "
                   "VALUES (:t, 'demo', 's', 'pergunta?', 'started', 'r1')"), {"t": tid})
    c.commit()
    return tid


def test_app_audit_permissions(conn):
    c = conn("app")
    denied(c, "SELECT * FROM oltp.orders")
    tid = _start_turn(c)
    qid = str(uuid.uuid4())
    c.execute(text("INSERT INTO audit.query_audit (query_id, turn_id, user_id, tool_name, status) "
                   "VALUES (:q, :t, 'demo', 'list_metrics', 'ok')"), {"q": qid, "t": tid})
    c.commit()
    denied(c, "UPDATE audit.query_audit SET status='error' WHERE query_id=:q", {"q": qid})
    denied(c, "DELETE FROM audit.query_audit WHERE query_id=:q", {"q": qid})
    denied(c, "DELETE FROM audit.chat_turn WHERE turn_id=:t", {"t": tid})
    denied(c, "UPDATE audit.chat_turn SET question='outra' WHERE turn_id=:t", {"t": tid})
    # FK de query_audit.turn_id
    denied(c, "INSERT INTO audit.query_audit (query_id, turn_id, user_id, tool_name, status) "
              "VALUES (gen_random_uuid(), gen_random_uuid(), 'demo', 'x', 'ok')")


def test_chat_turn_transitions(conn, pg_env):
    c = conn("app")
    tid = _start_turn(c)
    c.execute(text("UPDATE audit.chat_turn SET status='ok', answer='resposta' WHERE turn_id=:t"), {"t": tid})
    c.commit()
    denied(c, "UPDATE audit.chat_turn SET status='error' WHERE turn_id=:t", {"t": tid})  # ok -> error
    # mesmo como admin (dono), o gatilho rejeita a mudança de coluna imutável
    admin = conn("admin")
    denied(admin, "UPDATE audit.chat_turn SET question='x' WHERE turn_id=:t", {"t": tid})


def test_query_audit_fk_exists(conn):
    c = conn("admin")
    n = c.execute(text("SELECT count(*) FROM pg_constraint WHERE contype='f' AND conrelid='audit.query_audit'::regclass")).scalar_one()
    assert n == 1
