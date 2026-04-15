"""Read-only: последнее сохранённое расписание из БД."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Operation
from backend.schemas import ScheduledOperationItem

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get(
    "",
    response_model=list[ScheduledOperationItem],
    summary="Список запланированных операций",
    description="Данные из таблицы operations; опционально фильтр по order_id.",
)
def list_operations(
    db: Session = Depends(get_db),
    order_id: int | None = Query(default=None, description="Фильтр по заказу."),
) -> list[ScheduledOperationItem]:
    q = (
        db.query(Operation)
        .join(Operation.order)
        .join(Operation.task)
        .join(Operation.worker)
        .join(Operation.equipment)
        .order_by(Operation.start_time)
    )
    if order_id is not None:
        q = q.filter(Operation.order_id == order_id)
    ops = q.all()
    return [
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
