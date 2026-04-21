"""
Pytest: до импорта backend задаём SQLite in-memory (см. database.py StaticPool).
"""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SQL_ECHO", "false")
# JWT для интеграционных тестов API (до импорта backend.main)
os.environ["JWT_SECRET_KEY"] = "pytest-jwt-secret-key-32chars-min!!"
os.environ["PLANNER_USERNAME"] = "planner"
os.environ["PLANNER_PASSWORD"] = "testpass"
os.environ.pop("PLANNER_PASSWORD_HASH", None)

import pytest
from sqlalchemy.orm import Session

from backend.database import Base, SessionLocal, engine


@pytest.fixture
def db_session() -> Session:
    # Сброс схемы: тот же engine, что у TestClient(app), может уже содержать демо после startup.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
