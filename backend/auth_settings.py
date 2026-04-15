"""Переменные окружения для JWT и учётной записи планировщика."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
PLANNER_USERNAME: str = os.getenv("PLANNER_USERNAME", "planner")
# В продакшене задайте PLANNER_PASSWORD_HASH (bcrypt); PLANNER_PASSWORD — только для локальной разработки.
PLANNER_PASSWORD: str = os.getenv("PLANNER_PASSWORD", "")
PLANNER_PASSWORD_HASH: str = os.getenv("PLANNER_PASSWORD_HASH", "").strip()

JWT_ALGORITHM = "HS256"
ROLE_PLANNER = "planner"
