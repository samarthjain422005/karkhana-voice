import asyncio
import logging
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from apps.api.bolna import BolnaClient, BolnaError, extract_execution_fields
from apps.api.config import get_settings
from apps.api.store import (
    Person,
    acknowledge_incident,
    acknowledge_handover,
    add_owner_signal,
    append_handover,
    claim_incident_escalation,
    create_daily_job_if_missing,
    get_incident,
    get_due_incidents,
    get_session,
    get_person,
    DailyJob,
    complete_close_retry,
    get_due_close_retries,
    list_daily_brief_recipients,
    list_pending_handovers,
    get_stuck_calls,
    mark_call_reconciled,
    claim_close_retry,
    record_approval,
    register_queued_call,
    set_incident_supervisor_execution,
    update_daily_job,
    update_incident_call_status,
    update_purchase_order_eta,
    upsert_call_webhook,
)
from apps.api.watchtower import compute_watchtower

logger = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo("Asia/Kolkata")
AGENT_SETTINGS = {
    "close": "bolna_agent_id_close",
    "open": "bolna_agent_id_open",
    "alert": "bolna_agent_id_alert",
}
CALL_MODES = {
    "close": {"shift_close", "opening_count"},
    "open": {"morning_brief", "handover_brief"},
    "alert": {"breakdown_dispatch", "supplier_eta"},
}


class WorkflowError(RuntimeError):
    pass


def _call_window_contains(person: Person, now: datetime | None = None) -> bool:
    local_now = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
    try:
        start_text, end_text = person.call_window.split("-", maxsplit=1)
        start = time.fromisoformat(start_text)
        end = time.fromisoformat(end_text)
    except ValueError as exc:
        raise WorkflowError(f"Invalid call window for {person.name}.") from exc
    current = local_now.time().replace(tzinfo=None)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def _check_opt_in(person: Person) -> None:
    if not person.opted_in or person.consent_at is None or person.consent_method == "none":
        raise WorkflowError(f"{person.name} has no recorded call consent.")
    if not _call_window_contains(person):
        raise WorkflowError(
            f"{person.name} is outside their permitted call window ({person.call_window})."
        )


def _risk_context(org_id: str) -> list[dict[str, Any]]:
    result = compute_watchtower(org_id)
    return [
        {
            "sku": row["sku"],
            "name": row["name"],
            "band": row["band"],
            "score": row["score"],
            "slack_days": row["slack_days"],
            "shortfall": max(
                0,
                row["planned_demand"] - row["on_hand"] - row["open_po_qty"],
            ),
            "reason": row["reason"],
            "suggested_reorder_qty": row["suggested_reorder_qty"],
        }
        for row in result["risk_lane"]
        if row["band"] in {"Red", "Amber"}
    ][:3]


