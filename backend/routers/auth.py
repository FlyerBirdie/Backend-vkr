"""Публичная аутентификация: выдача JWT."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from backend import auth_settings
from backend.auth_deps import create_access_token, verify_planner_password
from backend.schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Вход планировщика",
    description="При успешной проверке username/password возвращает JWT (роль planner).",
)
def login(body: LoginRequest) -> TokenResponse:
    if body.username != auth_settings.PLANNER_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Неверное имя пользователя или пароль."},
        )
    if not verify_planner_password(body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Неверное имя пользователя или пароль."},
        )
    try:
        token = create_access_token(username=body.username)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_MISCONFIGURED", "message": str(e)},
        ) from e
    return TokenResponse(access_token=token, token_type="bearer", role=auth_settings.ROLE_PLANNER)
