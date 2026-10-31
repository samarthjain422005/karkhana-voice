import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlmodel import Field, Session, SQLModel, create_engine, select

from apps.api.config import get_settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Part(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    sku: str = Field(index=True)
    name: str
    aliases_json: str = "[]"
    unit: str = "piece"
    unit_cost: float | None = None
    lead_time_days: int = 1
    typical_qty: int = 100


class Supplier(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    name: str
    on_time_count: int = 0
    total_po_count: int = 0
    avg_slip_days: int = 0
    contact_phone: str = ""
    opted_in: bool = False
    consent_at: datetime | None = None
    consent_method: str = "none"


class PartSupplier(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    part_id: int = Field(index=True)
    supplier_id: int = Field(index=True)


class PurchaseOrder(SQLModel, table=True):
    id: str = Field(primary_key=True)
    org_id: str = Field(index=True)
    part_id: int = Field(index=True)
    supplier_id: int = Field(index=True)
    qty: int
    promised_date: date
    eta_date: date
    status: str = "open"


class Product(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    code: str = Field(index=True)
    name: str


class BOMItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    product_id: int = Field(index=True)
    part_id: int = Field(index=True)
    qty_per_unit: int


class WorkOrder(SQLModel, table=True):
    id: str = Field(primary_key=True)
    org_id: str = Field(index=True)
    product_id: int = Field(index=True)
    qty: int
    start_date: date
    due_date: date


class Person(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    name: str
    phone: str = Field(index=True)
    role: str = "floor_manager"
    language: str = "hi"
    call_window: str = "08:00-21:00"
    opted_in: bool = False
    consent_at: datetime | None = None
    consent_method: str = "none"


class CallRecord(SQLModel, table=True):
    execution_id: str = Field(primary_key=True)
    org_id: str = Field(index=True)
    agent: str = "close"
    mode: str = "reconcile"
    person_id: int | None = Field(default=None, index=True)
    session_id: str = Field(default="", index=True)
    status: str = Field(default="queued", index=True)
    raw_payload: str = "{}"
    prompt_version: str = "close-v1.0"
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    duration: float = 0.0
    total_cost: float = 0.0
    cost_breakdown: str = "{}"
    completed_processed: bool = False
    completed_claimed: bool = False
    terminal_processed: bool = False
    retry_count: int = 0
    retry_at: datetime | None = None
    retry_claimed: bool = False
    retry_execution_id: str = ""
    reconciled_at: datetime | None = None


class HandoverItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    execution_id: str | None = Field(default=None, index=True)
    text: str
    severity: str = "normal"
    from_person: int | None = None
    acked_by: int | None = None
    acked_at: datetime | None = None
    ts: datetime = Field(default_factory=utc_now, index=True)


class Approval(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    execution_id: str = Field(index=True)
    part_id: int = Field(index=True)
    decision: str
    by_person: int | None = None
    ts: datetime = Field(default_factory=utc_now)


class Incident(SQLModel, table=True):
    id: str = Field(primary_key=True)
    org_id: str = Field(index=True)
    machine: str
    reported_at: datetime = Field(default_factory=utc_now, index=True)
    ack_at: datetime | None = None
    escalated_at: datetime | None = None
    resolved_at: datetime | None = None
    technician_phone: str
    supervisor_phone: str
    technician_name: str
    supervisor_name: str
    technician_person_id: int | None = None
    supervisor_person_id: int | None = None
    technician_execution_id: str = ""
    supervisor_execution_id: str = ""
    technician_consent: bool = False
    supervisor_consent: bool = False
    technician_status: str = "pending"
    supervisor_status: str = "pending"
    technician_eta_minutes: int | None = None
    escalation_level: int = 0
    escalation_due_at: datetime | None = None
    ack_note: str = ""
    ack_notified: bool = False


class DailyJob(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    person_id: int = Field(index=True)
    job_date: date = Field(index=True)
    job_type: str
    status: str = "queued"
    execution_id: str = ""


class LedgerEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    execution_id: str | None = Field(default=None, index=True)
    source_key: str | None = Field(default=None, unique=True)
    type: str
    part_id: int = Field(index=True)
    qty: int
    unit: str
    state: str = Field(default="proposed", index=True)
    source: str = "voice"
    guardrail_flags: str = "[]"
    ts: datetime = Field(default_factory=utc_now, index=True)


class ProductionOutput(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    execution_id: str = Field(index=True)
    source_key: str = Field(unique=True)
    product_code: str
    qty: int
    unit: str = "piece"
    state: str = Field(default="confirmed", index=True)
    guardrail_flags: str = "[]"
    ts: datetime = Field(default_factory=utc_now, index=True)


class DemoLimit(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    phone_hash: str = Field(index=True)
    ip_hash: str = Field(index=True)
    count: int = 0
    window_start: date = Field(index=True)


class Signal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    supplier_id: int = Field(index=True)
    delay_days: int = 0
    note: str = ""
    expires_at: datetime
    source_execution_id: str | None = None


class AuditLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    org_id: str = Field(index=True)
    actor: str
    action: str
    target: str
    ts: datetime = Field(default_factory=utc_now)


_ENGINE = None
TERMINAL_CALL_STATUSES = {
    "completed",
    "no-answer",
    "busy",
    "failed",
    "canceled",
    "stopped",
    "error",
    "balance-low",
}


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        database_url = get_settings().database_url
        if database_url.startswith("postgres://"):
            database_url = database_url.replace(
                "postgres://", "postgresql+psycopg://", 1
            )
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace(
                "postgresql://", "postgresql+psycopg://", 1
            )
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        _ENGINE = create_engine(database_url, connect_args=connect_args)
    return _ENGINE


def reset_engine_for_tests() -> None:
    global _ENGINE
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Session:
    return Session(get_engine())


def get_on_hand_qty(org_id: str, part_id: int) -> int:
    with get_session() as session:
        events = session.exec(
            select(LedgerEvent).where(
                LedgerEvent.org_id == org_id,
                LedgerEvent.part_id == part_id,
                LedgerEvent.state == "confirmed",
            )
        ).all()
    return sum(event.qty for event in events)


def find_part_by_sku_or_alias(org_id: str, token: str) -> Part | None:
    cleaned = token.strip().casefold()
    if not cleaned:
        return None
    with get_session() as session:
        parts = session.exec(select(Part).where(Part.org_id == org_id)).all()
    for part in parts:
        aliases = [alias.casefold() for alias in json.loads(part.aliases_json)]
        if cleaned == part.sku.casefold() or cleaned == part.name.casefold() or cleaned in aliases:
            return part
    for part in parts:
        aliases = json.loads(part.aliases_json)
        if cleaned in part.name.casefold() or any(cleaned in alias.casefold() for alias in aliases):
            return part
    return None


def list_recent_calls_and_events(org_id: str, limit: int = 10) -> dict[str, Any]:
    with get_session() as session:
        calls = session.exec(
            select(CallRecord)
            .where(CallRecord.org_id == org_id)
            .order_by(CallRecord.started_at.desc())
            .limit(limit)
        ).all()
        events = session.exec(
            select(LedgerEvent)
            .where(LedgerEvent.org_id == org_id)
            .order_by(LedgerEvent.ts.desc())
            .limit(limit * 3)
        ).all()
        production_outputs = session.exec(
            select(ProductionOutput)
            .where(ProductionOutput.org_id == org_id)
            .order_by(ProductionOutput.ts.desc())
            .limit(limit)
        ).all()
        parts = session.exec(select(Part).where(Part.org_id == org_id)).all()
    labels = {part.id: f"{part.sku} {part.name}" for part in parts}
    safe_calls = []
    for call in calls:
        payload = json.loads(call.raw_payload or "{}")
        transcript = str(payload.get("transcript") or "")
        transcript = re.sub(
            r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)",
            "[REDACTED NUMBER]",
            transcript,
        )
        safe_calls.append(
            {
                "execution_id": call.execution_id,
                "agent": call.agent,
                "mode": call.mode,
                "status": call.status,
                "prompt_version": call.prompt_version,
                "started_at": call.started_at.isoformat(),
                "completed_at": call.completed_at.isoformat()
                if call.completed_at
                else None,
                "duration": call.duration,
                "total_cost": call.total_cost,
                "transcript": transcript,
            }
        )
    return {
        "org_id": org_id,
        "synthetic_label": "SYNTHETIC DEMO DATASET — AARAV PUMPS",
        "stock_summary": [
            {
                "sku": part.sku,
                "name": part.name,
                "unit": part.unit,
                "on_hand": get_on_hand_qty(org_id, part.id),
            }
            for part in parts
            if part.id is not None
        ],
        "calls": safe_calls,
        "events": [
            {
                **event.model_dump(mode="json"),
                "part_label": labels.get(event.part_id, f"Part #{event.part_id}"),
            }
            for event in events
        ],
        "production_outputs": [
            output.model_dump(mode="json") for output in production_outputs
        ],
    }


def register_queued_call(
    execution_id: str,
    org_id: str,
    person_id: int | None,
    session_id: str,
    raw_payload: dict[str, Any],
    agent: str = "close",
    mode: str = "reconcile",
    retry_count: int = 0,
) -> None:
    with get_session() as session:
        if session.get(CallRecord, execution_id) is not None:
            return
        session.add(
            CallRecord(
                execution_id=execution_id,
                org_id=org_id,
                agent=agent,
                mode=mode,
                person_id=person_id,
                session_id=session_id,
                raw_payload=json.dumps(raw_payload),
                prompt_version=getattr(
                    get_settings(),
                    f"prompt_version_{agent}",
                    get_settings().prompt_version_close,
                ),
                retry_count=retry_count,
            )
        )
        session.commit()


def upsert_call_webhook(
    execution_id: str,
    org_id: str,
    status: str,
    raw_payload: dict[str, Any],
    duration: float = 0.0,
    total_cost: float = 0.0,
    cost_breakdown: dict[str, Any] | None = None,
    session_id: str = "",
) -> bool:
    """Persist every status; atomically claim completed-call processing once."""
    with get_session() as session:
        record = session.get(CallRecord, execution_id)
        if record is None:
            record = CallRecord(
                execution_id=execution_id,
                org_id=org_id,
                session_id=session_id,
                prompt_version=get_settings().prompt_version_close,
            )
            session.add(record)
        previous_status = record.status
        if previous_status == "completed" and status != "completed":
            session.commit()
            return False
        record.status = status
        record.raw_payload = json.dumps(raw_payload)
        if session_id and not record.session_id:
            record.session_id = session_id
        if status not in TERMINAL_CALL_STATUSES:
            session.add(record)
            session.commit()
            return False
        if record.terminal_processed or record.completed_claimed:
            session.add(record)
            session.commit()
            return False
        if status == "completed":
            record.duration = duration
            record.total_cost = total_cost
            record.cost_breakdown = json.dumps(cost_breakdown or {})
            record.completed_at = record.completed_at or utc_now()
        record.completed_claimed = True
        session.add(record)
        session.commit()
        return True


def finish_completed_call(
    execution_id: str, succeeded: bool, status: str = "completed"
) -> None:
    with get_session() as session:
        record = session.get(CallRecord, execution_id)
        if record is None:
            return
        record.completed_claimed = False
        record.terminal_processed = succeeded
        if status == "completed":
            record.completed_processed = succeeded
        session.add(record)
        session.commit()


def schedule_close_retry(execution_id: str, delay_seconds: int = 60) -> bool:
    with get_session() as session:
        record = session.get(CallRecord, execution_id)
        if (
            record is None
            or record.agent != "close"
            or record.retry_count >= 2
            or record.retry_at is not None
            or record.person_id is None
            or record.status not in {"no-answer", "busy", "failed"}
        ):
            return False
        record.retry_count += 1
        record.retry_at = utc_now() + timedelta(seconds=delay_seconds)
        session.add(record)
        session.commit()
        return True


def get_due_close_retries(now: datetime | None = None) -> list[CallRecord]:
    now = now or utc_now()
    with get_session() as session:
        return session.exec(
            select(CallRecord).where(
                CallRecord.agent == "close",
                CallRecord.retry_at.is_not(None),
                CallRecord.retry_at <= now,
                CallRecord.retry_claimed.is_(False),
            )
        ).all()


def claim_close_retry(execution_id: str) -> CallRecord | None:
    with get_session() as session:
        record = session.get(CallRecord, execution_id)
        if record is None or record.retry_claimed or record.retry_at is None:
            return None
        record.retry_claimed = True
        session.add(record)
        session.commit()
        session.refresh(record)
        return record


def complete_close_retry(
    execution_id: str, new_execution_id: str = "", failed: bool = False
) -> None:
    with get_session() as session:
        record = session.get(CallRecord, execution_id)
        if record is None:
            return
        record.retry_claimed = False
        record.retry_at = None
        record.retry_execution_id = new_execution_id
        if failed:
            record.status = "retry_failed"
        session.add(record)
        session.commit()


def get_stuck_calls(
    older_than: datetime, reconciled_before: datetime, limit: int = 50
) -> list[CallRecord]:
    terminal_statuses = list(TERMINAL_CALL_STATUSES)
    with get_session() as session:
        statement = select(CallRecord).where(
            CallRecord.started_at <= older_than,
            CallRecord.status.not_in(terminal_statuses),
        )
        statement = statement.where(
            (CallRecord.reconciled_at.is_(None))
            | (CallRecord.reconciled_at <= reconciled_before)
        )
        return session.exec(statement.order_by(CallRecord.started_at).limit(limit)).all()


def mark_call_reconciled(execution_id: str) -> None:
    with get_session() as session:
        record = session.get(CallRecord, execution_id)
        if record is None:
            return
        record.reconciled_at = utc_now()
        session.add(record)
        session.commit()


def append_event(
    org_id: str,
    execution_id: str | None,
    source_key: str | None,
    event_type: str,
    part_id: int,
    qty: int,
    unit: str,
    state: str,
    source: str = "voice",
    guardrail_flags: list[str] | None = None,
) -> None:
    with get_session() as session:
        if source_key and session.exec(
            select(LedgerEvent).where(LedgerEvent.source_key == source_key)
        ).first():
            return
        session.add(
            LedgerEvent(
                org_id=org_id,
                execution_id=execution_id,
                source_key=source_key,
                type=event_type,
                part_id=part_id,
                qty=qty,
                unit=unit,
                state=state,
                source=source,
                guardrail_flags=json.dumps(guardrail_flags or []),
            )
        )
        session.add(
            AuditLog(
                org_id=org_id,
                actor=f"call:{execution_id}" if execution_id else "system",
                action=f"append_event:{event_type}:{state}",
                target=f"part:{part_id}:qty:{qty}",
            )
        )
        session.commit()


def record_production_output(
    org_id: str,
    execution_id: str,
    source_key: str,
    product_code: str,
    qty: int,
    unit: str,
) -> tuple[str, list[str]]:
    if qty <= 0:
        raise ValueError("Production output quantity must be positive.")
    with get_session() as session:
        if session.exec(
            select(ProductionOutput).where(
                ProductionOutput.source_key == source_key
            )
        ).first():
            return "duplicate", []
        product = session.exec(
            select(Product).where(
                Product.org_id == org_id, Product.code == product_code
            )
        ).first()
        if product is None or product.id is None:
            raise ValueError(f"Unknown product code: {product_code}.")
        work_orders = session.exec(
            select(WorkOrder).where(
                WorkOrder.org_id == org_id, WorkOrder.product_id == product.id
            )
        ).all()
        maximum_order_qty = max((order.qty for order in work_orders), default=0)
        flags = (
            ["production_qty_spike"]
            if maximum_order_qty and qty > maximum_order_qty * 10
            else []
        )
        state = "needs_review" if flags else "confirmed"
        session.add(
            ProductionOutput(
                org_id=org_id,
                execution_id=execution_id,
                source_key=source_key,
                product_code=product.code,
                qty=qty,
                unit=unit,
                state=state,
                guardrail_flags=json.dumps(flags),
            )
        )
        session.add(
            AuditLog(
                org_id=org_id,
                actor=f"call:{execution_id}",
                action=f"record_production_output:{state}",
                target=f"product:{product.code}:qty:{qty}",
            )
        )
        session.commit()
        return state, flags


def get_watchtower_inputs(org_id: str) -> dict[str, Any]:
    with get_session() as session:
        parts = session.exec(select(Part).where(Part.org_id == org_id)).all()
        suppliers = session.exec(select(Supplier).where(Supplier.org_id == org_id)).all()
        links = session.exec(select(PartSupplier).where(PartSupplier.org_id == org_id)).all()
        orders = session.exec(
            select(PurchaseOrder).where(
                PurchaseOrder.org_id == org_id, PurchaseOrder.status == "open"
            )
        ).all()
        products = session.exec(select(Product).where(Product.org_id == org_id)).all()
        bom = session.exec(select(BOMItem).where(BOMItem.org_id == org_id)).all()
        work_orders = session.exec(select(WorkOrder).where(WorkOrder.org_id == org_id)).all()
        events = session.exec(
            select(LedgerEvent).where(
                LedgerEvent.org_id == org_id, LedgerEvent.state == "confirmed"
            )
        ).all()
        signals = session.exec(
            select(Signal).where(Signal.org_id == org_id, Signal.expires_at > utc_now())
        ).all()
        incidents = session.exec(
            select(Incident).where(Incident.org_id == org_id)
        ).all()
        handovers = session.exec(
            select(HandoverItem).where(
                HandoverItem.org_id == org_id,
                HandoverItem.acked_at.is_(None),
            )
        ).all()
    return {
        "parts": parts,
        "suppliers": suppliers,
        "links": links,
        "orders": orders,
        "products": products,
        "bom": bom,
        "work_orders": work_orders,
        "events": events,
        "signals": signals,
        "incidents": incidents,
        "handovers": handovers,
    }


def get_bom_for_product(org_id: str, product_code: str) -> list[tuple[Part, int]]:
    with get_session() as session:
        product = session.exec(
            select(Product).where(
                Product.org_id == org_id, Product.code == product_code
            )
        ).first()
        if product is None or product.id is None:
            return []
        rows = session.exec(
            select(BOMItem).where(
                BOMItem.org_id == org_id, BOMItem.product_id == product.id
            )
        ).all()
        result: list[tuple[Part, int]] = []
        for row in rows:
            part = session.get(Part, row.part_id)
            if part is not None and part.org_id == org_id:
                result.append((part, row.qty_per_unit))
        return result


def add_owner_signal(
    org_id: str,
    supplier_query: str,
    delay_days: int,
    note: str = "",
    source_execution_id: str | None = None,
) -> str | None:
    if delay_days < 0 or delay_days > 30:
        raise ValueError("Delay must be between 0 and 30 days.")
    with get_session() as session:
        suppliers = session.exec(select(Supplier).where(Supplier.org_id == org_id)).all()
        supplier = next(
            (s for s in suppliers if supplier_query.strip().casefold() in s.name.casefold()),
            None,
        )
        if supplier is None or supplier.id is None:
            return None
        session.add(
            Signal(
                org_id=org_id,
                supplier_id=supplier.id,
                delay_days=delay_days,
                note=note.strip() or f"Owner note: {supplier.name} delayed +{delay_days}d",
                expires_at=utc_now() + timedelta(days=7),
                source_execution_id=source_execution_id,
            )
        )
        session.commit()
        return supplier.name


def get_or_create_opted_in_person(
    org_id: str,
    phone: str,
    name: str,
    role: str,
    consent_method: str,
    call_window: str = "08:00-21:00",
) -> Person:
    with get_session() as session:
        person = session.exec(
            select(Person).where(Person.org_id == org_id, Person.phone == phone)
        ).first()
        if person is None:
            person = Person(
                org_id=org_id,
                name=name,
                phone=phone,
                role=role,
                opted_in=True,
                consent_at=utc_now(),
                consent_method=consent_method,
                call_window=call_window,
            )
        else:
            person.name = name
            person.role = role
            person.call_window = call_window
            person.opted_in = True
            person.consent_at = utc_now()
            person.consent_method = consent_method
        session.add(person)
        session.commit()
        session.refresh(person)
        return person


def get_person(person_id: int) -> Person | None:
    with get_session() as session:
        return session.get(Person, person_id)


def list_people(org_id: str) -> list[Person]:
    with get_session() as session:
        return session.exec(
            select(Person)
            .where(Person.org_id == org_id)
            .order_by(Person.name)
        ).all()


def list_opted_in_people(org_id: str, roles: list[str] | None = None) -> list[Person]:
    with get_session() as session:
        statement = select(Person).where(
            Person.org_id == org_id,
            Person.opted_in.is_(True),
            Person.consent_at.is_not(None),
        )
        if roles:
            statement = statement.where(Person.role.in_(roles))
        return session.exec(statement.order_by(Person.name)).all()


def register_incident(
    org_id: str,
    incident_id: str,
    machine: str,
    technician_name: str,
    technician_phone: str,
    supervisor_name: str,
    supervisor_phone: str,
    technician_person_id: int,
    supervisor_person_id: int,
    escalation_delay_seconds: int = 60,
) -> Incident:
    incident = Incident(
        id=incident_id,
        org_id=org_id,
        machine=machine,
        technician_name=technician_name,
        technician_phone=technician_phone,
        supervisor_name=supervisor_name,
        supervisor_phone=supervisor_phone,
        technician_person_id=technician_person_id,
        supervisor_person_id=supervisor_person_id,
        technician_consent=True,
        supervisor_consent=True,
        escalation_due_at=utc_now() + timedelta(seconds=escalation_delay_seconds),
    )
    with get_session() as session:
        session.add(incident)
        session.add(
            AuditLog(
                org_id=org_id,
                actor="control-room",
                action="incident_reported",
                target=f"incident:{incident_id}:machine:{machine}",
            )
        )
        session.commit()
        session.refresh(incident)
        return incident


def get_incident(incident_id: str) -> Incident | None:
    with get_session() as session:
        return session.get(Incident, incident_id)


def set_incident_technician_execution(
    incident_id: str, execution_id: str, due_at: datetime
) -> None:
    with get_session() as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise ValueError(f"Incident {incident_id} does not exist.")
        incident.technician_execution_id = execution_id
        incident.technician_status = "queued"
        incident.escalation_due_at = due_at
        session.add(incident)
        session.commit()


def set_incident_supervisor_execution(
    incident_id: str, execution_id: str
) -> None:
    with get_session() as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise ValueError(f"Incident {incident_id} does not exist.")
        incident.supervisor_execution_id = execution_id
        incident.supervisor_status = "queued"
        incident.escalation_level = 1
        incident.escalated_at = utc_now()
        incident.escalation_due_at = None
        session.add(incident)
        session.add(
            AuditLog(
                org_id=incident.org_id,
                actor="orchestrator",
                action="incident_escalated",
                target=f"incident:{incident_id}:supervisor",
            )
        )
        session.commit()


def claim_incident_escalation(incident_id: str) -> Incident | None:
    with get_session() as session:
        incident = session.get(Incident, incident_id)
        if (
            incident is None
            or incident.resolved_at is not None
            or incident.escalated_at is not None
            or incident.supervisor_execution_id
        ):
            return None
        incident.escalated_at = utc_now()
        incident.escalation_level = 1
        incident.escalation_due_at = None
        session.add(incident)
        session.add(
            AuditLog(
                org_id=incident.org_id,
                actor="orchestrator",
                action="incident_escalation_claimed",
                target=f"incident:{incident_id}:supervisor",
            )
        )
        session.commit()
        session.refresh(incident)
        return incident


def update_incident_call_status(incident_id: str, audience: str, status: str) -> None:
    with get_session() as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise ValueError(f"Incident {incident_id} does not exist.")
        if audience == "technician":
            incident.technician_status = status
        elif audience == "supervisor":
            incident.supervisor_status = status
        else:
            raise ValueError(f"Unknown incident audience: {audience}")
        session.add(incident)
        session.commit()


def acknowledge_incident(
    incident_id: str, audience: str, eta_minutes: int | None, note: str
) -> None:
    with get_session() as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise ValueError(f"Incident {incident_id} does not exist.")
        incident.ack_at = incident.ack_at or utc_now()
        incident.resolved_at = incident.ack_at
        incident.ack_note = note
        incident.escalation_due_at = None
        if audience == "technician":
            incident.technician_eta_minutes = eta_minutes
            incident.technician_status = "acknowledged"
        else:
            incident.supervisor_status = "acknowledged"
        session.add(incident)
        session.add(
            AuditLog(
                org_id=incident.org_id,
                actor=f"alert:{audience}",
                action="incident_acknowledged",
                target=f"incident:{incident_id}",
            )
        )
        session.commit()


def list_open_incidents(org_id: str) -> list[Incident]:
    with get_session() as session:
        return session.exec(
            select(Incident)
            .where(Incident.org_id == org_id, Incident.resolved_at.is_(None))
            .order_by(Incident.reported_at.desc())
        ).all()


def get_due_incidents(now: datetime | None = None) -> list[Incident]:
    now = now or utc_now()
    with get_session() as session:
        return session.exec(
            select(Incident).where(
                Incident.resolved_at.is_(None),
                Incident.escalated_at.is_(None),
                Incident.escalation_due_at.is_not(None),
                Incident.escalation_due_at <= now,
            )
        ).all()


def append_handover(
    org_id: str,
    execution_id: str,
    text: str,
    severity: str,
    from_person: int | None = None,
) -> HandoverItem:
    item = HandoverItem(
        org_id=org_id,
        execution_id=execution_id,
        text=text,
        severity=severity if severity in {"high", "normal"} else "normal",
        from_person=from_person,
    )
    with get_session() as session:
        session.add(item)
        session.add(
            AuditLog(
                org_id=org_id,
                actor=f"call:{execution_id}",
                action="handover_added",
                target=f"severity:{item.severity}",
            )
        )
        session.commit()
        session.refresh(item)
        return item


def list_pending_handovers(org_id: str, limit: int = 3) -> list[HandoverItem]:
    with get_session() as session:
        return session.exec(
            select(HandoverItem)
            .where(HandoverItem.org_id == org_id, HandoverItem.acked_at.is_(None))
            .order_by(HandoverItem.ts.desc())
            .limit(limit)
        ).all()


def acknowledge_handover(item_id: int, acked_by: int | None = None) -> bool:
    with get_session() as session:
        item = session.get(HandoverItem, item_id)
        if item is None or item.acked_at is not None:
            return False
        item.acked_by = acked_by
        item.acked_at = utc_now()
        session.add(item)
        session.add(
            AuditLog(
                org_id=item.org_id,
                actor=f"person:{acked_by}" if acked_by else "call",
                action="handover_acknowledged",
                target=f"handover:{item_id}",
            )
        )
        session.commit()
        return True


def record_approval(
    org_id: str,
    execution_id: str,
    part_token: str,
    decision: str,
    by_person: int | None = None,
) -> bool:
    if decision not in {"approve", "defer", "reject"}:
        raise ValueError("Approval decision must be approve, defer, or reject.")
    part = find_part_by_sku_or_alias(org_id, part_token)
    if part is None or part.id is None:
        return False
    with get_session() as session:
        session.add(
            Approval(
                org_id=org_id,
                execution_id=execution_id,
                part_id=part.id,
                decision=decision,
                by_person=by_person,
            )
        )
        session.add(
            AuditLog(
                org_id=org_id,
                actor=f"call:{execution_id}",
                action=f"purchase_suggestion_{decision}",
                target=f"part:{part.id}",
            )
        )
        session.commit()
    return True


def update_purchase_order_eta(
    org_id: str, execution_id: str, po_id: str, eta_date: date
) -> bool:
    with get_session() as session:
        order = session.get(PurchaseOrder, po_id)
        if order is None or order.org_id != org_id or order.status != "open":
            return False
        order.eta_date = eta_date
        session.add(order)
        session.add(
            AuditLog(
                org_id=org_id,
                actor=f"call:{execution_id}",
                action="supplier_eta_confirmed",
                target=f"po:{po_id}:eta:{eta_date.isoformat()}",
            )
        )
        session.commit()
    return True


def get_purchase_order_context(org_id: str, po_id: str) -> dict[str, Any] | None:
    with get_session() as session:
        order = session.get(PurchaseOrder, po_id)
        if order is None or order.org_id != org_id or order.status != "open":
            return None
        part = session.get(Part, order.part_id)
        supplier = session.get(Supplier, order.supplier_id)
    if part is None or supplier is None:
        return None
    return {
        "id": order.id,
        "eta_date": order.eta_date.isoformat(),
        "part_id": part.id,
        "part_name": part.name,
        "part_sku": part.sku,
        "supplier_id": supplier.id,
        "supplier_name": supplier.name,
        "supplier_phone": supplier.contact_phone,
        "supplier_opted_in": supplier.opted_in,
        "supplier_consent_at": supplier.consent_at.isoformat()
        if supplier.consent_at
        else None,
    }


def register_supplier_consent(
    org_id: str, supplier_id: int, phone: str, consent_method: str
) -> Supplier | None:
    with get_session() as session:
        supplier = session.get(Supplier, supplier_id)
        if supplier is None or supplier.org_id != org_id:
            return None
        supplier.contact_phone = phone
        supplier.opted_in = True
        supplier.consent_at = utc_now()
        supplier.consent_method = consent_method
        session.add(supplier)
        session.add(
            AuditLog(
                org_id=org_id,
                actor="supplier-consent",
                action="supplier_opt_in_recorded",
                target=f"supplier:{supplier_id}",
            )
        )
        session.commit()
        session.refresh(supplier)
        return supplier


def list_open_purchase_orders(org_id: str) -> list[dict[str, Any]]:
    with get_session() as session:
        orders = session.exec(
            select(PurchaseOrder).where(
                PurchaseOrder.org_id == org_id, PurchaseOrder.status == "open"
            )
        ).all()
    result: list[dict[str, Any]] = []
    for order in orders:
        context = get_purchase_order_context(org_id, order.id)
        if context:
            result.append(
                {
                    key: value
                    for key, value in context.items()
                    if key not in {"supplier_phone", "supplier_consent_at"}
                }
            )
    return result


def list_daily_brief_recipients(org_id: str) -> list[Person]:
    with get_session() as session:
        return session.exec(
            select(Person).where(
                Person.org_id == org_id,
                Person.opted_in.is_(True),
                Person.role.in_(["owner", "purchaser"]),
            )
        ).all()


def list_recent_incidents(org_id: str, limit: int = 10) -> list[dict[str, Any]]:
    with get_session() as session:
        incidents = session.exec(
            select(Incident)
            .where(Incident.org_id == org_id)
            .order_by(Incident.reported_at.desc())
            .limit(limit)
        ).all()
    return [
        {
            "id": incident.id,
            "machine": incident.machine,
            "reported_at": incident.reported_at.isoformat(),
            "ack_at": incident.ack_at.isoformat() if incident.ack_at else None,
            "escalated_at": incident.escalated_at.isoformat()
            if incident.escalated_at
            else None,
            "resolved_at": incident.resolved_at.isoformat()
            if incident.resolved_at
            else None,
            "technician_name": incident.technician_name,
            "supervisor_name": incident.supervisor_name,
            "technician_status": incident.technician_status,
            "supervisor_status": incident.supervisor_status,
            "technician_eta_minutes": incident.technician_eta_minutes,
            "escalation_level": incident.escalation_level,
            "ack_note": incident.ack_note,
        }
        for incident in incidents
    ]


def list_approvals(org_id: str, limit: int = 10) -> list[dict[str, Any]]:
    with get_session() as session:
        approvals = session.exec(
            select(Approval)
            .where(Approval.org_id == org_id)
            .order_by(Approval.ts.desc())
            .limit(limit)
        ).all()
        parts = session.exec(select(Part).where(Part.org_id == org_id)).all()
    labels = {part.id: f"{part.sku} {part.name}" for part in parts}
    return [
        {
            **approval.model_dump(mode="json"),
            "part_label": labels.get(approval.part_id, f"Part #{approval.part_id}"),
        }
        for approval in approvals
    ]


def create_daily_job_if_missing(
    org_id: str, person_id: int, job_date: date, job_type: str
) -> bool:
    with get_session() as session:
        existing = session.exec(
            select(DailyJob).where(
                DailyJob.org_id == org_id,
                DailyJob.person_id == person_id,
                DailyJob.job_date == job_date,
                DailyJob.job_type == job_type,
            )
        ).first()
        if existing is not None:
            return False
        session.add(
            DailyJob(
                org_id=org_id,
                person_id=person_id,
                job_date=job_date,
                job_type=job_type,
                status="scheduled",
            )
        )
        session.commit()
        return True


def update_daily_job(job_id: int, status: str, execution_id: str = "") -> None:
    with get_session() as session:
        job = session.get(DailyJob, job_id)
        if job is None:
            raise ValueError(f"Daily job {job_id} does not exist.")
        job.status = status
        job.execution_id = execution_id
        session.add(job)
        session.commit()


def record_demo_call_attempt(org_id: str, phone: str, client_ip: str) -> tuple[bool, str]:
    today = date.today()
    phone_hash = hashlib.sha256(phone.encode()).hexdigest()
    ip_hash = hashlib.sha256((client_ip or "unknown").encode()).hexdigest()
    settings = get_settings()
    with get_session() as session:
        rows = session.exec(
            select(DemoLimit).where(
                DemoLimit.org_id == org_id, DemoLimit.window_start == today
            )
        ).all()
        global_count = sum(row.count for row in rows)
        phone_count = sum(row.count for row in rows if row.phone_hash == phone_hash)
        ip_count = sum(row.count for row in rows if row.ip_hash == ip_hash)
        if global_count >= settings.demo_daily_cap:
            return False, "The demo's daily call limit has been reached."
        if phone_count >= settings.demo_per_phone_daily_cap:
            return False, "This number has reached today's demo call limit."
        if ip_count >= min(settings.demo_daily_cap, 5):
            return False, "This network has reached today's demo call limit."
        row = session.exec(
            select(DemoLimit).where(
                DemoLimit.org_id == org_id,
                DemoLimit.phone_hash == phone_hash,
                DemoLimit.ip_hash == ip_hash,
                DemoLimit.window_start == today,
            )
        ).first()
        if row is None:
            row = DemoLimit(
                org_id=org_id,
                phone_hash=phone_hash,
                ip_hash=ip_hash,
                window_start=today,
            )
        row.count += 1
        session.add(row)
        session.commit()
    return True, ""


def build_close_expected_context(org_id: str) -> dict[str, Any]:
    today = date.today()
    with get_session() as session:
        parts = session.exec(select(Part).where(Part.org_id == org_id)).all()
        open_orders = session.exec(
            select(PurchaseOrder).where(
                PurchaseOrder.org_id == org_id, PurchaseOrder.status == "open"
            )
        ).all()
    part_by_id = {part.id: part for part in parts}
    rows: list[str] = []
    seen: set[int] = set()
    for order in sorted(open_orders, key=lambda po: po.eta_date):
        part = part_by_id.get(order.part_id)
        if part is not None and order.eta_date <= today and part.id not in seen:
            rows.append(f"{part.sku} ({part.name}): {order.qty} {part.unit} expected today")
            seen.add(part.id)
    for sku in ("P-104", "P-105", "P-107", "P-102", "P-101"):
        part = next((p for p in parts if p.sku == sku), None)
        if part and part.id not in seen and len(rows) < 5:
            rows.append(f"{part.sku} ({part.name}): stock count due")
            seen.add(part.id)
    return {
        "factory_name": "Aarav Pumps (Synthetic Demo)",
        "product_name": "Pump-X",
        "expected_items_summary": " | ".join(rows[:5]),
        "max_items": 5,
    }


def seed_synthetic_demo(today: date | None = None) -> None:
    """Create the clearly labelled Aarav Pumps sample once per organization."""
    settings = get_settings()
    org_id = settings.default_org_id
    today = today or date.today()
    now = utc_now()
    with get_session() as session:
        if session.exec(select(Part).where(Part.org_id == org_id)).first():
            return

        specs = [
            ("P-101", "Casing", ["casing", "body"], 520, 7, 100, 2.0),
            ("P-102", "Impeller", ["impeller", "pankha"], 450, 7, 100, 3.0),
            ("P-103", "Shaft", ["shaft", "rod"], 610, 5, 100, 4.0),
            ("P-104", "Gasket 50mm", ["gasket", "chhota gasket"], 380, 4, 100, 1.5),
            ("P-105", "M8 bolt", ["M8 bolt", "bolt"], 1700, 2, 500, 0.5),
            ("P-106", "Bearing 6204", ["bearing"], 1150, 5, 100, 12.0),
            ("P-107", "Mechanical seal", ["seal"], 540, 6, 100, 18.0),
            ("P-108", "Motor 1HP", ["motor"], 520, 10, 100, 2500.0),
            ("P-109", "Packing carton", ["carton", "dabba"], 9000, 3, 500, 25.0),
        ]
        parts: dict[str, Part] = {}
        for sku, name, aliases, on_hand, lead, typical, cost in specs:
            part = Part(
                org_id=org_id,
                sku=sku,
                name=name,
                aliases_json=json.dumps(aliases),
                unit_cost=cost,
                lead_time_days=lead,
                typical_qty=typical,
            )
            session.add(part)
            session.flush()
            parts[sku] = part
            if sku == "P-109":
                session.add(
                    LedgerEvent(
                        org_id=org_id,
                        type="opening_count",
                        part_id=part.id,
                        qty=9700,
                        unit=part.unit,
                        state="confirmed",
                        source="seed",
                        ts=now - timedelta(days=14),
                    )
                )
                for day_offset in range(14):
                    session.add(
                        LedgerEvent(
                            org_id=org_id,
                            type="consumption",
                            part_id=part.id,
                            qty=-50,
                            unit=part.unit,
                            state="confirmed",
                            source="seed",
                            ts=now - timedelta(days=13 - day_offset),
                        )
                    )
            else:
                session.add(
                    LedgerEvent(
                        org_id=org_id,
                        type="opening_count",
                        part_id=part.id,
                        qty=on_hand,
                        unit=part.unit,
                        state="confirmed",
                        source="seed",
                        ts=now - timedelta(days=9 if sku == "P-107" else 1),
                    )
                )

        suppliers = {
            "reliable": Supplier(
                org_id=org_id, name="Shree Components", on_time_count=5,
                total_po_count=5, avg_slip_days=0
            ),
            "late": Supplier(
                org_id=org_id, name="Mahalaxmi Fasteners", on_time_count=2,
                total_po_count=5, avg_slip_days=3
            ),
            "single": Supplier(
                org_id=org_id, name="Precision Seals", on_time_count=0,
                total_po_count=0, avg_slip_days=0
            ),
            "general": Supplier(
                org_id=org_id, name="Aarav Industrial Supply", on_time_count=4,
                total_po_count=5, avg_slip_days=0
            ),
        }
        for supplier in suppliers.values():
            session.add(supplier)
        session.flush()

        supplier_map = {
            "P-101": ["reliable", "general"],
            "P-102": ["reliable", "general"],
            "P-103": ["reliable", "general"],
            "P-104": ["single"],
            "P-105": ["late", "general"],
            "P-106": ["reliable", "general"],
            "P-107": ["single"],
            "P-108": ["reliable", "general"],
            "P-109": ["reliable", "general"],
        }
        for sku, keys in supplier_map.items():
            for key in keys:
                session.add(
                    PartSupplier(
                        org_id=org_id,
                        part_id=parts[sku].id,
                        supplier_id=suppliers[key].id,
                    )
                )

        product = Product(org_id=org_id, code="Pump-X", name="Pump-X")
        session.add(product)
        session.flush()
        bom_quantities = {
            "P-101": 1, "P-102": 1, "P-103": 1, "P-104": 1,
            "P-105": 4, "P-106": 2, "P-107": 1, "P-108": 1,
        }
        for sku, qty_per_unit in bom_quantities.items():
            session.add(
                BOMItem(
                    org_id=org_id,
                    product_id=product.id,
                    part_id=parts[sku].id,
                    qty_per_unit=qty_per_unit,
                )
            )
        session.add(
            WorkOrder(
                id="WO-2041",
                org_id=org_id,
                product_id=product.id,
                qty=500,
                start_date=today + timedelta(days=4),
                due_date=today + timedelta(days=8),
            )
        )
        for order_id, sku, supplier_key, qty in (
            ("PO-IMP-001", "P-102", "reliable", 100),
            ("PO-BOLT-001", "P-105", "late", 500),
        ):
            session.add(
                PurchaseOrder(
                    id=order_id,
                    org_id=org_id,
                    part_id=parts[sku].id,
                    supplier_id=suppliers[supplier_key].id,
                    qty=qty,
                    promised_date=today + timedelta(days=2),
                    eta_date=today + timedelta(days=2),
                )
            )
        session.commit()
