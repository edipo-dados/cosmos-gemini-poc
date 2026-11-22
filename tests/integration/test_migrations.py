import pytest
from sqlalchemy import text

from app.db import make_engine
from database.migrate import migrate

TABLES = ["customers", "products", "categories", "regions", "orders", "order_items", "payments", "refunds"]


def test_second_migrate_is_noop(pg_env):
    assert migrate(pg_env) == []


@pytest.fixture(scope="module")
def admin(pg_env):
    e = make_engine("admin", pg_env)
    yield e
    e.dispose()


def test_oltp_tables_have_pk_fk_indexes_checks(admin):
    with admin.connect() as c:
        q = lambda sql: c.execute(text(sql)).all()
        tables = {r[0] for r in q("SELECT tablename FROM pg_tables WHERE schemaname='oltp'")}
        assert tables == set(TABLES)
        pk = {r[0] for r in q("SELECT conrelid::regclass::text FROM pg_constraint WHERE contype='p' AND connamespace='oltp'::regnamespace")}
        assert pk == {f"oltp.{t}" for t in TABLES}
        fks = {r[0] for r in q("SELECT conrelid::regclass::text || '->' || confrelid::regclass::text FROM pg_constraint WHERE contype='f' AND connamespace='oltp'::regnamespace")}
        for expected in ["oltp.orders->oltp.customers", "oltp.order_items->oltp.orders", "oltp.order_items->oltp.products",
                         "oltp.payments->oltp.orders", "oltp.refunds->oltp.order_items", "oltp.products->oltp.categories",
                         "oltp.customers->oltp.regions"]:
            assert expected in fks
        assert q("SELECT count(*) FROM pg_constraint WHERE contype='c' AND connamespace='oltp'::regnamespace")[0][0] >= 14
        idx = {r[0] for r in q("SELECT indexname FROM pg_indexes WHERE schemaname='oltp'")}
        assert {"ix_orders_order_date", "ix_orders_status", "ix_items_order", "ix_orders_customer"} <= idx
        assert q("SELECT count(*) FROM pg_constraint WHERE contype='f' AND connamespace='dq_lab'::regnamespace")[0][0] == 0
        assert q("SELECT count(*) FROM pg_constraint WHERE contype='c' AND connamespace='dq_lab'::regnamespace")[0][0] == 0


def test_database_name_and_version(admin):
    with admin.connect() as c:
        assert c.execute(text("SELECT current_database()")).scalar_one() == "analytics_poc"
        assert c.execute(text("SHOW server_version")).scalar_one().startswith("16")


def test_check_constraints_reject_invalid_rows_in_oltp(pg_env):
    from sqlalchemy.exc import IntegrityError
    e = make_engine("loader", pg_env)
    with e.connect() as c:
        for sql in [
            "INSERT INTO oltp.orders VALUES (900001, 999999, '2025-01-01', 'paid', 1)",   # FK
            "INSERT INTO oltp.orders VALUES (900002, 1, '2025-01-01', 'bogus', 1)",        # status
            "INSERT INTO oltp.orders VALUES (900003, 1, '2025-01-01', 'paid', -1)",        # negativo
            "INSERT INTO oltp.payments VALUES (900004, 1, 'pix', 'captured', 10, '2025-01-01')",  # UNIQUE order_id
        ]:
            with pytest.raises(IntegrityError):
                c.execute(text(sql))
            c.rollback()
    e.dispose()
