"""Аутентификация: публичный login и защита /api/orders."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client() -> TestClient:
    """Контекстный менеджер обязателен: иначе не выполняется startup (create_all / демо)."""
    with TestClient(app) as test_client:
        yield test_client


def test_orders_without_token_returns_401(client: TestClient) -> None:
    r = client.get("/api/orders")
    assert r.status_code == 401
    assert r.json().get("detail")


def test_health_public(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_login_form_urlencoded_ok(client: TestClient) -> None:
    r = client.post("/api/auth/login", data={"username": "planner", "password": "testpass"})
    assert r.status_code == 200, r.text
    assert r.json().get("token_type") == "bearer"


def test_login_and_orders_with_token(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"username": "planner", "password": "testpass"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("token_type") == "bearer"
    assert data.get("role") == "planner"
    token = data["access_token"]
    r2 = client.get("/api/orders", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert isinstance(r2.json(), list)
