"""Статусы заказов и фильтр POST /api/schedule."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.planner import EXCLUDED_ORDER_STATUS


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _bearer(client: TestClient) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"username": "planner", "password": "testpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_schedule_excludes_draft_order(client: TestClient) -> None:
    h = _bearer(client)
    ro = client.get("/api/orders", headers=h)
    assert ro.status_code == 200
    ref = ro.json()[0]
    payload = {
        "name": "Тест черновика планирования",
        "profit": "10.00",
        "planned_start": ref["planned_start"],
        "planned_end": ref["planned_end"],
        "tech_process_id": ref["tech_process_id"],
        "status": "draft",
    }
    cr = client.post("/api/orders", json=payload, headers=h)
    assert cr.status_code == 201, cr.text
    new_id = cr.json()["id"]
    assert cr.json()["status"] == "draft"

    sc = client.post("/api/schedule", json={}, headers=h)
    assert sc.status_code == 200, sc.text
    hit = [x for x in sc.json()["excluded_orders"] if x["order_id"] == new_id]
    assert len(hit) == 1
    assert hit[0]["code"] == EXCLUDED_ORDER_STATUS
    assert "draft" in hit[0]["reason"].lower()


def test_schedule_excludes_cancelled_order(client: TestClient) -> None:
    h = _bearer(client)
    ro = client.get("/api/orders", headers=h)
    ref = ro.json()[0]
    payload = {
        "name": "Тест отмены планирования",
        "profit": "11.00",
        "planned_start": ref["planned_start"],
        "planned_end": ref["planned_end"],
        "tech_process_id": ref["tech_process_id"],
        "status": "scheduled",
    }
    cr = client.post("/api/orders", json=payload, headers=h)
    assert cr.status_code == 201, cr.text
    new_id = cr.json()["id"]
    pa = client.patch(f"/api/orders/{new_id}", json={"status": "cancelled"}, headers=h)
    assert pa.status_code == 200, pa.text

    sc = client.post("/api/schedule", json={}, headers=h)
    assert sc.status_code == 200, sc.text
    hit = [x for x in sc.json()["excluded_orders"] if x["order_id"] == new_id]
    assert len(hit) == 1
    assert hit[0]["code"] == EXCLUDED_ORDER_STATUS


def test_reset_all_orders_to_scheduled(client: TestClient) -> None:
    h = _bearer(client)
    ro = client.get("/api/orders", headers=h)
    assert ro.status_code == 200
    ref = ro.json()[0]

    cr = client.post(
        "/api/orders",
        json={
            "name": "Тест массового в плане",
            "profit": "12.00",
            "planned_start": ref["planned_start"],
            "planned_end": ref["planned_end"],
            "tech_process_id": ref["tech_process_id"],
            "status": "in_progress",
        },
        headers=h,
    )
    assert cr.status_code == 201, cr.text
    in_progress_id = cr.json()["id"]

    rs = client.post("/api/orders/reset-to-scheduled", headers=h)
    assert rs.status_code == 200, rs.text
    body = rs.json()
    assert body["updated_count"] >= 1

    got = client.get(f"/api/orders/{in_progress_id}", headers=h)
    assert got.status_code == 200
    assert got.json()["status"] == "scheduled"
