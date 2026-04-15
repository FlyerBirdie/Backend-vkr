"""
Общий календарь смены участка (MVP): пн–пт, 08:00–17:00 по местному времени APP_TIMEZONE,
перерыв 12:00–13:00. Оборудование в MVP следует тому же календарю, что и люди.

Интервалы возвращаются в UTC; на входе period_start/period_end — timezone-aware
(наивные datetime не допускаются — см. assert).

Операция длиннее максимального непрерывного куска (4 ч: 08–12 или 13–17) в текущей
версии не разбивается на части по перерыву — планировщик не сможет её разместить
(ограничение MVP, см. также backend/planner.py).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from backend.time_settings import get_app_zoneinfo


def _require_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("work_calendar: datetime должен быть timezone-aware (не используйте наивные моменты).")
    return dt.astimezone(timezone.utc)


def work_intervals_utc(period_start: datetime, period_end: datetime) -> list[tuple[datetime, datetime]]:
    """
    Список непересекающихся интервалов (start, end) в UTC — рабочие куски,
    обрезанные пересечением с плановым периодом (как в планировщике: операция может
    заканчиваться не позже period_end; кусок добавляется, если после обрезки start < end).

    Пн–пт по календарю зоны участка; внутри дня: 08:00–12:00 и 13:00–17:00 локально;
    выходные дают пустой вклад за эти сутки.
    """
    ps = _require_aware_utc(period_start)
    pe = _require_aware_utc(period_end)
    if ps >= pe:
        return []

    tz = get_app_zoneinfo()
    out: list[tuple[datetime, datetime]] = []

    start_local = ps.astimezone(tz)
    end_local = pe.astimezone(tz)
    day = start_local.date()
    last_day = end_local.date()

    while day <= last_day:
        if day.weekday() < 5:
            morning_start = datetime.combine(day, time(8, 0), tzinfo=tz)
            morning_end = datetime.combine(day, time(12, 0), tzinfo=tz)
            afternoon_start = datetime.combine(day, time(13, 0), tzinfo=tz)
            afternoon_end = datetime.combine(day, time(17, 0), tzinfo=tz)
            for local_s, local_e in (
                (morning_start, morning_end),
                (afternoon_start, afternoon_end),
            ):
                u_s = local_s.astimezone(timezone.utc)
                u_e = local_e.astimezone(timezone.utc)
                clip_s = max(u_s, ps)
                clip_e = min(u_e, pe)
                if clip_s < clip_e:
                    out.append((clip_s, clip_e))
        day += timedelta(days=1)

    return out


def clip_intervals_to_window(
    intervals: list[tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
) -> list[tuple[datetime, datetime]]:
    """Пересечение каждого куска календаря с [window_start, window_end] (моменты UTC)."""
    ws = _require_aware_utc(window_start)
    we = _require_aware_utc(window_end)
    if ws >= we:
        return []
    clipped: list[tuple[datetime, datetime]] = []
    for u_s, u_e in intervals:
        clip_s = max(u_s, ws)
        clip_e = min(u_e, we)
        if clip_s < clip_e:
            clipped.append((clip_s, clip_e))
    return clipped


def total_available_work_minutes(period_start: datetime, period_end: datetime) -> int:
    """Суммарная длительность рабочих кусков в минутах (целое деление секунд), 0 если период пуст."""
    total = 0
    for u_s, u_e in work_intervals_utc(period_start, period_end):
        total += int((u_e - u_s).total_seconds() // 60)
    return total
