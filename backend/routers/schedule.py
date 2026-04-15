"""Пересчёт расписания (единственное место массового удаления Operation)."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Equipment, Operation, Order, Worker
from backend.planner import (
    PlannedOperation,
    PlannerExclusion,
    default_planning_period,
    greedy_planner,
    order_sort_key_for_planner,
    total_profit_of_included_orders,
)
from backend.planning_validation import (
    assert_planned_all_or_nothing,
    build_schedule_report_summary,
    human_summary_for_validation,
    planning_issue_to_api_dict,
    validate_planning_inputs,
)
from backend.schedule_metrics import compute_schedule_metrics
from backend.schemas import (
    AggregateUtilizationMetrics,
    BottleneckItem,
    ExcludedOrderItem,
    IncludedOrderItem,
    PlanningValidationErrorContent,
    ResourceUtilizationRow,
    ScheduledOperationItem,
    ScheduleIssueItem,
    ScheduleReportMetrics,
    ScheduleRequest,
    ScheduleResponse,
)

router = APIRouter(tags=["schedule"])


@router.post(
    "/schedule",
    response_model=ScheduleResponse,
    summary="Расчёт расписания",
    responses={
        422: {
            "description": (
                "Данные из БД или период не проходят проверку перед планированием; БД не изменяется. "
                "Тело ответа: стандартное обёртывание FastAPI — объект с полем `detail` "
                "(схема PlanningValidationErrorContent)."
            ),
        },
    },
)
def build_schedule(
    body: ScheduleRequest = Body(default_factory=ScheduleRequest),
    db: Session = Depends(get_db),
) -> ScheduleResponse:
    """
    Пересчитывает расписание жадным алгоритмом: старые записи `operations` удаляются
    только после успешной **предпроверки** данных (ТП, задачи, наличие Worker/Equipment).

    **Плановый период:** операции размещаются только в пересечении
    `[period_start, period_end]` запроса (или периода по умолчанию) и окна заказа
    `[planned_start, planned_end]`. Период по умолчанию: с 00:00 UTC текущих суток на 14 суток вперёд.

    Заказ либо целиком попадает в ответ (`included_orders`), либо перечислен в `excluded_orders`
    с кодом и причиной (принцип «всё или ничё»). Частично запланированных заказов в `operations` нет.

    Поле **`metrics`**: загрузка персонала и оборудования в % от фонда периода, агрегаты,
    узкие места (макс. загрузка / макс. простой), строки-рекомендации для демо и отчёта ВКР.

    При ошибках проверки данных возвращается **422** с полем `detail`: структура
    `PlanningValidationErrorContent` (ошибки, предупреждения, `report_summary`); транзакция не выполняется.
    """
    if body.period_start is None:
        period_start, period_end = default_planning_period()
    else:
        period_start, period_end = body.period_start, body.period_end

    orders = db.query(Order).all()
    workers = db.query(Worker).all()
    equipment = db.query(Equipment).all()

    for o in orders:
        _ = o.tech_process
        for t in o.tech_process.tasks:
            _ = t

    validation_result = validate_planning_inputs(
        orders, workers, equipment, period_start, period_end
    )
    if not validation_result.ok:
        payload = PlanningValidationErrorContent(
            errors=[
                ScheduleIssueItem.model_validate(planning_issue_to_api_dict(e))
                for e in validation_result.errors
            ],
            warnings=[
                ScheduleIssueItem.model_validate(planning_issue_to_api_dict(w))
                for w in validation_result.warnings
            ],
            report_summary=human_summary_for_validation(validation_result),
        )
        raise HTTPException(status_code=422, detail=payload.model_dump())

    planned: list[PlannedOperation]
    planner_exclusions: list[PlannerExclusion]
    planned, planner_exclusions = greedy_planner(
        orders, workers, equipment, period_start, period_end
    )

    orders_by_id = {o.id: o for o in orders}
    assert_planned_all_or_nothing(planned, orders_by_id)

    try:
        db.query(Operation).delete()
        for p in planned:
            op = Operation(
                order_id=p["order_id"],
                task_id=p["task_id"],
                worker_id=p["worker_id"],
                equipment_id=p["equipment_id"],
                start_time=p["start_time"],
                end_time=p["end_time"],
            )
            db.add(op)
        db.commit()
    except Exception:
        db.rollback()
        raise

    order_ids_planned: set[int] = {p["order_id"] for p in planned}

    total_profit = total_profit_of_included_orders(planned, orders_by_id)

    included_orders: list[IncludedOrderItem] = []
    planned_order_objs = [o for o in orders if o.id in order_ids_planned]
    planned_order_objs.sort(key=order_sort_key_for_planner)
    for order in planned_order_objs:
        included_orders.append(
            IncludedOrderItem(id=order.id, name=order.name, profit=order.profit)
        )

    excluded_orders = [
        ExcludedOrderItem(
            order_id=e.order_id,
            order_name=e.order_name,
            code=e.code,
            reason=e.reason,
        )
        for e in planner_exclusions
    ]

    issues: list[ScheduleIssueItem] = [
        ScheduleIssueItem.model_validate(planning_issue_to_api_dict(w))
        for w in validation_result.warnings
    ]
    for ex in planner_exclusions:
        issues.append(
            ScheduleIssueItem(
                level="warning",
                code=ex.code,
                message=ex.reason,
                order_id=ex.order_id,
                order_name=ex.order_name,
            )
        )

    report_summary = build_schedule_report_summary(
        period_start=period_start,
        period_end=period_end,
        validation_warning_count=len(validation_result.warnings),
        included_count=len(included_orders),
        excluded_count=len(excluded_orders),
        total_profit=total_profit,
    )

    ops = (
        db.query(Operation)
        .join(Operation.order)
        .join(Operation.task)
        .join(Operation.worker)
        .join(Operation.equipment)
        .order_by(Operation.start_time)
        .all()
    )

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

    mc = compute_schedule_metrics(period_start, period_end, workers, equipment, ops)
    metrics = ScheduleReportMetrics(
        period_start=period_start,
        period_end=period_end,
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
        period_start=period_start,
        period_end=period_end,
        included_orders=included_orders,
        excluded_orders=excluded_orders,
        total_profit=total_profit,
        operations=items,
        issues=issues,
        report_summary=report_summary,
        metrics=metrics,
    )
