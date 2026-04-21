"""
Доменные инварианты планировщика: «всё или ничё», ресурсы, sequence, период.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.models import Equipment, Order, Task, TechProcess, Worker
from backend.order_status import OrderStatus
from backend.planning_validation import assert_planned_all_or_nothing
from backend.planner import (
    EXCLUDED_OUTSIDE_PERIOD,
    EXCLUDED_TIME_CONFLICT,
    greedy_planner,
    total_profit_of_included_orders,
)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


SAMARA_TZ = ZoneInfo("Europe/Samara")


def _interval_overlaps_samara_lunch(st: datetime, en: datetime) -> bool:
    """Пересечение с локальным перерывом 12:00–13:00 (один календарный день в Самаре)."""
    st_l = st.astimezone(SAMARA_TZ)
    en_l = en.astimezone(SAMARA_TZ)
    assert st_l.date() == en_l.date(), "тест ожидает операцию в пределах одних суток по Самаре"
    lo = st_l.replace(hour=12, minute=0, second=0, microsecond=0)
    hi = st_l.replace(hour=13, minute=0, second=0, microsecond=0)
    return st_l < hi and en_l > lo


def _assert_no_resource_overlaps(planned: list[dict]) -> None:
    by_w: dict[int, list[tuple[datetime, datetime]]] = defaultdict(list)
    by_e: dict[int, list[tuple[datetime, datetime]]] = defaultdict(list)
    for p in planned:
        by_w[p["worker_id"]].append((p["start_time"], p["end_time"]))
        by_e[p["equipment_id"]].append((p["start_time"], p["end_time"]))
    for wid, ivs in by_w.items():
        s = sorted(ivs, key=lambda x: x[0])
        for i in range(len(s) - 1):
            assert s[i][1] <= s[i + 1][0], f"worker {wid} overlap {s[i]} {s[i+1]}"
    for eid, ivs in by_e.items():
        s = sorted(ivs, key=lambda x: x[0])
        for i in range(len(s) - 1):
            assert s[i][1] <= s[i + 1][0], f"equipment {eid} overlap"


def _assert_sequence_and_period(
    planned: list[dict],
    orders_by_id: dict,
    period_start: datetime,
    period_end: datetime,
) -> None:
    tid_to_seq: dict[int, int] = {}
    for oid, order in orders_by_id.items():
        for t in order.tech_process.tasks:
            tid_to_seq[t.id] = t.sequence_number
    by_order: dict[int, list] = defaultdict(list)
    for p in planned:
        by_order[p["order_id"]].append(p)
    for oid, ops in by_order.items():
        ordered = sorted(ops, key=lambda x: tid_to_seq[x["task_id"]])
        prev_end = None
        for op in ordered:
            assert period_start <= op["start_time"]
            assert op["end_time"] <= period_end
            if prev_end is not None:
                assert op["start_time"] >= prev_end
            prev_end = op["end_time"]


def test_all_or_nothing_second_order_excluded_when_no_time(db_session: Session) -> None:
    """Второй заказ не попадает частично: либо полный ТП, либо исключён с кодом конфликта времени."""
    tp = TechProcess(name="TP")
    db_session.add(tp)
    db_session.flush()
    t1 = Task(
        tech_process_id=tp.id,
        sequence_number=1,
        duration_minutes=30,
        profession="p",
        equipment_model="m",
        name="A",
    )
    t2 = Task(
        tech_process_id=tp.id,
        sequence_number=2,
        duration_minutes=30,
        profession="p",
        equipment_model="m",
        name="B",
    )
    db_session.add_all([t1, t2])
    db_session.flush()
    w = Worker(name="W", profession="p")
    e = Equipment(name="E", model="m")
    db_session.add_all([w, e])
    db_session.flush()

    # 95 минут утреннего куска 08:00–12:00 по Europe/Samara (1 янв. 2026 — чт): 04:00–05:35 UTC.
    ps = _utc(2026, 1, 1, 4, 0)
    pe = _utc(2026, 1, 1, 5, 35)
    o_high = Order(
        name="High",
        profit=Decimal("100"),
        planned_start=ps,
        planned_end=pe,
        tech_process_id=tp.id,
        status=OrderStatus.scheduled.value,
    )
    o_low = Order(
        name="Low",
        profit=Decimal("50"),
        planned_start=ps,
        planned_end=pe,
        tech_process_id=tp.id,
        status=OrderStatus.scheduled.value,
    )
    db_session.add_all([o_high, o_low])
    db_session.commit()

    for o in (o_high, o_low):
        _ = o.tech_process
        for t in o.tech_process.tasks:
            _ = t

    orders = db_session.query(Order).all()
    workers = db_session.query(Worker).all()
    equipment = db_session.query(Equipment).all()

    planned, exclusions = greedy_planner(orders, workers, equipment, ps, pe)

    assert {p["order_id"] for p in planned} == {o_high.id}
    assert len(planned) == 2
    low_ex = next((x for x in exclusions if x.order_id == o_low.id), None)
    assert low_ex is not None
    assert low_ex.code == EXCLUDED_TIME_CONFLICT

    orders_by_id = {o.id: o for o in orders}
    assert_planned_all_or_nothing(planned, orders_by_id)
    assert total_profit_of_included_orders(planned, orders_by_id) == Decimal("100")


def test_operations_inside_period(db_session: Session) -> None:
    """Все операции внутри [period_start, period_end]."""
    tp = TechProcess(name="TP2")
    db_session.add(tp)
    db_session.flush()
    t1 = Task(
        tech_process_id=tp.id,
        sequence_number=1,
        duration_minutes=10,
        profession="p2",
        equipment_model="m2",
    )
    db_session.add(t1)
    db_session.flush()
    w = Worker(name="W2", profession="p2")
    e = Equipment(name="E2", model="m2")
    db_session.add_all([w, e])
    db_session.flush()
    ps = _utc(2026, 6, 1, 10, 0)
    pe = _utc(2026, 6, 2, 10, 0)
    o = Order(
        name="O",
        profit=Decimal("1"),
        planned_start=ps,
        planned_end=pe,
        tech_process_id=tp.id,
        status=OrderStatus.scheduled.value,
    )
    db_session.add(o)
    db_session.commit()
    for x in (o,):
        _ = x.tech_process
        for t in x.tech_process.tasks:
            _ = t

    planned, _ = greedy_planner(
        db_session.query(Order).all(),
        db_session.query(Worker).all(),
        db_session.query(Equipment).all(),
        ps,
        pe,
    )
    orders_by_id = {x.id: x for x in db_session.query(Order).all()}
    _assert_sequence_and_period(planned, orders_by_id, ps, pe)


def test_no_overlaps_and_sequence(db_session: Session) -> None:
    """Нет пересечений по worker/equipment; порядок операций заказа по sequence_number."""
    tp = TechProcess(name="TP3")
    db_session.add(tp)
    db_session.flush()
    tasks = [
        Task(
            tech_process_id=tp.id,
            sequence_number=i,
            duration_minutes=15,
            profession="px",
            equipment_model="mx",
            name=f"S{i}",
        )
        for i in range(1, 4)
    ]
    db_session.add_all(tasks)
    db_session.flush()
    w = Worker(name="Wx", profession="px")
    e = Equipment(name="Ex", model="mx")
    db_session.add_all([w, e])
    db_session.flush()
    ps = _utc(2026, 2, 1, 0, 0)
    pe = _utc(2026, 2, 10, 0, 0)
    o = Order(
        name="Seq",
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

    planned, _ = greedy_planner(
        db_session.query(Order).all(),
        db_session.query(Worker).all(),
        db_session.query(Equipment).all(),
        ps,
        pe,
    )
    _assert_no_resource_overlaps(planned)
    orders_by_id = {o.id: o for o in db_session.query(Order).all()}
    _assert_sequence_and_period(planned, orders_by_id, ps, pe)


def test_order_outside_period_excluded(db_session: Session) -> None:
    """Заказ без пересечения с плановым периодом — исключён, операций нет."""
    tp = TechProcess(name="TP4")
    db_session.add(tp)
    db_session.flush()
    t1 = Task(
        tech_process_id=tp.id,
        sequence_number=1,
        duration_minutes=5,
        profession="py",
        equipment_model="my",
    )
    db_session.add(t1)
    db_session.flush()
    w = Worker(name="Wy", profession="py")
    e = Equipment(name="Ey", model="my")
    db_session.add_all([w, e])
    db_session.flush()
    o = Order(
        name="Outside",
        profit=Decimal("999"),
        planned_start=_utc(2030, 1, 1, 0, 0),
        planned_end=_utc(2030, 1, 2, 0, 0),
        tech_process_id=tp.id,
        status=OrderStatus.scheduled.value,
    )
    db_session.add(o)
    db_session.commit()
    _ = o.tech_process
    for t in o.tech_process.tasks:
        _ = t

    ps = _utc(2026, 3, 1, 0, 0)
    pe = _utc(2026, 3, 2, 0, 0)
    planned, exclusions = greedy_planner(
        db_session.query(Order).all(),
        db_session.query(Worker).all(),
        db_session.query(Equipment).all(),
        ps,
        pe,
    )
    assert planned == []
    assert len(exclusions) == 1
    assert exclusions[0].code == EXCLUDED_OUTSIDE_PERIOD


def test_saturday_in_period_no_scheduled_operations(db_session: Session) -> None:
    """Период только по субботе (Europe/Samara) — рабочих окон нет, операций не создаётся."""
    tp = TechProcess(name="TP_SAT")
    db_session.add(tp)
    db_session.flush()
    db_session.add(
        Task(
            tech_process_id=tp.id,
            sequence_number=1,
            duration_minutes=30,
            profession="psat",
            equipment_model="msat",
        )
    )
    db_session.flush()
    w = Worker(name="Ws", profession="psat")
    e = Equipment(name="Es", model="msat")
    db_session.add_all([w, e])
    db_session.flush()
    o = Order(
        name="SatOrder",
        profit=Decimal("1"),
        planned_start=_utc(2026, 1, 1, 0, 0),
        planned_end=_utc(2026, 12, 31, 23, 0),
        tech_process_id=tp.id,
        status=OrderStatus.scheduled.value,
    )
    db_session.add(o)
    db_session.commit()
    _ = o.tech_process
    for t in o.tech_process.tasks:
        _ = t

    ps = datetime(2026, 4, 18, 0, 0, 0, tzinfo=SAMARA_TZ).astimezone(timezone.utc)
    pe = datetime(2026, 4, 19, 0, 0, 0, tzinfo=SAMARA_TZ).astimezone(timezone.utc)
    planned, exclusions = greedy_planner(
        db_session.query(Order).all(),
        db_session.query(Worker).all(),
        db_session.query(Equipment).all(),
        ps,
        pe,
    )
    assert planned == []
    assert exclusions and exclusions[0].code == EXCLUDED_TIME_CONFLICT


def test_operations_do_not_overlap_lunch_samara(db_session: Session) -> None:
    """После заполнения утреннего куска следующая операция с 13:00 по Самаре, не в 12–13."""
    tp_fill = TechProcess(name="TP_FILL")
    db_session.add(tp_fill)
    db_session.flush()
    for seq in range(1, 5):
        db_session.add(
            Task(
                tech_process_id=tp_fill.id,
                sequence_number=seq,
                duration_minutes=60,
                profession="plunch",
                equipment_model="mlunch",
                name=f"T{seq}",
            )
        )
    tp_one = TechProcess(name="TP_ONE")
    db_session.add(tp_one)
    db_session.flush()
    db_session.add(
        Task(
            tech_process_id=tp_one.id,
            sequence_number=1,
            duration_minutes=60,
            profession="plunch",
            equipment_model="mlunch",
            name="After",
        )
    )
    db_session.flush()
    w = Worker(name="Wl", profession="plunch")
    e = Equipment(name="El", model="mlunch")
    db_session.add_all([w, e])
    db_session.flush()
    day = datetime(2026, 4, 13, 8, 0, 0, tzinfo=SAMARA_TZ)
    day_end = datetime(2026, 4, 13, 17, 0, 0, tzinfo=SAMARA_TZ)
    win_s, win_e = day.astimezone(timezone.utc), day_end.astimezone(timezone.utc)
    o_big = Order(
        name="FillMorning",
        profit=Decimal("500"),
        planned_start=win_s,
        planned_end=win_e,
        tech_process_id=tp_fill.id,
        status=OrderStatus.scheduled.value,
    )
    o_small = Order(
        name="Afternoon",
        profit=Decimal("100"),
        planned_start=win_s,
        planned_end=win_e,
        tech_process_id=tp_one.id,
        status=OrderStatus.scheduled.value,
    )
    db_session.add_all([o_big, o_small])
    db_session.commit()
    for o in (o_big, o_small):
        _ = o.tech_process
        for t in o.tech_process.tasks:
            _ = t

    planned, _ = greedy_planner(
        db_session.query(Order).all(),
        db_session.query(Worker).all(),
        db_session.query(Equipment).all(),
        win_s,
        win_e,
    )
    assert len(planned) == 5
    for p in planned:
        assert not _interval_overlaps_samara_lunch(p["start_time"], p["end_time"])
    last = max(planned, key=lambda x: x["start_time"])
    assert last["start_time"].astimezone(SAMARA_TZ).hour >= 13
