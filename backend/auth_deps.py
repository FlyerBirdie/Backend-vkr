"""JWT Bearer и зависимость get_current_planner."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext

from backend import auth_settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)


def verify_planner_password(plain_password: str) -> bool:
    if auth_settings.PLANNER_PASSWORD_HASH:
        try:
            return _pwd.verify(plain_password, auth_settings.PLANNER_PASSWORD_HASH)
        except ValueError:
            return False
    if auth_settings.PLANNER_PASSWORD:
        return plain_password == auth_settings.PLANNER_PASSWORD
    return False


def create_access_token(*, username: str) -> str:
    if not auth_settings.JWT_SECRET_KEY or len(auth_settings.JWT_SECRET_KEY) < 16:
        raise RuntimeError(
            "JWT_SECRET_KEY не задан или слишком короткий (минимум 16 символов для MVP)."
        )
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=auth_settings.JWT_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": username,
        "username": username,
        "role": auth_settings.ROLE_PLANNER,
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, auth_settings.JWT_SECRET_KEY, algorithm=auth_settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        auth_settings.JWT_SECRET_KEY,
        algorithms=[auth_settings.JWT_ALGORITHM],
    )


def get_current_planner(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict[str, str]:
    """
    Проверка Bearer JWT: подпись, срок, role=planner, sub/username согласованы.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "NOT_AUTHENTICATED", "message": "Требуется заголовок Authorization: Bearer <token>."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    if not auth_settings.JWT_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_MISCONFIGURED", "message": "JWT_SECRET_KEY не настроен на сервере."},
        )
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message": "Срок действия токена истёк."},
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from None
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Недействительный токен."},
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from e

    role = payload.get("role")
    if role != auth_settings.ROLE_PLANNER:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "FORBIDDEN_ROLE", "message": "Недостаточно прав (ожидается роль planner)."},
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    sub = payload.get("sub")
    username = payload.get("username")
    if not sub or not username or sub != username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CLAIMS", "message": "В токене отсутствуют или неверны поля sub/username."},
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    return {"username": str(username), "role": str(role)}
