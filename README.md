# Backend: оперативное планирование производства

REST API для расчёта расписания и справочников (корпусные изделия из листового металла, мелкосерия).

**Стек:** Python 3, FastAPI, SQLAlchemy 2.x, PostgreSQL, Pydantic v2.

## Требования

- **Python** 3.11+ (в проекте проверялось на 3.13).
- **PostgreSQL** с доступом по TCP (по умолчанию порт `5432`). Для тестов `pytest` PostgreSQL **не** нужен — в тестах используется SQLite в памяти.

## Быстрый старт

1. Создайте виртуальное окружение и установите зависимости:

   ```bash
   cd Backend   # корень репозитория backend
   python3 -m venv venv
   source venv/bin/activate          # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Скопируйте пример окружения и при необходимости отредактируйте `.env` (обязательно **`DATABASE_URL`** под вашу установку PostgreSQL):

   ```bash
   cp .env.example .env
   ```

3. Убедитесь, что в кластере есть **роль** и **база** из `DATABASE_URL`. Пример для локальной машины:

   ```bash
   psql -d postgres -c '\du'                    # список ролей
   createdb production_planning                 # если базы ещё нет
   ```

4. Запуск сервера:

   ```bash
   uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
   ```

Открытая документация: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## Конфигурация (`.env`)

Ориентир — файл **`.env.example`**. Основные переменные:

| Переменная | Назначение |
|------------|------------|
| `DATABASE_URL` | Строка SQLAlchemy для PostgreSQL, например `postgresql://ИМЯ_РОЛИ@localhost:5432/production_planning` или с паролем `postgresql://роль:пароль@хост:5432/имя_базы` |
| `CORS_ORIGINS` | Разрешённые origin для браузера (через запятую), для Vite: `http://localhost:5173` и т.п. |
| `SQL_ECHO` | Логировать SQL (`true` / `false`) |
| `JWT_SECRET_KEY`, `JWT_EXPIRE_MINUTES` | Подпись и срок жизни JWT |
| `PLANNER_USERNAME`, `PLANNER_PASSWORD` или `PLANNER_PASSWORD_HASH` | Учётная запись планировщика (в продакшене — только хэш пароля) |

### PostgreSQL: типичные ошибки

- **`FATAL: role "user" does not exist`** — в `DATABASE_URL` указана несуществующая роль. Часто в `.env` по ошибке оставляют шаблон с именем `user`. Замените на реальную роль из `\du` (на Linux часто `postgres`, на macOS с Homebrew суперпользователь иногда совпадает с логином в ОС).
- **Нет базы** — создайте её (`createdb …`) или дайте роли право на создание БД.

## REST API (MVP)

Префикс **`/api`**: справочники `workers`, `equipment`, `tech-processes`, задачи `tasks/{id}`, заказы `orders`, read-only `operations`, пересчёт **`POST /schedule`**. Схемы тел и ответов — в **`/docs`**.

### Аутентификация

- **`POST /api/auth/login`** — тело: **JSON** `{"username": "…", "password": "…"}` (рекомендуется для SPA, заголовок `Content-Type: application/json`) **или** `application/x-www-form-urlencoded` с полями `username` и `password`. В ответе: `access_token` (JWT), `token_type`, `role`.
- Остальные маршруты под `/api` (кроме публичных вроде **`GET /api/health`**) требуют заголовок **`Authorization: Bearer <access_token>`**.

## Тесты

```bash
pytest
```

Тесты не поднимают PostgreSQL: в `conftest.py` задаётся `DATABASE_URL=sqlite:///:memory:`.

## Схема БД

Alembic в репозитории пока не используется: таблицы создаются вызовом **`Base.metadata.create_all`** при старте приложения. При появлении миграций типичный цикл:

```bash
alembic revision --autogenerate -m "описание"
alembic upgrade head
```

До этого достаточно согласованности `backend/models.py` с фактической БД в dev (при необходимости — пересоздание схемы вручную).
