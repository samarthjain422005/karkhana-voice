import hmac
import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from apps.api.bolna import BolnaError
from apps.api.config import get_settings
from apps.api.orchestrator import (
    WorkflowError,
    acknowledge_incident_manually,
    escalation_for_incident,
    scheduler_loop,
    run_scheduler_once,
    start_workflow_call,
)
from apps.api.routes.tools import router as tools_router
from apps.api.routes.webhooks import router as webhooks_router
from apps.api.store import (
    add_owner_signal,
    get_or_create_opted_in_person,
    get_purchase_order_context,
    init_db,
    list_approvals,
    list_open_purchase_orders,
    list_people,
    list_pending_handovers,
    list_recent_calls_and_events,
    list_recent_incidents,
    record_demo_call_attempt,
    register_incident,
    register_supplier_consent,
    update_incident_call_status,
)
from apps.api.watchtower import compute_watchtower
from scripts.seed_demo import seed_aarav_pumps

logger = logging.getLogger(__name__)
WEB_INDEX_PATH = Path(__file__).resolve().parents[1] / "web" / "index.html"
PHONE_PATTERN = r"^\+[1-9]\d{8,14}$"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_aarav_pumps()
    if os.getenv("VERCEL") == "1":
        if not get_settings().database_url.startswith(
            ("postgres://", "postgresql://", "postgresql+psycopg://")
        ):
            raise RuntimeError(
                "Vercel requires a persistent PostgreSQL DATABASE_URL; SQLite is ephemeral."
            )
        yield
        return
    scheduler_task = asyncio.create_task(scheduler_loop())
    app.state.scheduler_task = scheduler_task
    try:
        yield
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Karkhana Voice API", version="1.1.0", lifespan=lifespan)
app.include_router(webhooks_router)
app.include_router(tools_router)


@app.get("/api/cron")
def scheduled_workflows(request: Request) -> dict[str, bool]:
    secret = get_settings().cron_secret
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET is not configured.")
    provided = request.headers.get("authorization", "")
    expected = f"Bearer {secret}"
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid scheduler authorization.")
    run_scheduler_once()
    return {"ok": True}


