"""
Настройка подключения к PostgreSQL через SQLAlchemy (для pytest — SQLite в памяти).
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://localhost/production_planning",
)

_engine_kwargs: dict = {}
if DATABASE_URL.startswith("sqlite"):
    # Общий in-memory каталог для всех соединений (тесты).
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    _engine_kwargs["poolclass"] = StaticPool

SQL_ECHO = os.getenv("SQL_ECHO", "false").lower() in ("1", "true", "yes")

engine = create_engine(DATABASE_URL, echo=SQL_ECHO, **_engine_kwargs)


@event.listens_for(engine, "connect")
def _on_connect(dbapi_connection, _connection_record) -> None:
    """PostgreSQL: UTC. SQLite: внешние ключи и без SET TIME ZONE."""
    if engine.dialect.name == "sqlite":
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
        return
    cur = dbapi_connection.cursor()
    cur.execute("SET TIME ZONE 'UTC'")
    cur.close()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Генератор сессии БД для FastAPI Depends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
