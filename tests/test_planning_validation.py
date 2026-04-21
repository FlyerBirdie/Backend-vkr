"""Предпроверка данных перед планированием."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.models import Equipment, Order, Task, TechProcess, Worker
from backend.order_status import OrderStatus
from backend.planning_validation import validate_planning_inputs


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_validation_fails_without_matching_worker(db_session: Session) -> None:
    """Нет Worker под профессию задачи — блокирующая ошибка."""
    tp = TechProcess(name="TP")
    db_session.add(tp)
    db_session.flush()
    db_session.add(
        Task(
            tech_process_id=tp.id,
            sequence_number=1,
            duration_minutes=10,
            profession="unique_prof",
            equipment_model="em",
        )
    )
    db_session.add(Equipment(name="E", model="em"))
    db_session.flush()
    o = Order(
        name="O",
        profit=Decimal("1"),
        planned_start=_utc(2026, 1, 1),
        planned_end=_utc(2026, 12, 31),
        tech_process_id=tp.id,
        status=OrderStatus.scheduled.value,
    )
    db_session.add(o)
    db_session.commit()

    orders = db_session.query(Order).all()
    workers = db_session.query(Worker).all()
    equipment = db_session.query(Equipment).all()
    for x in orders:
        _ = x.tech_process
        for t in x.tech_process.tasks:
            _ = t

    r = validate_planning_inputs(
        orders, workers, equipment, _utc(2026, 6, 1), _utc(2026, 6, 15)
    )
    assert not r.ok
    assert any(e.code == "TASK_NO_MATCHING_WORKER" for e in r.errors)
