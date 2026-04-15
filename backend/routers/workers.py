"""Справочник рабочих."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api_errors import conflict, not_found
from backend.database import get_db
from backend.models import Operation, Worker
from backend.schemas import WorkerCreate, WorkerResponse, WorkerUpdate

router = APIRouter(prefix="/workers", tags=["workers"])


@router.get(
    "",
    response_model=list[WorkerResponse],
    summary="Список рабочих",
    description="Все записи справочника Worker.",
)
def list_workers(db: Session = Depends(get_db)) -> list[WorkerResponse]:
    rows = db.query(Worker).order_by(Worker.id).all()
    return [WorkerResponse.model_validate(w) for w in rows]


@router.post(
    "",
    response_model=WorkerResponse,
    status_code=201,
    summary="Создать рабочего",
)
def create_worker(body: WorkerCreate, db: Session = Depends(get_db)) -> WorkerResponse:
    w = Worker(name=body.name, profession=body.profession)
    db.add(w)
    try:
        db.commit()
        db.refresh(w)
    except Exception:
        db.rollback()
        raise
    return WorkerResponse.model_validate(w)


@router.get(
    "/{worker_id}",
    response_model=WorkerResponse,
    summary="Рабочий по id",
)
def get_worker(worker_id: int, db: Session = Depends(get_db)) -> WorkerResponse:
    w = db.query(Worker).filter(Worker.id == worker_id).first()
    if not w:
        raise not_found("Рабочий", worker_id)
    return WorkerResponse.model_validate(w)


@router.patch(
    "/{worker_id}",
    response_model=WorkerResponse,
    summary="Обновить рабочего",
)
def update_worker(
    worker_id: int,
    body: WorkerUpdate,
    db: Session = Depends(get_db),
) -> WorkerResponse:
    w = db.query(Worker).filter(Worker.id == worker_id).first()
    if not w:
        raise not_found("Рабочий", worker_id)
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "Нет полей для обновления."})
    for k, v in data.items():
        setattr(w, k, v)
    try:
        db.commit()
        db.refresh(w)
    except Exception:
        db.rollback()
        raise
    return WorkerResponse.model_validate(w)


@router.delete(
    "/{worker_id}",
    status_code=204,
    summary="Удалить рабочего",
    description="Запрещено, если есть Operation с этим worker_id (409).",
)
def delete_worker(worker_id: int, db: Session = Depends(get_db)) -> None:
    w = db.query(Worker).filter(Worker.id == worker_id).first()
    if not w:
        raise not_found("Рабочий", worker_id)
    if db.query(Operation).filter(Operation.worker_id == worker_id).first():
        raise conflict(
            "Нельзя удалить рабочего: есть запланированные операции (Operation). "
            "Сначала пересчитайте расписание без этого ресурса или удалите операции через сценарий планирования.",
            code="WORKER_IN_USE",
        )
    try:
        db.delete(w)
        db.commit()
    except Exception:
        db.rollback()
        raise
