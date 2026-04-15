# Backend: оперативное планирование производства

Стек: Python 3, FastAPI, SQLAlchemy 2, PostgreSQL, Pydantic v2.

## Быстрый старт

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # задать DATABASE_URL и при необходимости CORS_ORIGINS
```

Запуск API:

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Документация OpenAPI: `http://127.0.0.1:8000/docs`

### REST API (MVP)

Под префиксом `/api`: справочники `workers`, `equipment`, `tech-processes` и задачи `tasks/{id}`, заказы `orders`, read-only `operations`, пересчёт `POST /schedule`. Подробности и схемы тел запросов — в `/docs`.

**Аутентификация:** `POST /api/auth/login` (тело `username`, `password`) → JWT. Остальные перечисленные маршруты требуют заголовок `Authorization: Bearer <token>`. Публично также `GET /api/health`. Переменные: `JWT_SECRET_KEY`, `JWT_EXPIRE_MINUTES`, `PLANNER_USERNAME`, `PLANNER_PASSWORD_HASH` (или `PLANNER_PASSWORD` только для dev) — см. `.env.example`.

## Переменные окружения

См. `.env.example`: строка подключения к PostgreSQL (`DATABASE_URL`), CORS для локального фронта (`CORS_ORIGINS`), опционально `SQL_ECHO`.

## Тесты

```bash
pytest
```

Тесты используют SQLite в памяти (не требуют запущенного PostgreSQL).

## Миграции схемы БД

В репозитории пока нет Alembic/Flyway — таблицы создаются через `Base.metadata.create_all` при старте приложения.

Когда появится Alembic, типичный цикл:

```bash
alembic revision --autogenerate -m "описание"
alembic upgrade head
```

До введения миграций достаточно согласованности `backend/models.py` с БД вручную или через пересоздание схемы в dev.
