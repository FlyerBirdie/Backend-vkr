"""Единый стиль тел `detail` для 404/409 (помимо стандартного 422 Pydantic)."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def not_found(resource: str, id_: int) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=_detail("NOT_FOUND", f"{resource} с id={id_} не найден."),
    )


def conflict(message: str, code: str = "CONFLICT") -> HTTPException:
    return HTTPException(status_code=409, detail=_detail(code, message))


def _detail(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}
