"""
Статусы жизненного цикла заказа (MVP).

**Участие в POST /api/schedule:** в расчёт жадного планировщика попадают только заказы
со статусом ``scheduled`` (приняты к планированию).

**``in_progress`` (MVP):** повторно не планируются — исключаются из выборки так же,
как ``completed`` / ``cancelled`` / ``draft``, чтобы не пересчитывать уже запущенное
производство без явного возврата в ``scheduled`` через PATCH.

Терминальные статусы: ``completed``, ``cancelled`` — из них нельзя перейти в другой
статус через API (ошибка валидации 422).
"""
from __future__ import annotations

from enum import Enum


class OrderStatus(str, Enum):
    """Строковые значения хранятся в БД и в JSON API."""

    draft = "draft"
    scheduled = "scheduled"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


# Значения для CHECK в SQL и для сравнения без импорта Enum в миграциях.
ORDER_STATUS_DB_VALUES: tuple[str, ...] = tuple(s.value for s in OrderStatus)


def statuses_eligible_for_planning() -> frozenset[str]:
    """Статусы заказов, передаваемые в ``greedy_planner`` и в предпроверку данных."""
    return frozenset({OrderStatus.scheduled.value})


def is_terminal_order_status(value: str) -> bool:
    return value in (OrderStatus.completed.value, OrderStatus.cancelled.value)


def human_reason_excluded_from_planning(status: str) -> str:
    """Текст для ``excluded_orders.reason`` при отборе по статусу (POST /api/schedule)."""
    if status == OrderStatus.draft.value:
        return (
            "Заказ в статусе «draft» (черновик) не участвует в планировании. "
            "Переведите заказ в «scheduled», чтобы допустить его к расчёту расписания."
        )
    if status == OrderStatus.in_progress.value:
        return (
            "Заказ в статусе «in_progress» в MVP не планируется повторно. "
            "Верните статус «scheduled», если нужен пересчёт в общем прогоне POST /api/schedule."
        )
    if status == OrderStatus.completed.value:
        return "Заказ завершён (completed) и не участвует в расчёте расписания."
    if status == OrderStatus.cancelled.value:
        return "Заказ отменён (cancelled) и не участвует в расчёте расписания."
    return f"Заказ в статусе «{status}» не допущен к планированию в этом прогоне."


def reset_orders_to_scheduled(db: object) -> tuple[int, list[dict[str, str | int]]]:
    """
    Переводит все заказы в ``scheduled``, где переход допустим.
    Возвращает (число обновлённых, список пропущенных с причиной).
    """
    from backend.models import Order

    target = OrderStatus.scheduled.value
    updated = 0
    skipped: list[dict[str, str | int]] = []
    orders = db.query(Order).order_by(Order.id).all()
    for o in orders:
        current = str(o.status)
        if current == target:
            continue
        try:
            assert_order_status_transition_allowed(current, target)
        except ValueError as e:
            skipped.append(
                {
                    "order_id": o.id,
                    "order_name": o.name,
                    "previous_status": current,
                    "reason": str(e),
                }
            )
            continue
        o.status = target
        updated += 1
    if updated:
        db.flush()
    return updated, skipped


def promote_included_orders_to_in_progress(db: object, order_ids: set[int]) -> int:
    """
    После успешного планирования: заказы, полностью вошедшие в расписание,
    переводятся в ``in_progress``. Возвращает число обновлённых строк.
    """
    if not order_ids:
        return 0
    from backend.models import Order

    return (
        db.query(Order)
        .filter(Order.id.in_(order_ids))
        .filter(Order.status == OrderStatus.scheduled.value)
        .update({Order.status: OrderStatus.in_progress.value}, synchronize_session=False)
    )


def assert_order_status_transition_allowed(current: str, new: str) -> None:
    """
    Проверка PATCH: допустимые переходы (MVP).

    Из ``completed`` и ``cancelled`` — никуда (даже в то же значение при смене других
    полей статус можно не передавать; явная смена запрещена).
    """
    if current == new:
        return
    if is_terminal_order_status(current):
        raise ValueError(
            f"Из статуса «{current}» переход запрещён: заказ завершён или отменён и не меняется через API."
        )
    allowed_from: dict[str, frozenset[str]] = {
        OrderStatus.draft.value: frozenset(
            {OrderStatus.scheduled.value, OrderStatus.cancelled.value}
        ),
        OrderStatus.scheduled.value: frozenset(
            {
                OrderStatus.draft.value,
                OrderStatus.in_progress.value,
                OrderStatus.completed.value,
                OrderStatus.cancelled.value,
            }
        ),
        OrderStatus.in_progress.value: frozenset(
            {
                OrderStatus.scheduled.value,
                OrderStatus.completed.value,
                OrderStatus.cancelled.value,
            }
        ),
    }
    ok = allowed_from.get(current, frozenset())
    if new not in ok:
        raise ValueError(
            f"Недопустимый переход статуса заказа: «{current}» → «{new}». "
            f"Допустимо: {', '.join(sorted(ok)) if ok else 'нет'}."
        )
