"""Генетический планировщик: детерминизм (seed) и отсутствие пересечений ресурсов."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.genetic_planner import genetic_planner
from backend.models import Equipment, Order, Task, TechProcess, Worker
from backend.order_status import OrderStatus


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


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


def _freeze_tuple_plan(planned: list) -> tuple[tuple, ...]:
    out = []
    for p in planned:
        out.append(
            (
                p["order_id"],
                p["task_id"],
                p["worker_id"],
                p["equipment_id"],
                p["start_time"].isoformat(),
                p["end_time"].isoformat(),
            )
        )
    return tuple(sorted(out))


def _freeze_exclusions(exc) -> tuple[tuple, ...]:
    return tuple(
        sorted(
            ((e.order_id, e.code, e.order_name, e.reason) for e in exc),
            key=lambda x: (x[0], x[1]),
        )
    )


def test_genetic_same_result_with_fixed_seed(monkeypatch, db_session: Session) -> None:
    monkeypatch.setenv("GENETIC_SEED", "31415")
    monkeypatch.setenv("GENETIC_POP_SIZE", "8")
    monkeypatch.setenv("GENETIC_GENERATIONS", "6")

    tp = TechProcess(name="TPg")
    db_session.add(tp)
    db_session.flush()
    t1 = Task(
        tech_process_id=tp.id,
        sequence_number=1,
        duration_minutes=30,
        profession="pg",
        equipment_model="mg",
        name="g1",
    )
    t2 = Task(
        tech_process_id=tp.id,
        sequence_number=2,
        duration_minutes=30,
        profession="pg",
        equipment_model="mg",
        name="g2",
    )
    db_session.add_all([t1, t2])
    db_session.flush()
    w = Worker(name="Wg", profession="pg")
    e = Equipment(name="Eg", model="mg")
    db_session.add_all([w, e])
    db_session.flush()

    ps = _utc(2026, 1, 1, 4, 0)
    pe = _utc(2026, 1, 1, 5, 35)
    o_high = Order(
        name="Gh",
        profit=Decimal("100"),
        planned_start=ps,
        planned_end=pe,
        tech_process_id=tp.id,
        status=OrderStatus.scheduled.value,
    )
    o_low = Order(
        name="Gl",
        profit=Decimal("50"),
        planned_start=ps,
        planned_end=pe,
        tech_process_id=tp.id,
        status=OrderStatus.scheduled.value,
    )
    db_session.add_all([o_high, o_low])
    db_session.commit()

    orders = db_session.query(Order).all()
    workers = db_session.query(Worker).all()
    equipment = db_session.query(Equipment).all()
    for o in orders:
        _ = o.tech_process
        for t in o.tech_process.tasks:
            _ = t

    a1, e1 = genetic_planner(orders, workers, equipment, ps, pe)
    a2, e2 = genetic_planner(orders, workers, equipment, ps, pe)
    assert _freeze_tuple_plan(a1) == _freeze_tuple_plan(a2)
    assert _freeze_exclusions(e1) == _freeze_exclusions(e2)


def test_genetic_no_resource_overlaps(db_session: Session) -> None:
    tp = TechProcess(name="TPg2")
    db_session.add(tp)
    db_session.flush()
    t1 = Task(
        tech_process_id=tp.id,
        sequence_number=1,
        duration_minutes=10,
        profession="px",
        equipment_model="mx",
    )
    db_session.add(t1)
    db_session.flush()
    w = Worker(name="Wx", profession="px")
    e = Equipment(name="Ex", model="mx")
    db_session.add_all([w, e])
    db_session.flush()
    ps = _utc(2026, 7, 1, 4, 0)
    pe = _utc(2026, 7, 5, 20, 0)
    o = Order(
        name="Og",
        profit=Decimal("3"),
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

    planned, _ = genetic_planner(
        db_session.query(Order).all(),
        db_session.query(Worker).all(),
        db_session.query(Equipment).all(),
        ps,
        pe,
    )
    _assert_no_resource_overlaps(planned)
