"""
Сборка ответа ScheduleResponse из сохранённых операций в БД (просмотр после F5).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.models import Equipment, Operation, Order, Worker
from backend.planner import order_sort_key_for_planner, total_profit_of_included_orders
from backend.schemas import (
    AggregateUtilizationMetrics,
    BottleneckItem,
    IncludedOrderItem,
    ResourceUtilizationRow,
    ScheduledOperationItem,
    ScheduleReportMetrics,
    ScheduleResponse,
)
from backend.schedule_metrics import compute_schedule_metrics


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _period_from_operations(ops: list[Operation]) -> tuple[datetime, datetime]:
    min_start = min(_ensure_utc(op.start_time) for op in ops)
    max_end = max(_ensure_utc(op.end_time) for op in ops)
    return min_start, max_end


def build_schedule_response_from_stored(
    db: Session,
    *,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> ScheduleResponse | None:
    """
    Восстанавливает снимок расписания по таблице ``operations``.
    ``planner_used`` не хранится в БД — в ответе ``None``.
    """
    ops = (
        db.query(Operation)
        .join(Operation.order)
        .join(Operation.task)
        .join(Operation.worker)
        .join(Operation.equipment)
        .order_by(Operation.start_time)
        .all()
    )
    if not ops:
        return None

    if period_start is not None and period_end is not None:
        ps = _ensure_utc(period_start)
        pe = _ensure_utc(period_end)
    else:
        ps, pe = _period_from_operations(ops)

    workers = db.query(Worker).all()
    equipment = db.query(Equipment).all()

    items = [
        ScheduledOperationItem(
            id=op.id,
            order_id=op.order_id,
            order_name=op.order.name,
            task_id=op.task_id,
            task_name=op.task.name,
            sequence_number=op.task.sequence_number,
            worker_id=op.worker_id,
            worker_name=op.worker.name,
            worker_profession=op.worker.profession,
            equipment_id=op.equipment_id,
            equipment_name=op.equipment.name,
            equipment_model=op.equipment.model,
            start_time=op.start_time,
            end_time=op.end_time,
        )
        for op in ops
    ]

    order_ids = {op.order_id for op in ops}
    order_objs = db.query(Order).filter(Order.id.in_(order_ids)).all()
    order_objs.sort(key=order_sort_key_for_planner)
    orders_by_id = {o.id: o for o in order_objs}

    included_orders = [
        IncludedOrderItem(id=o.id, name=o.name, profit=o.profit) for o in order_objs
    ]

    planned_dicts = [
        {
            "order_id": op.order_id,
            "task_id": op.task_id,
            "worker_id": op.worker_id,
            "equipment_id": op.equipment_id,
            "start_time": op.start_time,
            "end_time": op.end_time,
        }
        for op in ops
    ]
    total_profit = total_profit_of_included_orders(planned_dicts, orders_by_id)

    mc = compute_schedule_metrics(ps, pe, workers, equipment, ops)
    metrics = ScheduleReportMetrics(
        period_start=ps,
        period_end=pe,
        available_minutes_per_resource=mc.available_minutes,
        workers=[ResourceUtilizationRow.model_validate(r) for r in mc.worker_rows],
        equipment=[ResourceUtilizationRow.model_validate(r) for r in mc.equipment_rows],
        aggregate=AggregateUtilizationMetrics(
            workers_mean_utilization_percent=mc.workers_avg,
            equipment_mean_utilization_percent=mc.equipment_avg,
            total_busy_minutes_sum_workers=mc.total_busy_workers,
            total_busy_minutes_sum_equipment=mc.total_busy_equipment,
            pool_worker_load_percent=mc.pool_worker_load_percent,
            pool_equipment_load_percent=mc.pool_equipment_load_percent,
        ),
        bottlenecks_highest_load=[BottleneckItem.model_validate(x) for x in mc.highest_load],
        bottlenecks_highest_idle=[BottleneckItem.model_validate(x) for x in mc.highest_idle],
        recommendations=mc.recommendations,
    )

    return ScheduleResponse(
        period_start=ps,
        period_end=pe,
        included_orders=included_orders,
        excluded_orders=[],
        total_profit=total_profit,
        operations=items,
        issues=[],
        report_summary=(
            f"Сохранённое расписание из базы: {len(included_orders)} заказ(ов), "
            f"{len(items)} операций."
        ),
        metrics=metrics,
        planner_used=None,
    )
