import json
from pathlib import Path

import pytest

from apps.api.config import get_settings
from apps.api.orchestrator import (
    escalation_for_incident,
    process_alert_execution,
    process_close_handover,
    process_open_execution,
)
from apps.api.store import (
    append_handover,
    get_incident,
    get_or_create_opted_in_person,
    get_purchase_order_context,
    init_db,
    list_approvals,
    list_pending_handovers,
    register_incident,
    reset_engine_for_tests,
)
from apps.api import orchestrator
from scripts.seed_demo import seed_aarav_pumps


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'workflows.db'}")
    get_settings.cache_clear()
    reset_engine_for_tests()
    init_db()
    seed_aarav_pumps()
    yield
    reset_engine_for_tests()
    get_settings.cache_clear()


def test_three_agent_specs_are_valid_and_have_disclosures():
    root = Path(__file__).resolve().parents[1]
    for agent in ("close", "open", "alert"):
        config = json.loads(
            (root / "agents" / agent / "agent.json").read_text(encoding="utf-8")
        )
        prompt = (root / "agents" / agent / "prompt.md").read_text(encoding="utf-8")
        assert config["agent_config"]["agent_name"]
        assert config["agent_config"]["tasks"][0]["task_type"] == "conversation"
        assert "AI assistant" in config["agent_config"]["agent_welcome_message"]
        assert "call record" in prompt


def test_open_records_approval_owner_signal_and_handover_ack():
    org_id = get_settings().default_org_id
    process_open_execution(
        org_id,
        {"execution_id": "open-brief-1", "mode": "morning_brief", "person_id": 7},
        "CONFIRMED_APPROVAL: PART=P-105|DECISION=approve\n"
        "CONFIRMED_OWNER_NOTE: SUPPLIER=Shree Components|DELAY_DAYS=4|NOTE=Truck delayed",
    )
    approvals = list_approvals(org_id)
    assert approvals[0]["decision"] == "approve"
    assert approvals[0]["part_label"].startswith("P-105")

    pending = append_handover(org_id, "close-1", "Machine 3 vibration", "high")
    process_open_execution(
        org_id,
        {"execution_id": "open-handover-1", "mode": "handover_brief"},
        f"CONFIRMED_HANDOVER_ACK: ID={pending.id}|ACK=yes",
    )
    assert list_pending_handovers(org_id) == []


def test_close_supervisor_handover_capture_requires_role():
    org_id = get_settings().default_org_id
    process_close_handover(
        org_id,
        {"execution_id": "close-supervisor", "role": "supervisor"},
        "CONFIRMED_HANDOVER: SEVERITY=high|NOTE=Machine 3 is vibrating",
    )
    assert len(list_pending_handovers(org_id)) == 1
    process_close_handover(
        org_id,
        {"execution_id": "close-manager", "role": "floor_manager"},
        "CONFIRMED_HANDOVER: SEVERITY=high|NOTE=This must not be stored",
    )
    assert len(list_pending_handovers(org_id)) == 1


def test_alert_ack_and_existing_po_eta_update():
    org_id = get_settings().default_org_id
    technician = get_or_create_opted_in_person(
        org_id, "+919999999991", "Tech", "technician", "test-consent",
        "00:00-23:59",
    )
    supervisor = get_or_create_opted_in_person(
        org_id, "+919999999992", "Supervisor", "supervisor", "test-consent",
        "00:00-23:59",
    )
    incident = register_incident(
        org_id, "incident-ack-1", "Machine 3", "Tech", technician.phone,
        "Supervisor", supervisor.phone, technician.id, supervisor.id,
    )
    process_alert_execution(
        org_id,
        {
            "incident_id": incident.id,
            "audience": "technician",
            "mode": "breakdown_dispatch",
        },
        "completed",
        "CONFIRMED_INCIDENT_ACK: INCIDENT_ID=incident-ack-1|ETA_MINUTES=20|NOTE=On my way",
    )
    updated_incident = get_incident(incident.id)
    assert updated_incident is not None
    assert updated_incident.resolved_at is not None
    assert updated_incident.technician_eta_minutes == 20

    po = get_purchase_order_context(org_id, "PO-BOLT-001")
    assert po is not None
    process_alert_execution(
        org_id,
        {
            "execution_id": "supplier-eta-1",
            "mode": "supplier_eta",
        },
        "completed",
        "CONFIRMED_SUPPLIER_ETA: PO_ID=PO-BOLT-001|ETA_DATE=2026-11-06",
    )
    updated_po = get_purchase_order_context(org_id, "PO-BOLT-001")
    assert updated_po is not None
    assert updated_po["eta_date"] == "2026-11-06"


def test_breakdown_without_technician_ack_escalates_to_opted_in_supervisor(monkeypatch):
    org_id = get_settings().default_org_id
    technician = get_or_create_opted_in_person(
        org_id, "+919999999981", "Tech", "technician", "test-consent",
        "00:00-23:59",
    )
    supervisor = get_or_create_opted_in_person(
        org_id, "+919999999982", "Supervisor", "supervisor", "test-consent",
        "00:00-23:59",
    )
    incident = register_incident(
        org_id, "incident-escalate-1", "Machine 4", "Tech", technician.phone,
        "Supervisor", supervisor.phone, technician.id, supervisor.id,
    )
    monkeypatch.setattr(
        orchestrator,
        "place_agent_call",
        lambda *_args, **_kwargs: {"execution_id": "supervisor-call-1"},
    )
    process_alert_execution(
        org_id,
        {
            "incident_id": incident.id,
            "audience": "technician",
            "mode": "breakdown_dispatch",
        },
        "no-answer",
        "",
    )
    updated = get_incident(incident.id)
    assert updated is not None
    assert updated.escalation_level == 1
    assert updated.supervisor_execution_id == "supervisor-call-1"
    assert escalation_for_incident(incident.id) is False
