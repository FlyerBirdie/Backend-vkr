"""
Проверки данных перед планированием: ТП, задачи, соответствие Worker/Equipment.
Коды issue — стабильные строки для клиентов и отчётов.

Последовательность операций (sequence_number): требуются уникальные положительные номера;
необязательная непрерывность с 1 — пропуски в нумерации допустимы (MVP), при обнаружении
пропуска выдаётся предупреждение TASK_SEQUENCE_HAS_GAPS.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from backend.models import Equipment, Order, Task, TechProcess, Worker
from backend.planner import PlannedOperation


IssueLevel = Literal["error", "warning"]


@dataclass(frozen=True)
class PlanningIssue:
    """Машиночитаемая запись о проблеме или предупреждении."""

    level: IssueLevel
    code: str
    message: str
    tech_process_id: int | None = None
    tech_process_name: str | None = None
    task_id: int | None = None
    order_id: int | None = None
    order_name: str | None = None


@dataclass
class PlanningValidationResult:
    """Итог проверки: блокирующие ошибки и предупреждения."""

    errors: list[PlanningIssue] = field(default_factory=list)
    warnings: list[PlanningIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def _collect_tech_processes(orders: list[Order]) -> dict[int, TechProcess]:
    out: dict[int, TechProcess] = {}
    for o in orders:
        tp = o.tech_process
        if tp.id not in out:
            out[tp.id] = tp
    return out


def _task_label(task: Task) -> str:
    return task.name or f"операция seq={task.sequence_number}"


def validate_planning_inputs(
    orders: list[Order],
    workers: list[Worker],
    equipment: list[Equipment],
    period_start: datetime,
    period_end: datetime,
) -> PlanningValidationResult:
    """
    Проверка данных из БД перед вызовом планировщика.

    Блокирует расчёт при: пустом ТП, некорректных полях задач, отсутствии рабочего
    или оборудования под профессию/модель, некорректном окне заказа или периода.
    """
    result = PlanningValidationResult()

    profs = {w.profession for w in workers}
    models = {e.model for e in equipment}

    if period_end <= period_start:
        result.errors.append(
            PlanningIssue(
                level="error",
                code="PERIOD_INVALID",
                message="Плановый период некорректен: period_end должен быть позже period_start.",
            )
        )

    for order in orders:
        ps, pe = order.planned_start, order.planned_end
        if ps >= pe:
            result.errors.append(
                PlanningIssue(
                    level="error",
                    code="ORDER_WINDOW_INVALID",
                    message=f"Заказ «{order.name}»: planned_start должен быть раньше planned_end.",
                    order_id=order.id,
                    order_name=order.name,
                )
            )

    tech_processes = _collect_tech_processes(orders)

    for tp in tech_processes.values():
        tasks = list(tp.tasks)
        if not tasks:
            result.errors.append(
                PlanningIssue(
                    level="error",
                    code="TECH_PROCESS_EMPTY",
                    message=f"Техпроцесс «{tp.name}» (id={tp.id}) не содержит операций.",
                    tech_process_id=tp.id,
                    tech_process_name=tp.name,
                )
            )
            continue

        by_seq: dict[int, list[Task]] = {}
        for t in tasks:
            by_seq.setdefault(t.sequence_number, []).append(t)

        for seq, group in sorted(by_seq.items()):
            if len(group) > 1:
                ids = ", ".join(str(x.id) for x in group)
                result.errors.append(
                    PlanningIssue(
                        level="error",
                        code="TASK_SEQUENCE_DUPLICATE",
                        message=(
                            f"В ТП «{tp.name}» дублируется sequence_number={seq} "
                            f"(задачи: {ids})."
                        ),
                        tech_process_id=tp.id,
                        tech_process_name=tp.name,
                        task_id=group[0].id,
                    )
                )

        sorted_tasks = sorted(tasks, key=lambda x: x.sequence_number)
        seqs = [t.sequence_number for t in sorted_tasks]
        if any(s <= 0 for s in seqs):
            bad = next(t for t in sorted_tasks if t.sequence_number <= 0)
            result.errors.append(
                PlanningIssue(
                    level="error",
                    code="TASK_SEQUENCE_NON_POSITIVE",
                    message=(
                        f"В ТП «{tp.name}» у задачи «{_task_label(bad)}» "
                        f"sequence_number должен быть положительным."
                    ),
                    tech_process_id=tp.id,
                    tech_process_name=tp.name,
                    task_id=bad.id,
                )
            )

        # Пропуски в нумерации (1, 3, 5) допустимы в MVP; при наличии пропуска — одно предупреждение.
        unique_seq = sorted(set(seqs))
        if len(unique_seq) >= 2 and len(unique_seq) == len(seqs):
            for i in range(len(unique_seq) - 1):
                if unique_seq[i + 1] != unique_seq[i] + 1:
                    result.warnings.append(
                        PlanningIssue(
                            level="warning",
                            code="TASK_SEQUENCE_HAS_GAPS",
                            message=(
                                f"ТП «{tp.name}»: нумерация sequence_number не непрерывна "
                                f"(допустимы пропуски в MVP; порядок задаётся сортировкой по номеру)."
                            ),
                            tech_process_id=tp.id,
                            tech_process_name=tp.name,
                        )
                    )
                    break

        for task in tasks:
            if task.duration_minutes is None or task.duration_minutes <= 0:
                result.errors.append(
                    PlanningIssue(
                        level="error",
                        code="TASK_INVALID_DURATION",
                        message=(
                            f"ТП «{tp.name}», «{_task_label(task)}»: "
                            f"задайте duration_minutes > 0."
                        ),
                        tech_process_id=tp.id,
                        tech_process_name=tp.name,
                        task_id=task.id,
                    )
                )
            prof = (task.profession or "").strip()
            if not prof:
                result.errors.append(
                    PlanningIssue(
                        level="error",
                        code="TASK_MISSING_PROFESSION",
                        message=f"ТП «{tp.name}», «{_task_label(task)}»: не задана профессия.",
                        tech_process_id=tp.id,
                        tech_process_name=tp.name,
                        task_id=task.id,
                    )
                )
            elif prof not in profs:
                result.errors.append(
                    PlanningIssue(
                        level="error",
                        code="TASK_NO_MATCHING_WORKER",
                        message=(
                            f"ТП «{tp.name}», «{_task_label(task)}»: нет ни одного Worker "
                            f"с профессией «{prof}»."
                        ),
                        tech_process_id=tp.id,
                        tech_process_name=tp.name,
                        task_id=task.id,
                    )
                )

            mod = (task.equipment_model or "").strip()
            if not mod:
                result.errors.append(
                    PlanningIssue(
                        level="error",
                        code="TASK_MISSING_EQUIPMENT_MODEL",
                        message=(
                            f"ТП «{tp.name}», «{_task_label(task)}»: "
                            f"не задана модель оборудования (equipment_model)."
                        ),
                        tech_process_id=tp.id,
                        tech_process_name=tp.name,
                        task_id=task.id,
                    )
                )
            elif mod not in models:
                result.errors.append(
                    PlanningIssue(
                        level="error",
                        code="TASK_NO_MATCHING_EQUIPMENT",
                        message=(
                            f"ТП «{tp.name}», «{_task_label(task)}»: нет Equipment "
                            f"с model «{mod}»."
                        ),
                        tech_process_id=tp.id,
                        tech_process_name=tp.name,
                        task_id=task.id,
                    )
                )

    return result


def planning_issue_to_api_dict(issue: PlanningIssue) -> dict:
    """Сериализация в поля ScheduleIssueItem."""
    return {
        "level": issue.level,
        "code": issue.code,
        "message": issue.message,
        "tech_process_id": issue.tech_process_id,
        "tech_process_name": issue.tech_process_name,
        "task_id": issue.task_id,
        "order_id": issue.order_id,
        "order_name": issue.order_name,
    }


def build_schedule_report_summary(
    *,
    period_start: datetime,
    period_end: datetime,
    validation_warning_count: int,
    included_count: int,
    excluded_count: int,
    total_profit: Decimal,
) -> str:
    """Краткий отчёт после успешного расчёта (HTTP 200)."""
    tp = total_profit if isinstance(total_profit, Decimal) else Decimal(str(total_profit))
    lines = [
        f"Период планирования (UTC): {period_start.isoformat()} — {period_end.isoformat()}.",
        f"Заказов включено в расписание: {included_count}; исключено целиком: {excluded_count}.",
        f"Суммарная прибыль по включённым заказам: {tp}.",
    ]
    if validation_warning_count:
        lines.append(
            f"Предупреждений при проверке ТП/задач (до расчёта): {validation_warning_count}. "
            "Подробности — в поле issues."
        )
    else:
        lines.append("Предупреждений при проверке данных перед расчётом нет.")
    lines.append("Исключённые заказы и коды причин — в полях excluded_orders и issues.")
    return "\n".join(lines)


def human_summary_for_validation(
    result: PlanningValidationResult,
    *,
    title: str = "Проверка данных перед планированием",
) -> str:
    """Краткий текст для отчёта (агент/пользователь)."""
    lines = [title + "."]
    if result.errors:
        lines.append(f"Ошибок: {len(result.errors)}.")
        for e in result.errors:
            lines.append(f"  [{e.code}] {e.message}")
    else:
        lines.append("Блокирующих ошибок нет.")
    if result.warnings:
        lines.append(f"Предупреждений: {len(result.warnings)}.")
        for w in result.warnings:
            lines.append(f"  [{w.code}] {w.message}")
    return "\n".join(lines)


def assert_planned_all_or_nothing(
    planned: list[PlannedOperation],
    orders_by_id: dict[int, Order],
) -> None:
    """
    Проверка инварианта: для каждого order_id в planned число операций равно числу задач ТП.
    Используется после планировщика; при нарушении — ошибка реализации.
    """
    by_order: dict[int, list] = defaultdict(list)
    for p in planned:
        by_order[p["order_id"]].append(p)

    for oid, ops in by_order.items():
        order = orders_by_id.get(oid)
        if not order:
            raise RuntimeError(f"assert_planned_all_or_nothing: неизвестный order_id={oid}")
        n_tasks = len(order.tech_process.tasks)
        if len(ops) != n_tasks:
            raise RuntimeError(
                f"assert_planned_all_or_nothing: заказ {oid} частично запланирован "
                f"({len(ops)} из {n_tasks})."
            )
