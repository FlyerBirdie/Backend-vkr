"""
Демо-данные: заказы, технологические процессы, операции, рабочие, оборудование.
Генерируются только при пустых таблицах.

Окна заказов (planned_start/planned_end) заданы широко в UTC, чтобы пересекаться
с периодом по умолчанию POST /api/schedule (см. default_planning_period в planner.py)
и давать ненулевое расписание при типичном запуске.
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.models import Equipment, Order, Task, TechProcess, Worker

# Единое демо-окно: весь календарный год (UTC), внутри него укладывается период по умолчанию.
_DEMO_WINDOW_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_DEMO_WINDOW_END = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def init_demo_data(db: Session) -> None:
    """Заполнить БД демо-данными, если таблицы пустые (без дублирования при перезапуске)."""
    if db.query(TechProcess).first() is not None:
        return

    # Технологические процессы и операции (4 операции: резка, гибка, сварка, покраска)
    tp1 = TechProcess(name="Шкаф распределительный")
    db.add(tp1)
    db.flush()

    for seq, (name, dur, prof, model) in enumerate(
        [
            ("Резка", 60, "слесарь", "лазерный станок"),
            ("Гибка", 45, "слесарь", "гибочный пресс"),
            ("Сварка", 90, "сварщик", "сварочный аппарат"),
            ("Покраска", 30, "маляр", "камера покраски"),
        ],
        start=1,
    ):
        t = Task(
            tech_process_id=tp1.id,
            sequence_number=seq,
            duration_minutes=dur,
            profession=prof,
            equipment_model=model,
            name=name,
        )
        db.add(t)

    tp2 = TechProcess(name="Панель управления")
    db.add(tp2)
    db.flush()

    for seq, (name, dur, prof, model) in enumerate(
        [
            ("Резка", 40, "слесарь", "лазерный станок"),
            ("Гибка", 30, "слесарь", "гибочный пресс"),
            ("Сварка", 60, "сварщик", "сварочный аппарат"),
            ("Покраска", 25, "маляр", "камера покраски"),
        ],
        start=1,
    ):
        t = Task(
            tech_process_id=tp2.id,
            sequence_number=seq,
            duration_minutes=dur,
            profession=prof,
            equipment_model=model,
            name=name,
        )
        db.add(t)

    db.flush()

    # 5 демо-заказов, прибыль 1000–5000; все в общем демо-окне (пересечение с периодом по умолчанию).
    for name, profit, tp_id in [
        ("Заказ Шкаф №1", 5000, tp1.id),
        ("Заказ Панель №1", 3500, tp2.id),
        ("Заказ Шкаф №2", 2200, tp1.id),
        ("Заказ Панель №2", 1800, tp2.id),
        ("Заказ Шкаф №3", 1000, tp1.id),
    ]:
        db.add(
            Order(
                name=name,
                profit=Decimal(str(profit)),
                planned_start=_DEMO_WINDOW_START,
                planned_end=_DEMO_WINDOW_END,
                tech_process_id=tp_id,
            )
        )

    # 3 рабочих
    for name, profession in [
        ("Иванов И.И.", "слесарь"),
        ("Петров П.П.", "сварщик"),
        ("Сидоров С.С.", "маляр"),
    ]:
        db.add(Worker(name=name, profession=profession))

    # 4 единицы оборудования
    for name, model in [
        ("Станок Л-1", "лазерный станок"),
        ("Пресс Г-1", "гибочный пресс"),
        ("Аппарат СВА-1", "сварочный аппарат"),
        ("Камера КП-1", "камера покраски"),
    ]:
        db.add(Equipment(name=name, model=model))

    db.commit()
