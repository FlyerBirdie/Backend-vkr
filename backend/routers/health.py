"""Публичная проверка доступности сервиса."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Проверка работоспособности",
    description="Не требует аутентификации.",
)
def health() -> dict[str, str]:
    return {"status": "ok"}
