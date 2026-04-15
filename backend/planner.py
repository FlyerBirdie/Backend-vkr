"""
Жадный алгоритм планирования под доменные ограничения.

**Плановый период:** отбор заказов и размещение операций только в пересечении
глобального окна [period_start, period_end] (UTC) и окна заказа
[planned_start, planned_end]. Операции не начинаются раньше period_start и
заканчиваются не позже period_end (с учётом пересечения с окном заказа).

**Целевая функция (требование домена):** максимизация суммарной прибыли по полностью
включённым заказам. После расчёта явно проверяется, что сумма profit по включённым
заказам совпадает с суммой по списку запланированных операций (инвариант «всё или ничё»).

**MVP — жадный отбор:** заказы обрабатываются в порядке убывания прибыли, при равенстве —
по возрастанию id (детерминизм). Для каждого заказа операции ТП идут по sequence_number;
следующая операция не раньше окончания предыдущей. Эвристика не гарантирует глобальный
оптимум по прибыли.

**Опционально для v2:** полный перебор подмножеств заказов растёт как O(2^n); для точного
максимума прибыли при «всё или ничё» можно рассмотреть ILP/MILP, branch-and-bound или
динамику по узким классам входов — вынесено за рамки текущего жадного MVP.

Ресурсы: у одного worker_id и у одной equipment_id интервалы операций не пересекаются
(граница «конец = начало» следующей допустима).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TypedDict

from backend.models import Equipment, Order, Task, Worker

# Коды исключения заказа из расписания (машиночитаемые, стабильные).
EXCLUDED_OUTSIDE_PERIOD = "SCHEDULE_EXCLUDED_OUTSIDE_PERIOD"
"""Окно заказа не пересекается с плановым периодом (или вырожденное пересечение)."""

EXCLUDED_NO_PAIR = "SCHEDULE_EXCLUDED_NO_PAIR"
"""Для операции нет допустимой пары «рабочий (профессия) + оборудование (модель)»."""

EXCLUDED_TIME_CONFLICT = "SCHEDULE_EXCLUDED_TIME_CONFLICT"
"""Пары ресурсов есть, но не удаётся разместить операцию без пересечения по времени
в допустимом окне (конфликт по времени / исчерпание слотов в пределах периода)."""


class PlannedOperation(TypedDict):
    """Результат планирования одной операции."""
    order_id: int
    task_id: int
    worker_id: int
    equipment_id: int
    start_time: datetime
    end_time: datetime


@dataclass(frozen=True)
class PlannerExclusion:
    """Заказ, не вошедший в расписание (принцип «всё или ничё»)."""
    order_id: int
    order_name: str
    reason: str
    code: str


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _decimal_profit(order: Order) -> Decimal:
    p = order.profit
    if isinstance(p, Decimal):
        return p
    return Decimal(str(p))


def _order_sort_key(order: Order) -> tuple[Decimal, int]:
    """Убывание прибыли, затем возрастание id — детерминированный порядок."""
    return (-_decimal_profit(order), order.id)


def order_sort_key_for_planner(order: Order) -> tuple[Decimal, int]:
    """
    Публичный ключ той же сортировки, что и в greedy_planner (прибыль ↓, id ↑).
    Используйте для отображения включённых заказов в том же порядке, что и отбор.
    """
    return _order_sort_key(order)


def default_planning_period() -> tuple[datetime, datetime]:
    """
    Период планирования по умолчанию для демо и запросов без явных дат:
    с 00:00 UTC текущих суток на 14 суток вперёд (конец — верхняя граница для последней операции).
    """
    now = datetime.now(timezone.utc)
    period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    period_end = period_start + timedelta(days=14)
    return period_start, period_end


def _sorted_tasks(order: Order) -> list[Task]:
    """Задачи заказа по возрастанию sequence_number."""
    return sorted(order.tech_process.tasks, key=lambda t: t.sequence_number)


def _find_earliest_slot(
    duration_minutes: int,
    from_time: datetime,
    worker_busy: list[tuple[datetime, datetime]],
    equipment_busy: list[tuple[datetime, datetime]],
    not_after_end: datetime,
) -> datetime | None:
    """
    Ближайший старт, при котором рабочий и оборудование свободны на duration_minutes,
    начиная не раньше from_time, окончание не позже not_after_end.
    """
    slot_start = from_time
    delta = timedelta(minutes=duration_minutes)
    if slot_start + delta > not_after_end:
        return None

    def is_free(
        start: datetime,
        busy: list[tuple[datetime, datetime]],
    ) -> bool:
        slot_end = start + delta
        for b_start, b_end in busy:
            if start < b_end and slot_end > b_start:
                return False
        return True

    max_iter = 10000
    while max_iter > 0:
        if slot_start + delta > not_after_end:
            return None
        if is_free(slot_start, worker_busy) and is_free(slot_start, equipment_busy):
            return slot_start
        next_candidate = slot_start
        for b_start, b_end in worker_busy + equipment_busy:
            if b_end > slot_start and (next_candidate == slot_start or b_end < next_candidate):
                next_candidate = b_end
        if next_candidate == slot_start:
            break
        slot_start = next_candidate
        max_iter -= 1
    return None


def total_profit_of_included_orders(
    planned: list[PlannedOperation],
    orders_by_id: dict[int, Order],
) -> Decimal:
    """
    Целевая метрика: сумма profit по заказам, полностью представленным в planned
    (каждый order_id один раз; соответствует «всё или ничё» при полном ТП).
    """
    included_ids = {p["order_id"] for p in planned}
    return sum((_decimal_profit(orders_by_id[oid]) for oid in included_ids), Decimal("0"))


def _verify_no_resource_overlaps(planned: list[PlannedOperation]) -> None:
    """Интервалы одного worker_id / одного equipment_id не пересекаются (стык конец=начало допустим)."""
    from collections import defaultdict

    by_w: dict[int, list[tuple[datetime, datetime]]] = defaultdict(list)
    by_e: dict[int, list[tuple[datetime, datetime]]] = defaultdict(list)
    for p in planned:
        by_w[p["worker_id"]].append((p["start_time"], p["end_time"]))
        by_e[p["equipment_id"]].append((p["start_time"], p["end_time"]))

    def check(intervals: list[tuple[datetime, datetime]], label: str, rid: int) -> None:
        iv = sorted(intervals, key=lambda x: x[0])
        for i in range(len(iv) - 1):
            if iv[i][1] > iv[i + 1][0]:
                raise RuntimeError(
                    f"planner: пересечение интервалов {label} id={rid}: {iv[i]} и {iv[i + 1]}"
                )

    for wid, ivs in by_w.items():
        check(ivs, "worker", wid)
    for eid, ivs in by_e.items():
        check(ivs, "equipment", eid)


def _verify_intra_order_sequence(planned: list[PlannedOperation], orders_by_id: dict[int, Order]) -> None:
    """Операции одного заказа по возрастанию sequence_number; следующая не раньше конца предыдущей."""
    from collections import defaultdict

    by_order: dict[int, list[PlannedOperation]] = defaultdict(list)
    for p in planned:
        by_order[p["order_id"]].append(p)

    for oid, ops in by_order.items():
        order = orders_by_id[oid]
        tid_to_seq = {t.id: t.sequence_number for t in order.tech_process.tasks}
        ordered = sorted(ops, key=lambda x: tid_to_seq[x["task_id"]])
        prev_end: datetime | None = None
        for op in ordered:
            if prev_end is not None and op["start_time"] < prev_end:
                raise RuntimeError(
                    f"planner: заказ {oid}: операция task_id={op['task_id']} начинается раньше окончания предыдущей."
                )
            prev_end = op["end_time"]


def greedy_planner(
    orders: list[Order],
    workers: list[Worker],
    equipment: list[Equipment],
    period_start: datetime,
    period_end: datetime,
) -> tuple[list[PlannedOperation], list[PlannerExclusion]]:
    """
    Жадный планировщик: заказы в порядке (-profit, id), операции по sequence_number,
    выбор ближайшего допустимого слота; при равном времени старта — меньший worker_id,
    затем equipment_id (детерминизм).

    Возвращает запланированные операции и список исключённых заказов с кодами причин.
    """
    ps = _ensure_utc(period_start)
    pe = _ensure_utc(period_end)

    sorted_orders = sorted(orders, key=_order_sort_key)

    worker_busy: dict[int, list[tuple[datetime, datetime]]] = {w.id: [] for w in workers}
    equipment_busy: dict[int, list[tuple[datetime, datetime]]] = {e.id: [] for e in equipment}

    workers_by_profession: dict[str, list[Worker]] = {}
    for w in sorted(workers, key=lambda x: x.id):
        workers_by_profession.setdefault(w.profession, []).append(w)
    equipment_by_model: dict[str, list[Equipment]] = {}
    for e in sorted(equipment, key=lambda x: x.id):
        equipment_by_model.setdefault(e.model, []).append(e)

    result: list[PlannedOperation] = []
    exclusions: list[PlannerExclusion] = []

    eligible: list[Order] = []
    for order in sorted_orders:
        o_start = _ensure_utc(order.planned_start)
        o_end = _ensure_utc(order.planned_end)
        window_start = max(ps, o_start)
        window_end = min(pe, o_end)
        if window_start >= window_end:
            exclusions.append(
                PlannerExclusion(
                    order_id=order.id,
                    order_name=order.name,
                    reason=(
                        "Заказ не укладывается в плановый период: пересечение "
                        "[period_start, period_end] с окном заказа пусто или вырождено."
                    ),
                    code=EXCLUDED_OUTSIDE_PERIOD,
                )
            )
            continue
        eligible.append(order)

    orders_by_id = {o.id: o for o in orders}

    for order in eligible:
        o_start = _ensure_utc(order.planned_start)
        o_end = _ensure_utc(order.planned_end)
        window_start = max(ps, o_start)
        window_end = min(pe, o_end)

        op_start = window_start
        tasks = _sorted_tasks(order)
        order_planned = True
        fail_reason = (
            "Не удалось разместить операцию в допустимом окне: конфликт по времени "
            "после исчерпания доступных слотов (ресурсы заняты в пределах периода)."
        )
        fail_code = EXCLUDED_TIME_CONFLICT

        for task in tasks:
            prof = task.profession
            mod = task.equipment_model
            cand_workers = workers_by_profession.get(prof, [])
            cand_equipment = equipment_by_model.get(mod, [])

            if not cand_workers or not cand_equipment:
                task_label = task.name or f"операция #{task.sequence_number}"
                order_planned = False
                if not cand_workers and not cand_equipment:
                    detail = "нет ни исполнителя с нужной профессией, ни оборудования с нужной моделью"
                elif not cand_workers:
                    detail = f"нет исполнителя с профессией «{prof}»"
                else:
                    detail = f"нет оборудования с моделью «{mod}»"
                fail_reason = (
                    f"Для операции «{task_label}» не найдена допустимая пара «рабочий + оборудование»: {detail}."
                )
                fail_code = EXCLUDED_NO_PAIR
                break

            best_start: datetime | None = None
            best_worker: Worker | None = None
            best_equip: Equipment | None = None

            for w in cand_workers:
                for e in cand_equipment:
                    slot = _find_earliest_slot(
                        task.duration_minutes,
                        op_start,
                        worker_busy[w.id],
                        equipment_busy[e.id],
                        window_end,
                    )
                    if slot is None:
                        continue
                    end_t = slot + timedelta(minutes=task.duration_minutes)
                    if end_t > window_end:
                        continue
                    cand_key = (slot, w.id, e.id)
                    if best_start is None:
                        best_start = slot
                        best_worker = w
                        best_equip = e
                    else:
                        assert best_worker is not None and best_equip is not None
                        best_key = (best_start, best_worker.id, best_equip.id)
                        if cand_key < best_key:
                            best_start = slot
                            best_worker = w
                            best_equip = e

            if best_start is None or best_worker is None or best_equip is None:
                order_planned = False
                fail_reason = (
                    "Не удалось разместить операцию в допустимом окне: конфликт по времени "
                    "после исчерпания слотов (все допустимые пары worker+equipment заняты "
                    f"или не помещаются в период до {window_end.isoformat()})."
                )
                fail_code = EXCLUDED_TIME_CONFLICT
                break

            end_time = best_start + timedelta(minutes=task.duration_minutes)
            result.append(
                PlannedOperation(
                    order_id=order.id,
                    task_id=task.id,
                    worker_id=best_worker.id,
                    equipment_id=best_equip.id,
                    start_time=best_start,
                    end_time=end_time,
                )
            )
            worker_busy[best_worker.id].append((best_start, end_time))
            equipment_busy[best_equip.id].append((best_start, end_time))
            op_start = end_time

        if not order_planned:
            result = [r for r in result if r["order_id"] != order.id]
            worker_busy = {w.id: [] for w in workers}
            equipment_busy = {e.id: [] for e in equipment}
            for op in result:
                worker_busy[op["worker_id"]].append((op["start_time"], op["end_time"]))
                equipment_busy[op["equipment_id"]].append((op["start_time"], op["end_time"]))
            exclusions.append(
                PlannerExclusion(
                    order_id=order.id,
                    order_name=order.name,
                    reason=fail_reason,
                    code=fail_code,
                )
            )

    _verify_no_resource_overlaps(result)
    _verify_intra_order_sequence(result, orders_by_id)

    return result, exclusions
