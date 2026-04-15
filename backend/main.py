# Зависимости проекта (установка: pip install -r requirements.txt):
# fastapi, uvicorn[standard], sqlalchemy, psycopg2-binary, pydantic, python-dotenv

"""
FastAPI-приложение: производственное планирование.
Роутеры под префиксом /api; демо-данные при старте.
Публично: POST /api/auth/login, GET /api/health. Остальные /api/* — JWT Bearer (роль planner).
"""
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from backend.auth_deps import get_current_planner
from backend.database import Base, engine, SessionLocal
from backend.demo_data import init_demo_data
from backend.routers import auth, equipment, health, operations, orders, schedule, tasks, tech_processes, workers


def create_tables_and_demo() -> None:
    """Создать таблицы и при необходимости заполнить демо-данными."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        init_demo_data(db)
    finally:
        db.close()


def _cors_allow_origins() -> list[str]:
    """CORS: переменная CORS_ORIGINS — список через запятую; * или пусто — разрешить все (только для разработки)."""
    raw = os.getenv("CORS_ORIGINS", "*").strip()
    if raw in ("*", ""):
        return ["*"]
    return [x.strip() for x in raw.split(",") if x.strip()]


app = FastAPI(title="Production Planning API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    create_tables_and_demo()


_api_prefix = "/api"
_planner_dep = [Depends(get_current_planner)]

app.include_router(auth.router, prefix=_api_prefix)
app.include_router(health.router, prefix=_api_prefix)
app.include_router(workers.router, prefix=_api_prefix, dependencies=_planner_dep)
app.include_router(equipment.router, prefix=_api_prefix, dependencies=_planner_dep)
app.include_router(tech_processes.router, prefix=_api_prefix, dependencies=_planner_dep)
app.include_router(tasks.router, prefix=_api_prefix, dependencies=_planner_dep)
app.include_router(orders.router, prefix=_api_prefix, dependencies=_planner_dep)
app.include_router(operations.router, prefix=_api_prefix, dependencies=_planner_dep)
app.include_router(schedule.router, prefix=_api_prefix, dependencies=_planner_dep)


def custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version="1.0.0",
        routes=app.routes,
        description="API планирования. Защищённые маршруты требуют заголовок `Authorization: Bearer <JWT>`.",
    )
    openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})["HTTPBearer"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "JWT из POST /api/auth/login; укажите как Bearer token.",
    }
    public_paths = {"/api/auth/login", "/api/health"}
    for path, path_item in openapi_schema.get("paths", {}).items():
        if path in public_paths or not path.startswith("/api"):
            continue
        for method, op in path_item.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            if "security" not in op:
                op["security"] = [{"HTTPBearer": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]
