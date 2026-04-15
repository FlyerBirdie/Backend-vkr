"""
Единая таймзона приложения (участок, календарь, пользовательские пояснения в API).

Внутри кода интервалы и расчёты — в UTC с явной конвертацией через zoneinfo.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from zoneinfo import ZoneInfo

load_dotenv()

DEFAULT_APP_TIMEZONE = "Europe/Samara"


def get_app_timezone_name() -> str:
    """IANA-имя зоны (по умолчанию Europe/Samara; переопределение APP_TIMEZONE в .env)."""
    raw = os.getenv("APP_TIMEZONE", DEFAULT_APP_TIMEZONE)
    name = (raw or "").strip()
    return name if name else DEFAULT_APP_TIMEZONE


def get_app_zoneinfo() -> ZoneInfo:
    return ZoneInfo(get_app_timezone_name())
