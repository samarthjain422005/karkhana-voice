from datetime import date

import pytest
from apps.api.config import get_settings
from apps.api.routes.webhooks import process_completed_call
from apps.api.store import (
    find_part_by_sku_or_alias,
    get_on_hand_qty,
    init_db,
    list_recent_calls_and_events,
    reset_engine_for_tests,
    upsert_call_webhook,
)
from apps.api.watchtower import compute_watchtower
from scripts.seed_demo import seed_aarav_pumps


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    get_settings.cache_clear()
    reset_engine_for_tests()
    init_db()
    seed_aarav_pumps()
    yield
    reset_engine_for_tests()
    get_settings.cache_clear()


def test_synthetic_watchtower_expected_bands_and_components():
    result = compute_watchtower(get_settings().default_org_id)
    assert result["summary"] == {"Red": 2, "Amber": 1, "Green": 6, "Over_stock": 1}
    by_sku = {row["sku"]: row for row in result["risk_lane"]}
    assert by_sku["P-104"]["score"] == 50
    assert by_sku["P-104"]["components"] == {
        "slack": 35, "supplier_slip": 0, "single_source": 15, "data_confidence": 0
    }
    assert by_sku["P-105"]["score"] == 70
    assert by_sku["P-105"]["components"]["supplier_slip"] == 20
    assert by_sku["P-107"]["score"] == 30


def test_webhook_claims_completed_once_and_ignores_disconnect_transcript():
    execution_id = "exec-lifecycle-test"
    org_id = get_settings().default_org_id
    assert not upsert_call_webhook(
        execution_id,
        org_id,
        "call-disconnected",
        {"id": execution_id, "status": "call-disconnected", "transcript": "ignored"},
    )
    assert upsert_call_webhook(
        execution_id,
        org_id,
        "completed",
        {"id": execution_id, "status": "completed", "transcript": ""},
    )
    assert not upsert_call_webhook(
        execution_id,
        org_id,
        "completed",
        {"id": execution_id, "status": "completed", "transcript": ""},
    )


def test_completed_parser_is_idempotent_and_guardrail_holds_spike():
    org_id = get_settings().default_org_id
    gasket = find_part_by_sku_or_alias(org_id, "chhota gasket")
    assert gasket is not None and gasket.id is not None
    before = get_on_hand_qty(org_id, gasket.id)
    payload = {
        "id": "exec-parser-test",
        "status": "completed",
        "transcript": (
            "assistant: CONFIRMED_LEDGER: PART=P-104|QTY=6000|UNIT=piece|TYPE=receipt"
        ),
    }
    process_completed_call(org_id, payload)
    process_completed_call(org_id, payload)
    assert get_on_hand_qty(org_id, gasket.id) == before


def test_confirmed_output_backflushes_bom():
    org_id = get_settings().default_org_id
    gasket = find_part_by_sku_or_alias(org_id, "gasket")
    assert gasket is not None and gasket.id is not None
    before = get_on_hand_qty(org_id, gasket.id)
    process_completed_call(
        org_id,
        {
            "id": "exec-output-test",
            "status": "completed",
            "transcript": (
                "assistant: CONFIRMED_LEDGER: PART=Pump-X|QTY=10|UNIT=piece|TYPE=output"
            ),
        },
    )
    process_completed_call(
        org_id,
        {
            "id": "exec-output-test",
            "status": "completed",
            "transcript": (
                "assistant: CONFIRMED_LEDGER: PART=Pump-X|QTY=10|UNIT=piece|TYPE=output"
            ),
        },
    )
    assert get_on_hand_qty(org_id, gasket.id) == before - 10
    outputs = list_recent_calls_and_events(org_id)["production_outputs"]
    assert len(outputs) == 1
    assert outputs[0]["product_code"] == "Pump-X"
    assert outputs[0]["qty"] == 10
    assert outputs[0]["state"] == "confirmed"


def test_unreasonable_production_output_is_held_for_review():
    org_id = get_settings().default_org_id
    process_completed_call(
        org_id,
        {
            "id": "exec-output-spike-test",
            "status": "completed",
            "transcript": (
                "assistant: CONFIRMED_LEDGER: PART=Pump-X|QTY=100000|UNIT=piece|TYPE=output"
            ),
        },
    )
    outputs = list_recent_calls_and_events(org_id)["production_outputs"]
    assert outputs[0]["state"] == "needs_review"
    assert outputs[0]["guardrail_flags"] == '["production_qty_spike"]'


def test_watchtower_accepts_fixed_reference_date():
    result = compute_watchtower(get_settings().default_org_id, today=date.today())
    assert result["as_of"] == date.today().isoformat()
