"""
Метрики загрузки ресурсов для POST /api/schedule (демо, ВКР).

Формула (MVP, упрощённо):
- T_avail — сумма минут пересечения общего календаря участка (пн–пт, окна 08–12 и 13–17
  по Europe/Samara, см. backend/work_calendar.py) с [period_start, period_end]; одинакова
  для каждого ресурса (люди и оборудование — один календарь).
- Для рабочего w: T_busy(w) = сумма (end_time − start_time) в минутах по всем операциям
  расписания с worker_id = w. Аналогично для единицы оборудования e по equipment_id.
- Загрузка ресурса: U = min(100, T_busy / T_avail * 100) при T_avail > 0; иначе 0.
- Простой (idle) в %: 100 − U (для отчёта об «узких местах» по низкой загрузке).

Агрегаты:
- Средняя загрузка по персоналу: среднее арифметическое U по всем Worker из БД на момент расчёта.
- Средняя загрузка по оборудованию: среднее U по всем Equipment из БД.
- «Ванна» по персоналу: pool_worker = min(100, Σ T_busy(w) / (N_workers · T_avail) · 100);
  аналогично pool_equipment (сумма минут занятости по всем станкам / (N_eq · T_avail) · 100).
  Сумма занятых минут по разным рабочим может превышать T_avail из‑за параллельной работы.

Узкие места (минимальная логика MVP):
- highest_load: до 3 ресурсов (workers ∪ equipment) с наибольшим U;
- highest_idle: до 3 ресурсов с наименьшим U (наибольший резерв / простой).

Рекомендации — строки-заглушки без ИИ, для демонстрации UI отчёта.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from backend.models import Equipment, Operation, Worker
from backend.work_calendar import total_available_work_minutes


def _duration_minutes(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 60.0


def period_available_minutes(period_start: datetime, period_end: datetime) -> int:
    """Доступный фонд минут по календарю участка внутри планового периода (не длина суток)."""
    return total_available_work_minutes(period_start, period_end)


@dataclass
class MetricsComputation:
    """Промежуточный результат для сборки Pydantic-ответа."""

    available_minutes: int
    worker_rows: list[dict]
    equipment_rows: list[dict]
    workers_avg: float
    equipment_avg: float
    total_busy_workers: float
    total_busy_equipment: float
    pool_worker_load_percent: float
    pool_equipment_load_percent: float
    highest_load: list[dict]
    highest_idle: list[dict]
    recommendations: list[str]


def compute_schedule_metrics(
    period_start: datetime,
    period_end: datetime,
    workers: list[Worker],
    equipment: list[Equipment],
    operations: list[Operation],
) -> MetricsComputation:
    """
    operations — запланированные операции текущего прогона (после commit), с join worker/equipment.
    """
    t_avail = period_available_minutes(period_start, period_end)
    if t_avail <= 0:
        return MetricsComputation(
            available_minutes=0,
            worker_rows=[],
            equipment_rows=[],
            workers_avg=0.0,
            equipment_avg=0.0,
            total_busy_workers=0.0,
            total_busy_equipment=0.0,
            pool_worker_load_percent=0.0,
            pool_equipment_load_percent=0.0,
            highest_load=[],
            highest_idle=[],
            recommendations=[
                "Плановый период нулевой длительности — скорректируйте period_start/period_end (заглушка отчёта)."
            ],
        )

    busy_w: dict[int, float] = defaultdict(float)
    busy_e: dict[int, float] = defaultdict(float)
    for op in operations:
        d = _duration_minutes(op.start_time, op.end_time)
        busy_w[op.worker_id] += d
        busy_e[op.equipment_id] += d

    worker_rows: list[dict] = []
    for w in sorted(workers, key=lambda x: x.id):
        b = busy_w.get(w.id, 0.0)
        u = min(100.0, (b / t_avail) * 100.0) if t_avail else 0.0
        worker_rows.append(
            {
                "id": w.id,
                "name": w.name,
                "detail": w.profession,
                "busy_minutes": round(b, 2),
                "available_minutes": t_avail,
                "utilization_percent": round(u, 2),
                "idle_percent": round(100.0 - u, 2),
            }
        )

    equipment_rows: list[dict] = []
    for e in sorted(equipment, key=lambda x: x.id):
        b = busy_e.get(e.id, 0.0)
        u = min(100.0, (b / t_avail) * 100.0) if t_avail else 0.0
        equipment_rows.append(
            {
                "id": e.id,
                "name": e.name,
                "detail": e.model,
                "busy_minutes": round(b, 2),
                "available_minutes": t_avail,
                "utilization_percent": round(u, 2),
                "idle_percent": round(100.0 - u, 2),
            }
        )

    workers_avg = (
        sum(r["utilization_percent"] for r in worker_rows) / len(worker_rows) if worker_rows else 0.0
    )
    equipment_avg = (
        sum(r["utilization_percent"] for r in equipment_rows) / len(equipment_rows)
        if equipment_rows
        else 0.0
    )
    total_busy_w = sum(busy_w.values())
    total_busy_e = sum(busy_e.values())
    n_w, n_e = len(workers), len(equipment)
    pool_w = min(100.0, (total_busy_w / (n_w * t_avail)) * 100.0) if n_w and t_avail else 0.0
    pool_e = min(100.0, (total_busy_e / (n_e * t_avail)) * 100.0) if n_e and t_avail else 0.0

    combined: list[dict] = []
    for r in worker_rows:
        combined.append(
            {
                "resource_kind": "worker",
                "id": r["id"],
                "name": r["name"],
                "utilization_percent": r["utilization_percent"],
            }
        )
    for r in equipment_rows:
        combined.append(
            {
                "resource_kind": "equipment",
                "id": r["id"],
                "name": r["name"],
                "utilization_percent": r["utilization_percent"],
            }
        )

    by_load = sorted(
        combined,
        key=lambda x: (-x["utilization_percent"], x["resource_kind"], x["id"]),
    )
    by_idle = sorted(
        combined,
        key=lambda x: (x["utilization_percent"], x["resource_kind"], x["id"]),
    )

    highest_load = [{**x, "role": "high_load"} for x in by_load[:3]]
    highest_idle = [{**x, "role": "high_idle"} for x in by_idle[:3]]

    recommendations = _stub_recommendations(worker_rows, equipment_rows, highest_load, highest_idle)

    return MetricsComputation(
        available_minutes=t_avail,
        worker_rows=worker_rows,
        equipment_rows=equipment_rows,
        workers_avg=round(workers_avg, 2),
        equipment_avg=round(equipment_avg, 2),
        total_busy_workers=round(total_busy_w, 2),
        total_busy_equipment=round(total_busy_e, 2),
        pool_worker_load_percent=round(pool_w, 2),
        pool_equipment_load_percent=round(pool_e, 2),
        highest_load=highest_load,
        highest_idle=highest_idle,
        recommendations=recommendations,
    )


def _stub_recommendations(
    _worker_rows: list[dict],
    _equipment_rows: list[dict],
    highest_load: list[dict],
    highest_idle: list[dict],
) -> list[str]:
    """Текстовые заглушки для блока рекомендаций (без ИИ)."""
    out: list[str] = []
    for item in highest_load[:2]:
        out.append(
            f"[Узкое место] Высокая загрузка ({item['utilization_percent']:.1f}%): "
            f"{item['resource_kind']} «{item['name']}» (id={item['id']}) — "
            f"проверьте перегрузку или сроки; при необходимости сдвиг заказов или доп. ресурс (заглушка отчёта)."
        )
    for item in highest_idle[:2]:
        if item["utilization_percent"] < 25.0:
            out.append(
                f"[Резерв] Низкая загрузка ({item['utilization_percent']:.1f}%): "
                f"{item['resource_kind']} «{item['name']}» — потенциальный резерв мощности (заглушка отчёта)."
            )
    if not out:
        out.append(
            "Сводка: выраженных узких мест по загрузке нет; при необходимости уточните период или состав заказов (заглушка отчёта)."
        )
    return out
