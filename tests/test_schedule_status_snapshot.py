"""Статусы после планирования и снимок расписания из БД."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.database import Base, SessionLocal, engine
from backend.demo_data import init_demo_data
from backend.main import app


@pytest.fixture(autouse=True)
def fresh_demo_db() -> None:
    """Изолированная БД на каждый тест (иначе in_progress из предыдущего теста блокирует планирование)."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        init_demo_data(db)
    finally:
        db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _bearer(client: TestClient) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"username": "planner", "password": "testpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_included_orders_become_in_progress_after_schedule(
    client: TestClient,
) -> None:
    h = _bearer(client)
    ro = client.get("/api/orders", headers=h)
    assert ro.status_code == 200
    scheduled = [o for o in ro.json() if o.get("status") == "scheduled"]
    assert scheduled, "нужен хотя бы один заказ scheduled в демо-данных"

    sc = client.post("/api/schedule", json={}, headers=h)
    assert sc.status_code == 200, sc.text
    body = sc.json()
    assert body.get("planner_used") in ("greedy", "genetic")
    included_ids = {x["id"] for x in body.get("included_orders", [])}
    if not included_ids:
        pytest.skip("нет включённых заказов в этом прогоне")

    for oid in included_ids:
        g = client.get(f"/api/orders/{oid}", headers=h)
        assert g.status_code == 200
        assert g.json()["status"] == "in_progress", f"order {oid}"


def test_schedule_snapshot_after_planning(client: TestClient) -> None:
    h = _bearer(client)
    sc = client.post("/api/schedule", json={}, headers=h)
    assert sc.status_code == 200, sc.text
    if not sc.json().get("operations"):
        pytest.skip("в этом прогоне нет операций в расписании")

    snap = client.get("/api/schedule/snapshot", headers=h)
    assert snap.status_code == 200, snap.text
    data = snap.json()
    assert len(data["operations"]) > 0
    assert data["planner_used"] is None
    assert data["total_profit"] is not None