def _base_user_data(
    org_id: str, agent: str, mode: str, person: Person, extra: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    user_data = {
        "org_id": org_id,
        "session_id": session_id,
        "agent": agent,
        "mode": mode,
        "person_name": person.name,
        "person_id": person.id,
        "role": person.role,
        "timezone": "Asia/Kolkata",
        **extra,
    }
    return session_id, user_data


def place_agent_call(
    org_id: str,
    agent: str,
    mode: str,
    person: Person,
    extra: dict[str, Any] | None = None,
) -> dict[str, str]:
    if agent not in AGENT_SETTINGS or mode not in CALL_MODES[agent]:
        raise WorkflowError(f"Unsupported workflow mode: {agent}/{mode}.")
    _check_opt_in(person)
    settings = get_settings()
    agent_setting = AGENT_SETTINGS[agent]
    agent_id = getattr(settings, agent_setting)
    if not agent_id:
        raise WorkflowError(f"BOLNA_AGENT_ID_{agent.upper()} is not configured.")

    try:
        client = BolnaClient()
        account = client.get_user_me()
    except (BolnaError, httpx.HTTPError, ValueError) as exc:
        raise WorkflowError(f"Bolna account check failed: {exc}") from exc
    wallet = account.get("wallet")
    try:
        has_funds = wallet is not None and float(wallet) >= settings.wallet_floor
    except (TypeError, ValueError) as exc:
        raise WorkflowError("Bolna returned a non-numeric wallet balance.") from exc
    if not has_funds:
        raise WorkflowError(
            f"Bolna wallet is below the configured ${settings.wallet_floor:.2f} floor."
        )
    session_id, user_data = _base_user_data(
        org_id, agent, mode, person, extra or {}
    )
    try:
        response = client.place_call(agent_id, person.phone, user_data)
    except (BolnaError, httpx.HTTPError) as exc:
        raise WorkflowError(f"Bolna call request failed: {exc}") from exc
    execution_id = response["execution_id"]
    register_queued_call(
        execution_id=execution_id,
        org_id=org_id,
        person_id=person.id,
        session_id=session_id,
        raw_payload={**response, "user_data": user_data},
        agent=agent,
        mode=mode,
        retry_count=int(user_data.get("retry_count") or 0),
    )
    return {"execution_id": execution_id, "session_id": session_id}


def start_workflow_call(
    org_id: str,
    agent: str,
    mode: str,
    person: Person,
    extra: dict[str, Any] | None = None,
) -> dict[str, str]:
    context = dict(extra or {})
    if agent == "close":
        from apps.api.store import build_close_expected_context

        context.update(build_close_expected_context(org_id))
    elif agent == "open" and mode == "morning_brief":
        context["risk_summary"] = _risk_context(org_id)
    elif agent == "open" and mode == "handover_brief":
        context["handover_summary"] = [
            {
                "id": item.id,
                "text": item.text,
                "severity": item.severity,
            }
            for item in list_pending_handovers(org_id, 3)
        ]
    return place_agent_call(org_id, agent, mode, person, context)


def escalation_for_incident(incident_id: str) -> bool:
    current = get_incident(incident_id)
    if current is None or current.resolved_at is not None or current.escalated_at is not None:
        return False
    supervisor = get_person(current.supervisor_person_id) if current.supervisor_person_id else None
    if supervisor is None or not current.supervisor_consent:
        update_incident_call_status(current.id, "supervisor", "blocked_no_consent")
        logger.error("Incident %s has no opted-in supervisor contact.", current.id)
        return False
    if not _call_window_contains(supervisor):
        return False
    incident = claim_incident_escalation(incident_id)
    if incident is None:
        return False
    try:
        call = place_agent_call(
            incident.org_id,
            "alert",
            "breakdown_dispatch",
            supervisor,
            {
                "incident_id": incident.id,
                "machine": incident.machine,
                "audience": "supervisor",
                "escalation_reason": "Technician did not clearly acknowledge the breakdown.",
            },
        )
    except (WorkflowError, BolnaError, httpx.HTTPError, ValueError):
        update_incident_call_status(incident.id, "supervisor", "failed_to_place")
        logger.exception("Could not escalate incident %s to supervisor.", incident.id)
        return False
    set_incident_supervisor_execution(incident.id, call["execution_id"])
    return True


def _scheduled_brief_jobs(now: datetime) -> None:
    settings = get_settings()
    try:
        scheduled_time = time.fromisoformat(settings.open_brief_time)
    except ValueError:
        logger.error("OPEN_BRIEF_TIME must be HH:MM; daily Open calls are disabled.")
        return
    local_now = now.astimezone(LOCAL_TZ)
    if local_now.time().replace(tzinfo=None) < scheduled_time:
        return
    today = local_now.date()
    for person in list_daily_brief_recipients(settings.default_org_id):
        if not _call_window_contains(person, local_now):
            continue
        if person.id is None or not create_daily_job_if_missing(
            settings.default_org_id, person.id, today, "morning_brief"
        ):
            continue
        from sqlmodel import select

        with get_session() as session:
            job = session.exec(
                select(DailyJob).where(
                    DailyJob.org_id == settings.default_org_id,
                    DailyJob.person_id == person.id,
                    DailyJob.job_date == today,
                    DailyJob.job_type == "morning_brief",
                )
            ).first()
        if job is None or job.id is None:
            logger.error("Could not find daily Open job for person %s.", person.id)
            continue
        try:
            call = start_workflow_call(
                settings.default_org_id, "open", "morning_brief", person
            )
        except (WorkflowError, BolnaError, httpx.HTTPError, ValueError):
            update_daily_job(job.id, "failed")
            logger.exception("Daily Open brief failed for person %s.", person.id)
        else:
            update_daily_job(job.id, "queued", call["execution_id"])


def _process_due_close_retries(now: datetime) -> None:
    for due in get_due_close_retries(now):
        record = claim_close_retry(due.execution_id)
        if record is None:
            continue
        person = get_person(record.person_id) if record.person_id else None
        if person is None:
            complete_close_retry(record.execution_id, failed=True)
            logger.error("Cannot retry Close execution %s: person record is missing.", record.execution_id)
            continue
        try:
            result = start_workflow_call(
                record.org_id,
                "close",
                record.mode if record.mode in CALL_MODES["close"] else "shift_close",
                person,
                {"retry_count": record.retry_count},
            )
        except (WorkflowError, BolnaError, httpx.HTTPError, ValueError):
            complete_close_retry(record.execution_id, failed=True)
            logger.exception("Close retry failed for execution %s.", record.execution_id)
        else:
            complete_close_retry(
                record.execution_id, new_execution_id=result["execution_id"]
            )


def _reconcile_stuck_calls(now: datetime) -> None:
    stale_calls = get_stuck_calls(
        older_than=now - timedelta(minutes=10),
        reconciled_before=now - timedelta(seconds=60),
    )
    if not stale_calls:
        return
    try:
        client = BolnaClient()
    except ValueError:
        logger.warning("Stuck-call reconciliation skipped: Bolna API key is not configured.")
        for record in stale_calls:
            mark_call_reconciled(record.execution_id)
        return
    for record in stale_calls:
        try:
            execution = client.get_execution(record.execution_id)
            info = extract_execution_fields(execution)
            should_process = upsert_call_webhook(
                execution_id=record.execution_id,
                org_id=record.org_id,
                status=info["status"],
                raw_payload=execution,
                duration=info["conversation_duration"],
                total_cost=info["total_cost"],
                cost_breakdown=info["cost_breakdown"],
                session_id=info["session_id"],
            )
            mark_call_reconciled(record.execution_id)
            if should_process:
                from apps.api.routes.webhooks import process_and_finalize

                process_and_finalize(record.org_id, execution)
        except (BolnaError, httpx.HTTPError, ValueError):
            mark_call_reconciled(record.execution_id)
            logger.exception("Stuck-call reconciliation failed for %s.", record.execution_id)


def run_scheduler_once(now: datetime | None = None) -> None:
    """Run one scheduler pass; also used by serverless scheduled invocations."""
    now = now or datetime.now(timezone.utc)
    for incident in get_due_incidents(now):
        escalation_for_incident(incident.id)
    _process_due_close_retries(now)
    _reconcile_stuck_calls(now)
    _scheduled_brief_jobs(now)


async def scheduler_loop() -> None:
    """Restart-safe polling for escalation, retries, stuck calls, and daily briefs."""
    while True:
        now = datetime.now(timezone.utc)
        try:
            run_scheduler_once(now)
        except Exception:
            logger.exception("Workflow scheduler iteration failed.")
        await asyncio.sleep(10)


def handle_alert_execution(user_data: dict[str, Any], status: str, transcript: str) -> None:
    incident_id = str(user_data.get("incident_id") or "")
    audience = str(user_data.get("audience") or "technician")
    if not incident_id:
        return
    update_incident_call_status(incident_id, audience, status)
    if status != "completed":
        if audience == "technician":
            escalation_for_incident(incident_id)
        return

    acknowledgement = re.search(
        r"CONFIRMED_INCIDENT_ACK:\s*INCIDENT_ID=(?P<id>[^|\n]+)"
        r"\|ETA_MINUTES=(?P<eta>\d+)\|NOTE=(?P<note>[^\n]*)",
        transcript,
        re.IGNORECASE,
    )
    if acknowledgement and acknowledgement.group("id").strip() == incident_id:
        acknowledge_incident(
            incident_id,
            audience,
            int(acknowledgement.group("eta")),
            acknowledgement.group("note").strip(),
        )
        return
    if audience == "technician":
        escalation_for_incident(incident_id)


def process_open_execution(
    org_id: str, user_data: dict[str, Any], transcript: str
) -> None:
    execution_id = str(user_data.get("execution_id") or "")
    person_id_value = user_data.get("person_id")
    person_id = int(person_id_value) if person_id_value is not None else None
    mode = str(user_data.get("mode") or "")
    if mode == "morning_brief":
        approval_pattern = re.compile(
            r"CONFIRMED_APPROVAL:\s*PART=(?P<part>[^|\n]+)"
            r"\|DECISION=(?P<decision>approve|defer|reject)",
            re.IGNORECASE,
        )
        for match in approval_pattern.finditer(transcript):
            record_approval(
                org_id,
                execution_id,
                match.group("part").strip(),
                match.group("decision").casefold(),
                person_id,
            )
        note_pattern = re.compile(
            r"CONFIRMED_OWNER_NOTE:\s*SUPPLIER=(?P<supplier>[^|\n]+)"
            r"\|DELAY_DAYS=(?P<days>\d+)\|NOTE=(?P<note>[^\n]*)",
            re.IGNORECASE,
        )
        for match in note_pattern.finditer(transcript):
            supplier = add_owner_signal(
                org_id,
                match.group("supplier").strip(),
                int(match.group("days")),
                match.group("note").strip(),
                execution_id,
            )
            if supplier is None:
                logger.warning(
                    "Open call %s named unknown supplier %r.",
                    execution_id,
                    match.group("supplier").strip(),
                )
    elif mode == "handover_brief":
        ack_pattern = re.compile(
            r"CONFIRMED_HANDOVER_ACK:\s*ID=(?P<id>\d+)\|ACK=yes",
            re.IGNORECASE,
        )
        for match in ack_pattern.finditer(transcript):
            acknowledge_handover(int(match.group("id")), person_id)


def process_alert_execution(
    org_id: str,
    user_data: dict[str, Any],
    status: str,
    transcript: str,
) -> None:
    mode = str(user_data.get("mode") or "")
    if mode == "breakdown_dispatch":
        handle_alert_execution(user_data, status, transcript)
        return
    if mode == "supplier_eta" and status == "completed":
        match = re.search(
            r"CONFIRMED_SUPPLIER_ETA:\s*PO_ID=(?P<po>[^|\n]+)"
            r"\|ETA_DATE=(?P<eta>\d{4}-\d{2}-\d{2})",
            transcript,
            re.IGNORECASE,
        )
        if match:
            try:
                eta = date.fromisoformat(match.group("eta"))
            except ValueError:
                logger.warning("Supplier ETA call emitted invalid date.")
                return
            updated = update_purchase_order_eta(
                org_id,
                str(user_data.get("execution_id") or ""),
                match.group("po").strip(),
                eta,
            )
            if not updated:
                logger.warning(
                    "Supplier ETA call named unknown/closed PO %r.",
                    match.group("po").strip(),
                )


def process_close_handover(
    org_id: str, user_data: dict[str, Any], transcript: str
) -> None:
    if str(user_data.get("role") or "") != "supervisor":
        return
    execution_id = str(user_data.get("execution_id") or "")
    match_pattern = re.compile(
        r"CONFIRMED_HANDOVER:\s*SEVERITY=(?P<severity>high|normal)"
        r"\|NOTE=(?P<note>[^\n]+)",
        re.IGNORECASE,
    )
    person_value = user_data.get("person_id")
    person_id = int(person_value) if person_value is not None else None
    for match in match_pattern.finditer(transcript):
        append_handover(
            org_id,
            execution_id,
            match.group("note").strip(),
            match.group("severity").casefold(),
            person_id,
        )


def process_workflow_terminal(org_id: str, payload: dict[str, Any]) -> None:
    info = extract_execution_fields(payload)
    if not info["is_terminal"]:
        return
    user_data = payload.get("user_data") or {}
    if not isinstance(user_data, dict):
        raise ValueError("Bolna user_data must be an object.")
    user_data = {
        **user_data,
        "execution_id": info["execution_id"],
    }
    agent = str(user_data.get("agent") or "close")
    if agent == "alert":
        process_alert_execution(
            org_id, user_data, info["status"], info["transcript"]
        )
    elif agent == "open" and info["status"] == "completed":
        process_open_execution(org_id, user_data, info["transcript"])
    elif agent == "close" and info["status"] == "completed":
        process_close_handover(org_id, user_data, info["transcript"])
    if agent == "close" and info["status"] == "completed":
        from apps.api.routes.webhooks import process_completed_call

        process_completed_call(org_id, payload)


def acknowledge_incident_manually(incident_id: str, note: str) -> None:
    incident = get_incident(incident_id)
    if incident is None:
        raise WorkflowError("Open incident was not found.")
    acknowledge_incident(incident_id, "supervisor", None, note)
