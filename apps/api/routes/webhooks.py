import hmac
import logging
import re
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from apps.api.bolna import extract_execution_fields
from apps.api.config import get_settings
from apps.api.guardrails import evaluate_entry, validate_alias
from apps.api.store import (
    append_event,
    finish_completed_call,
    find_part_by_sku_or_alias,
    get_bom_for_product,
    record_production_output,
    schedule_close_retry,
    upsert_call_webhook,
)
from apps.api.orchestrator import process_workflow_terminal

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)

LEDGER_LINE_RE = re.compile(
    r"CONFIRMED_LEDGER:\s*PART=(?P<part>[^|\n]+)\|QTY=(?P<qty>-?\d+)"
    r"\|UNIT=(?P<unit>[^|\n]+)\|TYPE=(?P<type>[a-zA-Z_]+)",
    re.IGNORECASE,
)


def process_completed_call(org_id: str, payload: dict[str, Any]) -> None:
    info = extract_execution_fields(payload)
    execution_id = info["execution_id"]
    if info["status"] != "completed" or not execution_id or not info["transcript"]:
        return
    for index, match in enumerate(LEDGER_LINE_RE.finditer(info["transcript"])):
        part = find_part_by_sku_or_alias(org_id, match.group("part").strip())
        part_token = match.group("part").strip().casefold()
        qty = int(match.group("qty"))
        entry_type = match.group("type").casefold()
        if entry_type == "output" and part_token in {"pump-x", "pumpx", "pump"}:
            if qty <= 0:
                logger.warning(
                    "Ignoring non-positive production output for execution %s.",
                    execution_id,
                )
                continue
            record_production_output(
                org_id,
                execution_id,
                f"{execution_id}:production:{index}",
                "Pump-X",
                qty,
                match.group("unit").strip(),
            )
            for bom_part, per_unit in get_bom_for_product(org_id, "Pump-X"):
                if bom_part.id is None:
                    continue
                consumed = -(qty * per_unit)
                state, flags, _ = evaluate_entry(
                    org_id, bom_part, consumed, bom_part.unit
                )
                append_event(
                    org_id=org_id,
                    execution_id=execution_id,
                    source_key=f"{execution_id}:ledger:{index}:backflush:{bom_part.id}",
                    event_type="backflush",
                    part_id=bom_part.id,
                    qty=consumed,
                    unit=bom_part.unit,
                    state="confirmed" if state == "ok" else "needs_review",
                    guardrail_flags=flags,
                )
            continue
        if part is None or part.id is None:
            logger.warning(
                "Ignoring ledger line for unknown part %r in execution %s.",
                match.group("part").strip(),
                execution_id,
            )
            continue
        if entry_type in {"scrap", "backflush", "consumption"}:
            qty = -abs(qty)
        elif entry_type == "output":
            continue
        state, flags, _ = evaluate_entry(org_id, part, qty, match.group("unit"))
        if state == "ok":
            state = "confirmed"
        elif state == "reject":
            state = "rejected"
        else:
            state = "needs_review"
        append_event(
            org_id=org_id,
            execution_id=execution_id,
            source_key=f"{execution_id}:ledger:{index}",
            event_type=entry_type if entry_type in {"receipt", "scrap", "opening_count"} else "receipt",
            part_id=part.id,
            qty=qty,
            unit=part.unit,
            state=state,
            guardrail_flags=flags,
        )


@router.post("/bolna")
async def bolna_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    settings = get_settings()
    if settings.enforce_bolna_ip_allowlist:
        client_ip = request.client.host if request.client else ""
        if client_ip not in settings.bolna_webhook_ips:
            raise HTTPException(status_code=403, detail="Webhook source IP is not allowlisted.")

    if not settings.webhook_secret:
        raise HTTPException(
            status_code=503, detail="WEBHOOK_SECRET must be configured before accepting callbacks."
        )
    provided = request.headers.get("x-webhook-secret", "")
    if not hmac.compare_digest(provided, settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret.")

    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be a JSON object.")

    try:
        info = extract_execution_fields(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not info["execution_id"] or not info["status"]:
        raise HTTPException(
            status_code=400, detail="Webhook payload is missing id/execution_id or status."
        )
    user_data = payload.get("user_data") or {}
    if not isinstance(user_data, dict):
        raise HTTPException(status_code=400, detail="Webhook user_data must be an object.")
    org_id = str(user_data.get("org_id") or settings.default_org_id)
    should_process = upsert_call_webhook(
        execution_id=info["execution_id"],
        org_id=org_id,
        status=info["status"],
        raw_payload=payload,
        duration=info["conversation_duration"],
        total_cost=info["total_cost"],
        cost_breakdown=info["cost_breakdown"],
        session_id=info["session_id"],
    )
    if should_process:
        background_tasks.add_task(process_and_finalize, org_id, payload)
    return {"ok": True, "accepted": True, "processed": should_process}


def process_and_finalize(org_id: str, payload: dict[str, Any]) -> None:
    execution_id = str(payload.get("id") or payload.get("execution_id") or "")
    status = str(payload.get("status") or "")
    try:
        process_workflow_terminal(org_id, payload)
    except Exception:
        logger.exception("Failed to process completed Bolna execution %s", execution_id)
        finish_completed_call(execution_id, succeeded=False, status=status)
        return
    if status in {"no-answer", "busy", "failed"}:
        termination = str(payload.get("termination_reason") or "").casefold()
        telephony = payload.get("telephony_data") or {}
        hangup_reason = (
            str(telephony.get("hangup_reason") or "").casefold()
            if isinstance(telephony, dict)
            else ""
        )
        if "voicemail" not in termination and "voicemail" not in hangup_reason:
            schedule_close_retry(execution_id)
    finish_completed_call(execution_id, succeeded=True, status=status)
