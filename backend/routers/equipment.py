"""Справочник оборудования."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api_errors import conflict, not_found
from backend.database import get_db
from backend.models import Equipment, Operation
from backend.schemas import EquipmentCreate, EquipmentResponse, EquipmentUpdate

router = APIRouter(prefix="/equipment", tags=["equipment"])


@router.get(
    "",
    response_model=list[EquipmentResponse],
    summary="Список оборудования",
)
def list_equipment(db: Session = Depends(get_db)) -> list[EquipmentResponse]:
    rows = db.query(Equipment).order_by(Equipment.id).all()
    return [EquipmentResponse.model_validate(e) for e in rows]


@router.post(
    "",
    response_model=EquipmentResponse,
    status_code=201,
    summary="Создать единицу оборудования",
)
def create_equipment(body: EquipmentCreate, db: Session = Depends(get_db)) -> EquipmentResponse:
    e = Equipment(name=body.name, model=body.model, is_active=body.is_active)
    db.add(e)
    try:
        db.commit()
        db.refresh(e)
    except Exception:
        db.rollback()
        raise
    return EquipmentResponse.model_validate(e)


@router.get(
    "/{equipment_id}",
    response_model=EquipmentResponse,
    summary="Оборудование по id",
)
def get_equipment(equipment_id: int, db: Session = Depends(get_db)) -> EquipmentResponse:
    e = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not e:
        raise not_found("Оборудование", equipment_id)
    return EquipmentResponse.model_validate(e)


@router.patch(
    "/{equipment_id}",
    response_model=EquipmentResponse,
    summary="Обновить оборудование",
    description="В т.ч. is_active=false — выключить из планирования без удаления записи.",
)
def update_equipment(
    equipment_id: int,
    body: EquipmentUpdate,
    db: Session = Depends(get_db),
) -> EquipmentResponse:
    e = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not e:
        raise not_found("Оборудование", equipment_id)
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "Нет полей для обновления."})
    for k, v in data.items():
        setattr(e, k, v)
    try:
        db.commit()
        db.refresh(e)
    except Exception:
        db.rollback()
        raise
    return EquipmentResponse.model_validate(e)


@router.delete(
    "/{equipment_id}",
    status_code=204,
    summary="Удалить оборудование",
    description="Запрещено при наличии Operation с этим equipment_id (409).",
)
def delete_equipment(equipment_id: int, db: Session = Depends(get_db)) -> None:
    e = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not e:
        raise not_found("Оборудование", equipment_id)
    if db.query(Operation).filter(Operation.equipment_id == equipment_id).first():
        raise conflict(
            "Нельзя удалить оборудование: есть запланированные операции (Operation).",
            code="EQUIPMENT_IN_USE",
        )
    try:
        db.delete(e)
        db.commit()
    except Exception:
        db.rollback()
        raise
