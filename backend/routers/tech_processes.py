"""Технологические процессы и добавление задач в ТП."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api_errors import not_found
from backend.database import get_db
from backend.models import Task, TechProcess
from backend.schemas import (
    TaskCreate,
    TaskResponse,
    TechProcessCreate,
    TechProcessDetailResponse,
    TechProcessListItem,
    TechProcessUpdate,
)

router = APIRouter(prefix="/tech-processes", tags=["tech-processes"])


@router.get(
    "",
    response_model=list[TechProcessListItem],
    summary="Список технологических процессов",
)
def list_tech_processes(db: Session = Depends(get_db)) -> list[TechProcessListItem]:
    rows = db.query(TechProcess).order_by(TechProcess.id).all()
    return [TechProcessListItem.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=TechProcessListItem,
    status_code=201,
    summary="Создать технологический процесс",
)
def create_tech_process(body: TechProcessCreate, db: Session = Depends(get_db)) -> TechProcessListItem:
    tp = TechProcess(name=body.name)
    db.add(tp)
    try:
        db.commit()
        db.refresh(tp)
    except Exception:
        db.rollback()
        raise
    return TechProcessListItem.model_validate(tp)


@router.get(
    "/{tech_process_id}",
    response_model=TechProcessDetailResponse,
    summary="Техпроцесс с задачами",
    description="Вложенный список Task в порядке sequence_number.",
)
def get_tech_process(tech_process_id: int, db: Session = Depends(get_db)) -> TechProcessDetailResponse:
    tp = db.query(TechProcess).filter(TechProcess.id == tech_process_id).first()
    if not tp:
        raise not_found("Технологический процесс", tech_process_id)
    _ = tp.tasks  # load
    tasks = sorted(tp.tasks, key=lambda t: t.sequence_number)
    return TechProcessDetailResponse(
        id=tp.id,
        name=tp.name,
        tasks=[TaskResponse.model_validate(t) for t in tasks],
    )


@router.patch(
    "/{tech_process_id}",
    response_model=TechProcessListItem,
    summary="Переименовать технологический процесс",
)
def update_tech_process(
    tech_process_id: int,
    body: TechProcessUpdate,
    db: Session = Depends(get_db),
) -> TechProcessListItem:
    tp = db.query(TechProcess).filter(TechProcess.id == tech_process_id).first()
    if not tp:
        raise not_found("Технологический процесс", tech_process_id)
    data = body.model_dump(exclude_unset=True)
    if not data or "name" not in data:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "Укажите поле name для переименования ТП."},
        )
    tp.name = data["name"]
    try:
        db.commit()
        db.refresh(tp)
    except Exception:
        db.rollback()
        raise
    return TechProcessListItem.model_validate(tp)


@router.post(
    "/{tech_process_id}/tasks",
    response_model=TaskResponse,
    status_code=201,
    summary="Добавить задачу (операцию) в ТП",
)
def create_task(
    tech_process_id: int,
    body: TaskCreate,
    db: Session = Depends(get_db),
) -> TaskResponse:
    tp = db.query(TechProcess).filter(TechProcess.id == tech_process_id).first()
    if not tp:
        raise not_found("Технологический процесс", tech_process_id)
    t = Task(
        tech_process_id=tech_process_id,
        sequence_number=body.sequence_number,
        duration_minutes=body.duration_minutes,
        profession=body.profession,
        equipment_model=body.equipment_model,
        name=body.name,
    )
    db.add(t)
    try:
        db.commit()
        db.refresh(t)
    except Exception:
        db.rollback()
        raise
    return TaskResponse.model_validate(t)
