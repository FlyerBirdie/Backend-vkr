"""Публичная аутентификация: выдача JWT."""
from __future__ import annotations

import json
from urllib.parse import parse_qsl

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError

from backend import auth_settings
from backend.auth_deps import create_access_token, verify_planner_password
from backend.schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _login_from_urlencoded(body_bytes: bytes) -> LoginRequest:
    text = body_bytes.decode("utf-8", errors="replace")
    pairs = dict(parse_qsl(text, keep_blank_values=True))
    return LoginRequest(
        username=str(pairs.get("username") or "").strip(),
        password=str(pairs.get("password") or ""),
    )


def _login_from_json_dict(payload: object) -> LoginRequest:
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "type": "model_attributes_type",
                    "loc": ("body",),
                    "msg": "Ожидается JSON-объект с полями username и password.",
                    "input": payload,
                }
            ],
        )
    try:
        return LoginRequest.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.errors()) from e


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Вход планировщика",
    description=(
        "Тело: JSON `{\"username\",\"password\"}` или `application/x-www-form-urlencoded` "
        "с полями `username`, `password` (как OAuth2). При успехе — JWT (роль planner)."
    ),
)
async def login(request: Request) -> TokenResponse:
    body_bytes = await request.body()
    ct = (request.headers.get("content-type") or "").split(";")[0].strip().lower()

    if ct == "application/x-www-form-urlencoded":
        credentials = _login_from_urlencoded(body_bytes)
    elif ct.startswith("multipart/form-data"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Для входа используйте JSON или application/x-www-form-urlencoded.",
        )
    else:
        if not body_bytes.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[{"type": "missing", "loc": ("body",), "msg": "Пустое тело запроса"}],
            )
        try:
            payload = json.loads(body_bytes)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[{"type": "json_invalid", "loc": ("body",), "msg": f"Некорректный JSON: {exc}"}],
            ) from exc
        credentials = _login_from_json_dict(payload)

    if credentials.username != auth_settings.PLANNER_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Неверное имя пользователя или пароль."},
        )
    if not verify_planner_password(credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Неверное имя пользователя или пароль."},
        )
    try:
        token = create_access_token(username=credentials.username)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_MISCONFIGURED", "message": str(e)},
        ) from e
    return TokenResponse(access_token=token, token_type="bearer", role=auth_settings.ROLE_PLANNER)
