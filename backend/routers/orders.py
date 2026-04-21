"""Заказы: CRUD (список совместим с прежним GET /api/orders)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api_errors import conflict, not_found
from backend.database import get_db
from backend.models import Operation, Order, TechProcess
from backend.order_status import OrderStatus, assert_order_status_transition_allowed
from backend.schemas import OrderCreate, OrderResponse, OrderUpdate

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get(
    "",
    response_model=list[OrderResponse],
    summary="Список заказов",
    description="Все заказы (как прежний GET /api/orders).",
)
def list_orders(db: Session = Depends(get_db)) -> list[OrderResponse]:
    orders = db.query(Order).order_by(Order.id).all()
    return [OrderResponse.model_validate(o) for o in orders]


@router.post(
    "",
    response_model=OrderResponse,
    status_code=201,
    summary="Создать заказ",
    description="planned_end > planned_start; tech_process_id должен существовать. "
    "Поле status по умолчанию draft; для участия в POST /api/schedule задайте scheduled.",
)
def create_order(body: OrderCreate, db: Session = Depends(get_db)) -> OrderResponse:
    if not db.query(TechProcess).filter(TechProcess.id == body.tech_process_id).first():
        raise HTTPException(
            status_code=422,
            detail={
                "code": "VALIDATION_ERROR",
                "message": f"Технологический процесс id={body.tech_process_id} не найден.",
            },
        )
    o = Order(
        name=body.name,
        profit=body.profit,
        planned_start=body.planned_start,
        planned_end=body.planned_end,
        tech_process_id=body.tech_process_id,
        status=body.status.value,
    )
    db.add(o)
    try:
        db.commit()
        db.refresh(o)
    except Exception:
        db.rollback()
        raise
    return OrderResponse.model_validate(o)


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Заказ по id",
)
def get_order(order_id: int, db: Session = Depends(get_db)) -> OrderResponse:
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o:
        raise not_found("Заказ", order_id)
    return OrderResponse.model_validate(o)


@router.patch(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Обновить заказ",
)
def update_order(
    order_id: int,
    body: OrderUpdate,
    db: Session = Depends(get_db),
) -> OrderResponse:
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o:
        raise not_found("Заказ", order_id)
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "Нет полей для обновления."})
    if "status" in data:
        new_raw = data["status"]
        new_s = new_raw.value if isinstance(new_raw, OrderStatus) else str(new_raw)
        try:
            assert_order_status_transition_allowed(str(o.status), new_s)
        except ValueError as e:
            raise HTTPException(
                status_code=422,
                detail={"code": "ORDER_STATUS_TRANSITION_INVALID", "message": str(e)},
            ) from e
        data["status"] = new_s
    if "tech_process_id" in data:
        tid = data["tech_process_id"]
        if not db.query(TechProcess).filter(TechProcess.id == tid).first():
            raise HTTPException(
                status_code=422,
                detail={"code": "VALIDATION_ERROR", "message": f"Технологический процесс id={tid} не найден."},
            )
    ns = data["planned_start"] if "planned_start" in data else o.planned_start
    ne = data["planned_end"] if "planned_end" in data else o.planned_end
    if ne <= ns:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "После обновления planned_end должен быть позже planned_start.",
            },
        )
    for k, v in data.items():
        setattr(o, k, v)
    try:
        db.commit()
        db.refresh(o)
    except Exception:
        db.rollback()
        raise
    return OrderResponse.model_validate(o)


@router.delete(
    "/{order_id}",
    status_code=204,
    summary="Удалить заказ",
    description="Запрещено, если есть сохранённые Operation: сначала пересчитайте расписание (POST /api/schedule).",
)
def delete_order(order_id: int, db: Session = Depends(get_db)) -> None:
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o:
        raise not_found("Заказ", order_id)
    if db.query(Operation).filter(Operation.order_id == order_id).first():
        raise conflict(
            "Нельзя удалить заказ: есть сохранённое расписание (Operation). "
            "Удаление операций выполняется только при пересчёте POST /api/schedule.",
            code="ORDER_HAS_OPERATIONS",
        )
    try:
        db.delete(o)
        db.commit()
    except Exception:
        db.rollback()
        raise
