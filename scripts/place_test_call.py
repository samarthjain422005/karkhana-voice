import argparse
import time
import uuid

import httpx

from apps.api.bolna import BolnaClient, TERMINAL_STATUSES, extract_execution_fields
from apps.api.config import get_settings
from apps.api.routes.webhooks import process_and_finalize
from apps.api.store import (
    build_close_expected_context,
    get_or_create_opted_in_person,
    init_db,
    register_queued_call,
    upsert_call_webhook,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Place one opted-in Close test call.")
    parser.add_argument("--to", required=True, help="E.164 number owned by your team or opted in.")
    parser.add_argument("--name", default="Ramesh")
    parser.add_argument("--confirm-opt-in", action="store_true", required=True)
    parser.add_argument("--poll-timeout", type=int, default=240)
    args = parser.parse_args()
    settings = get_settings()
    if not settings.bolna_agent_id_close:
        raise SystemExit("Set BOLNA_AGENT_ID_CLOSE in .env first.")
    init_db()
    person = get_or_create_opted_in_person(
        settings.default_org_id, args.to, args.name, "floor_manager", "cli_explicit_opt_in"
    )
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    user_data = {
        "org_id": settings.default_org_id,
        "session_id": session_id,
        "agent": "close",
        "mode": "shift_close",
        "person_name": person.name,
        "role": person.role,
        "timezone": "Asia/Kolkata",
        **build_close_expected_context(settings.default_org_id),
    }
    client = BolnaClient()
    account = client.get_user_me()
    wallet = account.get("wallet")
    if wallet is None or float(wallet) < settings.wallet_floor:
        raise SystemExit(
            f"Bolna wallet is below the configured ${settings.wallet_floor:.2f} floor."
        )
    created = client.place_call(settings.bolna_agent_id_close, args.to, user_data)
    execution_id = created["execution_id"]
    register_queued_call(
        execution_id, settings.default_org_id, person.id, session_id, created
    )

    deadline = time.monotonic() + args.poll_timeout
    last_status = ""
    while time.monotonic() < deadline:
        with httpx.Client(timeout=15) as http:
            response = http.get(
                f"{settings.bolna_base_url.rstrip('/')}/executions/{execution_id}",
                headers={"Authorization": f"Bearer {settings.bolna_api_key}"},
            )
        if response.status_code != 200:
            raise SystemExit(f"Bolna execution poll failed ({response.status_code}): {response.text}")
        execution = response.json()
        info = extract_execution_fields(execution)
        if info["status"] != last_status:
            print(f"status -> {info['status']}")
            last_status = info["status"]
        if info["status"] in TERMINAL_STATUSES:
            should_process = upsert_call_webhook(
                execution_id,
                settings.default_org_id,
                info["status"],
                execution,
                info["conversation_duration"],
                info["total_cost"],
                info["cost_breakdown"],
                session_id,
            )
            if info["status"] == "completed" and should_process:
                process_and_finalize(settings.default_org_id, execution)
                print(
                    f"Completed: {info['conversation_duration']}s, "
                    f"${info['total_cost']:.4f}; webhook parser processes entries."
                )
            else:
                print(f"Call ended with status {info['status']}.")
            return
        time.sleep(5)
    raise SystemExit("Timed out waiting for a terminal execution status.")


if __name__ == "__main__":
    main()
