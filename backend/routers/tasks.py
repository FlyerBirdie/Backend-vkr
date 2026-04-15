"""Редактирование задач ТП по id (глобальный путь /api/tasks)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api_errors import not_found
from backend.database import get_db
from backend.models import Task
from backend.schemas import TaskResponse, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.patch(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Обновить задачу ТП",
)
def update_task(
    task_id: int,
    body: TaskUpdate,
    db: Session = Depends(get_db),
) -> TaskResponse:
    t = db.query(Task).filter(Task.id == task_id).first()
    if not t:
        raise not_found("Задача ТП", task_id)
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "Нет полей для обновления."})
    for k, v in data.items():
        setattr(t, k, v)
    try:
        db.commit()
        db.refresh(t)
    except Exception:
        db.rollback()
        raise
    return TaskResponse.model_validate(t)


@router.delete(
    "/{task_id}",
    status_code=204,
    summary="Удалить задачу ТП",
    description="CASCADE к Operation по модели БД.",
)
def delete_task(task_id: int, db: Session = Depends(get_db)) -> None:
    t = db.query(Task).filter(Task.id == task_id).first()
    if not t:
        raise not_found("Задача ТП", task_id)
    try:
        db.delete(t)
        db.commit()
    except Exception:
        db.rollback()
        raise
