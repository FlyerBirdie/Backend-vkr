"""Юнит-тесты календаря участка (Europe/Samara, пн–пт, перерыв)."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from backend.work_calendar import total_available_work_minutes, work_intervals_utc

SAMARA = ZoneInfo("Europe/Samara")


def test_saturday_has_no_work_intervals() -> None:
    """Суббота целиком в периоде — рабочих кусков нет."""
    ps = datetime(2026, 4, 18, 0, 0, 0, tzinfo=SAMARA).astimezone(timezone.utc)
    pe = datetime(2026, 4, 19, 0, 0, 0, tzinfo=SAMARA).astimezone(timezone.utc)
    assert work_intervals_utc(ps, pe) == []
    assert total_available_work_minutes(ps, pe) == 0


def test_monday_full_shift_minutes() -> None:
    """Один понедельник: 4 ч + 4 ч = 480 минут доступности."""
    ps = datetime(2026, 4, 13, 0, 0, 0, tzinfo=SAMARA).astimezone(timezone.utc)
    pe = datetime(2026, 4, 14, 0, 0, 0, tzinfo=SAMARA).astimezone(timezone.utc)
    assert total_available_work_minutes(ps, pe) == 480


def test_naive_period_raises() -> None:
    from datetime import datetime as dt

    try:
        work_intervals_utc(dt(2026, 1, 1), dt(2026, 1, 2))
    except ValueError as e:
        msg = str(e).lower()
        assert "timezone-aware" in msg or "наив" in msg
    else:
        raise AssertionError("expected ValueError")
