import pytest
from fastapi.testclient import TestClient

from apps.api.config import get_settings
import apps.api.main as api_main
from apps.api.main import app
from apps.api.store import (
    find_part_by_sku_or_alias,
    get_on_hand_qty,
    reset_engine_for_tests,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api-test.db'}")
    monkeypatch.setenv("WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("CRON_SECRET", "")
    get_settings.cache_clear()
    reset_engine_for_tests()
    with TestClient(app) as test_client:
        yield test_client
    reset_engine_for_tests()
    get_settings.cache_clear()


def test_control_room_and_watchtower_are_available(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "SYNTHETIC DEMO DATA" in page.text
    response = client.get("/api/watchtower")
    assert response.status_code == 200
    assert response.json()["summary"] == {
        "Red": 2,
        "Amber": 1,
        "Green": 6,
        "Over_stock": 1,
    }


def test_demo_call_requires_explicit_opt_in(client):
    response = client.post(
        "/api/workflow/call",
        json={
            "agent": "close",
            "mode": "shift_close",
            "role": "floor_manager",
            "phone": "+919876543210",
            "name": "Ramesh",
            "recipient_opted_in": False,
        },
    )
    assert response.status_code == 400
    assert "opt-in" in response.json()["detail"]


def test_webhook_rejects_missing_or_invalid_secret(client):
    payload = {"id": "exec-auth-test", "status": "completed", "transcript": ""}
    missing = client.post("/webhooks/bolna", json=payload)
    invalid = client.post(
        "/webhooks/bolna",
        headers={"X-Webhook-Secret": "wrong"},
        json=payload,
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_scheduled_workflow_endpoint_requires_secret_and_runs_once(
    client, monkeypatch
):
    calls = []
    monkeypatch.setattr(api_main, "run_scheduler_once", lambda: calls.append(True))
    assert client.get("/api/cron").status_code == 503

    monkeypatch.setenv("CRON_SECRET", "test-cron-secret")
    get_settings.cache_clear()
    assert client.get(
        "/api/cron", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401
    response = client.get(
        "/api/cron",
        headers={"Authorization": "Bearer test-cron-secret"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == [True]


def test_vercel_runtime_rejects_ephemeral_sqlite_database(tmp_path, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'vercel.db'}")
    get_settings.cache_clear()
    reset_engine_for_tests()
    with pytest.raises(RuntimeError, match="persistent PostgreSQL"):
        with TestClient(app):
            pass
    reset_engine_for_tests()
    get_settings.cache_clear()


def test_supplier_delay_what_if_can_move_impeller_to_red(client):
    baseline = client.get("/api/watchtower").json()
    baseline_impeller = next(
        row for row in baseline["risk_lane"] if row["sku"] == "P-102"
    )
    assert baseline_impeller["band"] == "Green"

    response = client.post(
        "/api/demo/owner-note",
        json={"supplier_name": "Shree Components", "delay_days": 4},
    )
    assert response.status_code == 200
    updated = client.get("/api/watchtower").json()
    updated_impeller = next(
        row for row in updated["risk_lane"] if row["sku"] == "P-102"
    )
    assert updated_impeller["band"] == "Red"


def test_webhook_only_processes_completed_once(client):
    org_id = get_settings().default_org_id
    part = find_part_by_sku_or_alias(org_id, "gasket")
    assert part is not None and part.id is not None
    before = get_on_hand_qty(org_id, part.id)
    execution_id = "exec-api-lifecycle-test"
    line = "CONFIRMED_LEDGER: PART=P-104|QTY=12|UNIT=piece|TYPE=receipt"

    disconnected = client.post(
        "/webhooks/bolna",
        headers={"X-Webhook-Secret": "test-webhook-secret"},
        json={
            "id": execution_id,
            "status": "call-disconnected",
            "transcript": line,
            "user_data": {"org_id": org_id},
        },
    )
    assert disconnected.status_code == 200
    assert disconnected.json()["processed"] is False
    assert get_on_hand_qty(org_id, part.id) == before

    completed_payload = {
        "id": execution_id,
        "status": "completed",
        "transcript": line,
        "user_data": {"org_id": org_id},
    }
    completed = client.post(
        "/webhooks/bolna",
        headers={"X-Webhook-Secret": "test-webhook-secret"},
        json=completed_payload,
    )
    assert completed.status_code == 200
    assert completed.json()["processed"] is True
    assert get_on_hand_qty(org_id, part.id) == before + 12

    duplicate = client.post(
        "/webhooks/bolna",
        headers={"X-Webhook-Secret": "test-webhook-secret"},
        json=completed_payload,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["processed"] is False
    assert get_on_hand_qty(org_id, part.id) == before + 12
