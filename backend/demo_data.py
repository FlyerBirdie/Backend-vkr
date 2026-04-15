"""
Демо-данные: заказы, технологические процессы, операции, рабочие, оборудование.
Генерируются только при пустых таблицах.

Окна заказов (planned_start/planned_end) заданы широко в UTC, чтобы пересекаться
с периодом по умолчанию POST /api/schedule (полночь—+14 дней по календарю Europe/Samara,
см. default_planning_period) и давать ненулевое расписание при типичном запуске.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.models import Equipment, Order, Task, TechProcess, Worker

# Единое демо-окно: весь календарный год (UTC), внутри него укладывается период по умолчанию.
_DEMO_WINDOW_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_DEMO_WINDOW_END = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

# (название ТП, список (имя операции, минуты, профессия, модель оборудования))
_TECH_PROCESS_SPECS: list[tuple[str, list[tuple[str, int, str, str]]]] = [
    (
        "Шкаф распределительный",
        [
            ("Резка", 60, "слесарь", "лазерный станок"),
            ("Гибка", 45, "слесарь", "гибочный пресс"),
            ("Сварка", 90, "сварщик", "сварочный аппарат"),
            ("Покраска", 30, "маляр", "камера покраски"),
        ],
    ),
    (
        "Панель управления",
        [
            ("Резка", 40, "слесарь", "лазерный станок"),
            ("Гибка", 30, "слесарь", "гибочный пресс"),
            ("Сварка", 60, "сварщик", "сварочный аппарат"),
            ("Покраска", 25, "маляр", "камера покраски"),
        ],
    ),
    (
        "Лоток кабельный",
        [
            ("Резка", 35, "слесарь", "лазерный станок"),
            ("Гибка", 28, "слесарь", "гибочный пресс"),
            ("Сварка", 55, "сварщик", "сварочный аппарат"),
            ("Покраска", 22, "маляр", "камера покраски"),
        ],
    ),
    (
        "Стойка монтажная",
        [
            ("Резка", 50, "слесарь", "лазерный станок"),
            ("Гибка", 40, "слесарь", "гибочный пресс"),
            ("Сварка", 70, "сварщик", "сварочный аппарат"),
            ("Покраска", 28, "маляр", "камера покраски"),
        ],
    ),
    (
        "Кожух защитный",
        [
            ("Резка", 45, "слесарь", "лазерный станок"),
            ("Гибка", 35, "слесарь", "гибочный пресс"),
            ("Сварка", 50, "сварщик", "сварочный аппарат"),
            ("Покраска", 20, "маляр", "камера покраски"),
        ],
    ),
    (
        "Бокс распределительный",
        [
            ("Резка", 55, "слесарь", "лазерный станок"),
            ("Гибка", 42, "слесарь", "гибочный пресс"),
            ("Сварка", 85, "сварщик", "сварочный аппарат"),
            ("Покраска", 32, "маляр", "камера покраски"),
        ],
    ),
]

_WORKERS: list[tuple[str, str]] = [
    ("Иванов И.И.", "слесарь"),
    ("Смирнов А.В.", "слесарь"),
    ("Кузнецов Д.Е.", "слесарь"),
    ("Волков М.С.", "слесарь"),
    ("Новиков П.Р.", "слесарь"),
    ("Петров П.П.", "сварщик"),
    ("Орлов В.К.", "сварщик"),
    ("Морозов Н.Т.", "сварщик"),
    ("Сидоров С.С.", "маляр"),
    ("Лебедев А.Ю.", "маляр"),
]

# Несколько единиц одной модели — параллельная загрузка в жадном планировщике.
_EQUIPMENT: list[tuple[str, str]] = [
    ("Станок Л-1", "лазерный станок"),
    ("Станок Л-2", "лазерный станок"),
    ("Пресс Г-1", "гибочный пресс"),
    ("Пресс Г-2", "гибочный пресс"),
    ("Аппарат СВА-1", "сварочный аппарат"),
    ("Аппарат СВА-2", "сварочный аппарат"),
    ("Камера КП-1", "камера покраски"),
    ("Камера КП-2", "камера покраски"),
]


def _build_order_specs(tp_ids: list[int]) -> list[tuple[str, Decimal, int]]:
    """
    Пул заказов: чередование ТП, убывающая прибыль для детерминированного жадного порядка,
    плюс «длинный хвост» мелких заказов.
    """
    out: list[tuple[str, Decimal, int]] = []
    n_tp = len(tp_ids)
    # Крупные и средние заказы (имена уникальны, прибыль 800…200)
    base_names = [
        "Шкаф А-100",
        "Панель ПУ-12",
        "Лоток ЛК-55",
        "Стойка СМ-7",
        "Кожух КЗ-3",
        "Бокс БР-9",
        "Шкаф А-101",
        "Панель ПУ-13",
        "Лоток ЛК-56",
        "Стойка СМ-8",
        "Кожух КЗ-4",
        "Бокс БР-10",
        "Шкаф А-102",
        "Панель ПУ-14",
        "Лоток ЛК-57",
        "Стойка СМ-9",
        "Кожух КЗ-5",
        "Бокс БР-11",
        "Шкаф А-103",
        "Панель ПУ-15",
        "Лоток ЛК-58",
        "Стойка СМ-10",
        "Кожух КЗ-6",
        "Бокс БР-12",
    ]
    profit_hi = Decimal("8200")
    step = Decimal("275")
    for i, name in enumerate(base_names):
        tp_id = tp_ids[i % n_tp]
        p = profit_hi - step * Decimal(i)
        out.append((f"Заказ {name}", p, tp_id))

    # Серийные мелкие заказы (ещё ~24 шт.)
    for batch, (prefix, profit_start, profit_step) in enumerate(
        [
            ("Серия М", Decimal("950"), Decimal("18")),
            ("Серия Н", Decimal("880"), Decimal("15")),
        ]
    ):
        for j in range(1, 13):
            idx = batch * 12 + j
            tp_id = tp_ids[(len(base_names) + idx) % n_tp]
            p = profit_start - profit_step * Decimal(j - 1)
            out.append((f"Заказ {prefix}-{j:02d}", p, tp_id))

    return out


def init_demo_data(db: Session) -> None:
    """Заполнить БД демо-данными, если таблицы пустые (без дублирования при перезапуске)."""
    if db.query(TechProcess).first() is not None:
        return

    tp_ids: list[int] = []
    for tp_name, tasks_spec in _TECH_PROCESS_SPECS:
        tp = TechProcess(name=tp_name)
        db.add(tp)
        db.flush()
        tp_ids.append(tp.id)
        for seq, (name, dur, prof, model) in enumerate(tasks_spec, start=1):
            db.add(
                Task(
                    tech_process_id=tp.id,
                    sequence_number=seq,
                    duration_minutes=dur,
                    profession=prof,
                    equipment_model=model,
                    name=name,
                )
            )

    db.flush()

    for name, profit, tp_id in _build_order_specs(tp_ids):
        db.add(
            Order(
                name=name,
                profit=profit,
                planned_start=_DEMO_WINDOW_START,
                planned_end=_DEMO_WINDOW_END,
                tech_process_id=tp_id,
            )
        )

    for name, profession in _WORKERS:
        db.add(Worker(name=name, profession=profession))

    for name, model in _EQUIPMENT:
        db.add(Equipment(name=name, model=model))

    db.commit()
