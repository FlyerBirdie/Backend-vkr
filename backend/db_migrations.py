"""
Идемпотентные правки схемы для существующих БД (create_all не добавляет колонки).

Миграция ``orders.status``: для уже существующих строк выставляется ``scheduled``,
чтобы поведение POST /api/schedule осталось прежним; для новых записей по умолчанию ``draft``.

Миграция ``equipment.is_active``: NOT NULL DEFAULT TRUE для существующих строк.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from backend.order_status import ORDER_STATUS_DB_VALUES


def _check_sql_in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def ensure_orders_status_column(engine: Engine) -> None:
    """PostgreSQL: добавить ``status``, заполнить, NOT NULL, default, CHECK (идемпотентно)."""
    if engine.dialect.name != "postgresql":
        return
    insp = inspect(engine)
    if not insp.has_table("orders"):
        return
    col_names = {c["name"] for c in insp.get_columns("orders")}
    if "status" in col_names:
        return
    in_list = _check_sql_in(ORDER_STATUS_DB_VALUES)
    ddl = [
        "ALTER TABLE orders ADD COLUMN status VARCHAR(32)",
        f"UPDATE orders SET status = 'scheduled' WHERE status IS NULL",
        "ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'draft'",
        "ALTER TABLE orders ALTER COLUMN status SET NOT NULL",
        f"ALTER TABLE orders ADD CONSTRAINT ck_orders_status CHECK (status IN ({in_list}))",
    ]
    with engine.begin() as conn:
        for stmt in ddl:
            conn.execute(text(stmt))


def ensure_equipment_is_active_column(engine: Engine) -> None:
    """PostgreSQL: колонка ``is_active`` NOT NULL DEFAULT true для существующих строк."""
    if engine.dialect.name != "postgresql":
        return
    insp = inspect(engine)
    if not insp.has_table("equipment"):
        return
    col_names = {c["name"] for c in insp.get_columns("equipment")}
    if "is_active" in col_names:
        return
    ddl = [
        "ALTER TABLE equipment ADD COLUMN is_active BOOLEAN",
        "UPDATE equipment SET is_active = TRUE WHERE is_active IS NULL",
        "ALTER TABLE equipment ALTER COLUMN is_active SET DEFAULT TRUE",
        "ALTER TABLE equipment ALTER COLUMN is_active SET NOT NULL",
    ]
    with engine.begin() as conn:
        for stmt in ddl:
            conn.execute(text(stmt))
