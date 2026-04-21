"""Активность оборудования (is_active) и планировщик."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.models import Equipment, Order, Task, TechProcess, Worker
from backend.order_status import OrderStatus
from backend.planner import greedy_planner


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_inactive_equipment_not_assigned_in_schedule(db_session: Session) -> None:
    """Выключенная единица той же модели не получает операций; выбирается только активная."""
    tp = TechProcess(name="TP_EQ")
    db_session.add(tp)
    db_session.flush()
    db_session.add(
        Task(
            tech_process_id=tp.id,
            sequence_number=1,
            duration_minutes=20,
            profession="p_eq",
            equipment_model="m_eq",
            name="Op1",
        )
    )
    db_session.flush()
    w = Worker(name="W_eq", profession="p_eq")
    e_on = Equipment(name="Active unit", model="m_eq", is_active=True)
    e_off = Equipment(name="Inactive unit", model="m_eq", is_active=False)
    db_session.add_all([w, e_on, e_off])
    db_session.flush()
    ps = _utc(2026, 5, 1, 4, 0)
    pe = _utc(2026, 5, 1, 8, 0)
    o = Order(
        name="OrderEq",
        profit=Decimal("10"),
        planned_start=ps,
        planned_end=pe,
        tech_process_id=tp.id,
        status=OrderStatus.scheduled.value,
    )
    db_session.add(o)
    db_session.commit()
    _ = o.tech_process
    for t in o.tech_process.tasks:
        _ = t

    orders = db_session.query(Order).all()
    workers = db_session.query(Worker).all()
    equipment = db_session.query(Equipment).all()

    planned, _ = greedy_planner(orders, workers, equipment, ps, pe)

    assert len(planned) == 1
    assert planned[0]["equipment_id"] == e_on.id
    assert planned[0]["equipment_id"] != e_off.id


def test_validation_fails_when_only_inactive_equipment_for_model(db_session: Session) -> None:
    """Предпроверка: только выключенные единицы под модель — TASK_NO_ACTIVE_EQUIPMENT_FOR_MODEL."""
    from backend.planning_validation import validate_planning_inputs

    tp = TechProcess(name="TP_OFF")
    db_session.add(tp)
    db_session.flush()
    db_session.add(
        Task(
            tech_process_id=tp.id,
            sequence_number=1,
            duration_minutes=10,
            profession="p_off",
            equipment_model="m_off",
        )
    )
    db_session.flush()
    db_session.add(Worker(name="W_off", profession="p_off"))
    db_session.add(Equipment(name="Off only", model="m_off", is_active=False))
    db_session.add(
        Order(
            name="O_off",
            profit=Decimal("1"),
            planned_start=_utc(2026, 1, 1),
            planned_end=_utc(2026, 12, 31),
            tech_process_id=tp.id,
            status=OrderStatus.scheduled.value,
        )
    )
    db_session.commit()

    orders = db_session.query(Order).all()
    workers = db_session.query(Worker).all()
    equipment = db_session.query(Equipment).all()
    for x in orders:
        _ = x.tech_process
        for t in x.tech_process.tasks:
            _ = t

    r = validate_planning_inputs(orders, workers, equipment, _utc(2026, 6, 1), _utc(2026, 6, 15))
    assert not r.ok
    assert any(e.code == "TASK_NO_ACTIVE_EQUIPMENT_FOR_MODEL" for e in r.errors)