class WorkflowCallRequest(BaseModel):
    agent: Literal["close", "open"]
    mode: Literal["shift_close", "opening_count", "morning_brief", "handover_brief"]
    phone: str = Field(pattern=PHONE_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    role: Literal[
        "floor_manager", "store_keeper", "supervisor", "owner", "purchaser"
    ]
    recipient_opted_in: bool = False
    call_window: str = Field(default="08:00-21:00", pattern=r"^\d{2}:\d{2}-\d{2}:\d{2}$")


class BreakdownRequest(BaseModel):
    machine: str = Field(min_length=1, max_length=100)
    technician_name: str = Field(min_length=1, max_length=80)
    technician_phone: str = Field(pattern=PHONE_PATTERN)
    technician_opted_in: bool = False
    supervisor_name: str = Field(min_length=1, max_length=80)
    supervisor_phone: str = Field(pattern=PHONE_PATTERN)
    supervisor_opted_in: bool = False


class SupplierEtaRequest(BaseModel):
    po_id: str = Field(min_length=1, max_length=80)
    supplier_phone: str = Field(pattern=PHONE_PATTERN)
    supplier_opted_in: bool = False
    call_window: str = Field(default="08:00-21:00", pattern=r"^\d{2}:\d{2}-\d{2}:\d{2}$")


class ManualAckRequest(BaseModel):
    note: str = Field(min_length=1, max_length=300)


class OwnerNoteRequest(BaseModel):
    supplier_name: str = Field(min_length=1, max_length=100)
    delay_days: int = Field(default=4, ge=0, le=30)


def _record_demo_limit(org_id: str, phone: str, request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    allowed, reason = record_demo_call_attempt(org_id, phone, client_ip)
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)


def _workflow_error(exc: Exception, status_code: int = 503) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


def _validate_workflow_role(agent: str, mode: str, role: str) -> None:
    expected = {
        ("close", "shift_close"): {"floor_manager", "store_keeper", "supervisor"},
        ("close", "opening_count"): {"floor_manager", "store_keeper"},
        ("open", "morning_brief"): {"owner", "purchaser"},
        ("open", "handover_brief"): {"supervisor"},
    }
    if role not in expected.get((agent, mode), set()):
        raise HTTPException(
            status_code=422,
            detail=f"Role '{role}' cannot receive the {agent}/{mode} workflow.",
        )


@app.get("/", response_class=HTMLResponse)
def control_room() -> HTMLResponse:
    return HTMLResponse(WEB_INDEX_PATH.read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    configured = {
        "close": bool(settings.bolna_agent_id_close),
        "open": bool(settings.bolna_agent_id_open),
        "alert": bool(settings.bolna_agent_id_alert),
    }
    return {"status": "ok", "service": "karkhana-voice", "agents": str(configured)}


@app.get("/api/agents")
def get_agents() -> list[dict[str, Any]]:
    settings = get_settings()
    return [
        {
            "agent": key,
            "configured": bool(getattr(settings, setting_name)),
            "agent_id": getattr(settings, setting_name),
            "prompt_version": getattr(settings, version_name),
        }
        for key, setting_name, version_name in (
            ("close", "bolna_agent_id_close", "prompt_version_close"),
            ("open", "bolna_agent_id_open", "prompt_version_open"),
            ("alert", "bolna_agent_id_alert", "prompt_version_alert"),
        )
    ]


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    org_id = get_settings().default_org_id
    return {
        **list_recent_calls_and_events(org_id),
        "incidents": list_recent_incidents(org_id),
        "handovers": [
            item.model_dump(mode="json") for item in list_pending_handovers(org_id, 10)
        ],
        "approvals": list_approvals(org_id),
        "people": [
            {
                "id": person.id,
                "name": person.name,
                "role": person.role,
                "opted_in": person.opted_in,
                "call_window": person.call_window,
            }
            for person in list_people(org_id)
        ],
        "purchase_orders": list_open_purchase_orders(org_id),
    }


@app.get("/api/watchtower")
def get_watchtower() -> dict[str, Any]:
    return compute_watchtower(get_settings().default_org_id)


@app.post("/api/demo/owner-note")
def create_owner_note(payload: OwnerNoteRequest) -> dict[str, Any]:
    org_id = get_settings().default_org_id
    try:
        supplier = add_owner_signal(org_id, payload.supplier_name, payload.delay_days)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier was not found.")
    return {"ok": True, "message": f"Added a +{payload.delay_days}d signal for {supplier}."}


@app.post("/api/workflow/call")
def workflow_call(payload: WorkflowCallRequest, request: Request) -> dict[str, Any]:
    _validate_workflow_role(payload.agent, payload.mode, payload.role)
    if not payload.recipient_opted_in:
        raise HTTPException(
            status_code=400, detail="Recipient's explicit opt-in is required."
        )
    settings = get_settings()
    _record_demo_limit(settings.default_org_id, payload.phone, request)
    person = get_or_create_opted_in_person(
        settings.default_org_id,
        payload.phone,
        payload.name.strip(),
        payload.role,
        "workflow_form_recipient_opt_in",
        payload.call_window,
    )
    try:
        result = start_workflow_call(
            settings.default_org_id, payload.agent, payload.mode, person
        )
    except (WorkflowError, BolnaError, ValueError) as exc:
        raise _workflow_error(exc) from exc
    return {"ok": True, "agent": payload.agent, "mode": payload.mode, **result}


@app.post("/api/incidents")
def report_breakdown(payload: BreakdownRequest, request: Request) -> dict[str, Any]:
    if not payload.technician_opted_in or not payload.supervisor_opted_in:
        raise HTTPException(
            status_code=400,
            detail="Both technician and supervisor must explicitly opt in before dispatch.",
        )
    settings = get_settings()
    _record_demo_limit(settings.default_org_id, payload.technician_phone, request)
    _record_demo_limit(settings.default_org_id, payload.supervisor_phone, request)
    technician = get_or_create_opted_in_person(
        settings.default_org_id,
        payload.technician_phone,
        payload.technician_name.strip(),
        "technician",
        "breakdown_dispatch_explicit_opt_in",
    )
    supervisor = get_or_create_opted_in_person(
        settings.default_org_id,
        payload.supervisor_phone,
        payload.supervisor_name.strip(),
        "supervisor",
        "breakdown_escalation_explicit_opt_in",
    )
    incident_id = f"inc_{uuid.uuid4().hex[:12]}"
    incident = register_incident(
        org_id=settings.default_org_id,
        incident_id=incident_id,
        machine=payload.machine.strip(),
        technician_name=technician.name,
        technician_phone=technician.phone,
        supervisor_name=supervisor.name,
        supervisor_phone=supervisor.phone,
        technician_person_id=technician.id,
        supervisor_person_id=supervisor.id,
        escalation_delay_seconds=settings.demo_escalation_seconds,
    )
    try:
        call = start_workflow_call(
            settings.default_org_id,
            "alert",
            "breakdown_dispatch",
            technician,
            {"incident_id": incident.id, "machine": incident.machine, "audience": "technician"},
        )
    except (WorkflowError, BolnaError, ValueError) as exc:
        update_incident_call_status(incident.id, "technician", "failed_to_place")
        escalation_for_incident(incident.id)
        raise HTTPException(
            status_code=503,
            detail={"message": str(exc), "incident_id": incident.id},
        ) from exc
    from datetime import timedelta
    from apps.api.store import set_incident_technician_execution, utc_now

    set_incident_technician_execution(
        incident.id,
        call["execution_id"],
        utc_now() + timedelta(seconds=settings.demo_escalation_seconds),
    )
    return {
        "ok": True,
        "incident_id": incident.id,
        "execution_id": call["execution_id"],
        "status": "technician_call_queued",
    }


@app.post("/api/incidents/{incident_id}/ack")
def acknowledge_incident(incident_id: str, payload: ManualAckRequest) -> dict[str, Any]:
    try:
        acknowledge_incident_manually(incident_id, payload.note.strip())
    except WorkflowError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "incident_id": incident_id, "status": "acknowledged_by_human"}


@app.post("/api/supplier-eta")
def confirm_supplier_eta(payload: SupplierEtaRequest, request: Request) -> dict[str, Any]:
    if not payload.supplier_opted_in:
        raise HTTPException(
            status_code=400, detail="Supplier's explicit opt-in is required."
        )
    settings = get_settings()
    context = get_purchase_order_context(settings.default_org_id, payload.po_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Open purchase order was not found.")
    _record_demo_limit(settings.default_org_id, payload.supplier_phone, request)
    supplier = register_supplier_consent(
        settings.default_org_id,
        int(context["supplier_id"]),
        payload.supplier_phone,
        "supplier_eta_explicit_opt_in",
    )
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier was not found.")
    person = get_or_create_opted_in_person(
        settings.default_org_id,
        payload.supplier_phone,
        supplier.name,
        "supplier",
        "supplier_eta_explicit_opt_in",
        payload.call_window,
    )
    try:
        call = start_workflow_call(
            settings.default_org_id,
            "alert",
            "supplier_eta",
            person,
            {
                "po_id": context["id"],
                "part_name": context["part_name"],
                "part_sku": context["part_sku"],
                "expected_eta_date": context["eta_date"],
                "supplier_name": supplier.name,
                "audience": "supplier",
            },
        )
    except (WorkflowError, BolnaError, ValueError) as exc:
        raise _workflow_error(exc) from exc
    return {
        "ok": True,
        "agent": "alert",
        "mode": "supplier_eta",
        "purchase_order": context["id"],
        **call,
    }
