from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from apps.api.store import (
    BOMItem,
    LedgerEvent,
    Incident,
    HandoverItem,
    Part,
    PurchaseOrder,
    Signal,
    Supplier,
    WorkOrder,
    get_on_hand_qty,
    get_watchtower_inputs,
)


def slack_points(slack_days: int | None) -> int:
    if slack_days is None:
        return 0
    if slack_days < 0:
        return 50
    if slack_days <= 1:
        return 35
    if slack_days <= 4:
        return 15
    return 0


def band_for_score(score: int) -> str:
    if score >= 50:
        return "Red"
    if score >= 25:
        return "Amber"
    return "Green"


def compute_watchtower(org_id: str, today: date | None = None) -> dict[str, Any]:
    inputs = get_watchtower_inputs(org_id)
    ref_today = today or date.today()
    parts: list[Part] = inputs["parts"]
    suppliers: list[Supplier] = inputs["suppliers"]
    orders: list[PurchaseOrder] = inputs["orders"]
    bom: list[BOMItem] = inputs["bom"]
    work_orders: list[WorkOrder] = inputs["work_orders"]
    events: list[LedgerEvent] = inputs["events"]
    signals: list[Signal] = inputs["signals"]
    incidents: list[Incident] = inputs["incidents"]
    handovers: list[HandoverItem] = inputs["handovers"]

    supplier_by_id = {supplier.id: supplier for supplier in suppliers}
    suppliers_by_part: dict[int, list[Supplier]] = defaultdict(list)
    for link in inputs["links"]:
        supplier = supplier_by_id.get(link.supplier_id)
        if supplier is not None:
            suppliers_by_part[link.part_id].append(supplier)
    bom_by_part: dict[int, list[BOMItem]] = defaultdict(list)
    for item in bom:
        bom_by_part[item.part_id].append(item)
    orders_by_part: dict[int, list[PurchaseOrder]] = defaultdict(list)
    for order in orders:
        orders_by_part[order.part_id].append(order)
    signals_by_supplier: dict[int, int] = {}
    for signal in signals:
        signals_by_supplier[signal.supplier_id] = max(
            signals_by_supplier.get(signal.supplier_id, 0), signal.delay_days
        )
    events_by_part: dict[int, list[LedgerEvent]] = defaultdict(list)
    for event in events:
        events_by_part[event.part_id].append(event)

    risk_rows: list[dict[str, Any]] = []
    capital_rows: list[dict[str, Any]] = []
    for part in parts:
        if part.id is None:
            continue
        on_hand = get_on_hand_qty(org_id, part.id)
        part_orders = orders_by_part[part.id]
        part_suppliers = suppliers_by_part[part.id]
        part_bom = bom_by_part[part.id]
        open_po_qty = sum(order.qty for order in part_orders)

        part_events = events_by_part[part.id]
        if part_events:
            newest = max(event.ts for event in part_events)
            if newest.tzinfo is None:
                newest = newest.replace(tzinfo=timezone.utc)
            stale_days = (datetime.now(timezone.utc) - newest).days
        else:
            stale_days = 999
        stale = stale_days >= 7

        need_date: date | None = None
        total_demand = 0
        effective_po_dates: dict[str, date] = {}
        for order in part_orders:
            supplier = supplier_by_id.get(order.supplier_id)
            delay = (supplier.avg_slip_days if supplier else 0)
            delay += signals_by_supplier.get(order.supplier_id, 0)
            effective_po_dates[order.id] = order.eta_date + timedelta(days=delay)

        for offset in range(31):
            day = ref_today + timedelta(days=offset)
            demand = 0
            for work_order in work_orders:
                if work_order.start_date > day:
                    continue
                for item in part_bom:
                    if item.product_id == work_order.product_id:
                        demand += work_order.qty * item.qty_per_unit
            total_demand = max(total_demand, demand)
            received = sum(
                order.qty
                for order in part_orders
                if effective_po_dates[order.id] <= day
            )
            if on_hand + received - demand < 0:
                need_date = day
                break

        slack_days: int | None = None
        reason: list[str] = []
        supplier_slip_points = 0
        if need_date is not None:
            if part_orders:
                order = min(part_orders, key=lambda po: effective_po_dates[po.id])
                supplier = supplier_by_id.get(order.supplier_id)
                effective_eta = effective_po_dates[order.id]
                slack_days = (need_date - effective_eta).days
                if supplier and supplier.total_po_count >= 3:
                    on_time_rate = supplier.on_time_count / supplier.total_po_count
                    if on_time_rate < 0.60:
                        supplier_slip_points = 20
                    elif on_time_rate <= 0.80:
                        supplier_slip_points = 10
                    reason.append(f"supplier on-time rate {on_time_rate:.0%}")
                reason.append(
                    f"PO effective ETA day +{(effective_eta - ref_today).days}"
                )
            else:
                primary_supplier = part_suppliers[0] if part_suppliers else None
                delay = primary_supplier.avg_slip_days if primary_supplier else 0
                if primary_supplier:
                    delay += signals_by_supplier.get(primary_supplier.id, 0)
                effective_lead = part.lead_time_days + delay
                slack_days = (need_date - ref_today).days - effective_lead
                reason.append(
                    f"short {max(0, total_demand - on_hand)} {part.unit} by day "
                    f"+{(need_date - ref_today).days}; lead {effective_lead}d"
                )
        elif part_suppliers:
            delayed = max(
                (signals_by_supplier.get(supplier.id, 0) for supplier in part_suppliers),
                default=0,
            )
            if delayed:
                reason.append(f"owner note: supplier delay +{delayed}d")

        single_source_points = 15 if len(part_suppliers) == 1 else 0
        confidence_points = 15 if stale else 0
        slack_score = slack_points(slack_days)
        score = min(
            100,
            slack_score + supplier_slip_points + single_source_points + confidence_points,
        )
        if single_source_points:
            reason.append("single-source exposure")
        if stale:
            reason.append(f"stale count ({stale_days}d)")
        usage_by_day: dict[date, int] = defaultdict(int)
        for event in part_events:
            if event.qty < 0 and event.type in {"consumption", "backflush"}:
                usage_by_day[event.ts.date()] += abs(event.qty)
        avg_daily_use = (
            sum(usage_by_day.values()) / len(usage_by_day) if usage_by_day else 0.0
        )
        effective_lead_days = part.lead_time_days
        if part_suppliers:
            effective_lead_days += min(
                (
                    supplier.avg_slip_days
                    + signals_by_supplier.get(supplier.id, 0)
                    for supplier in part_suppliers
                ),
                default=0,
            )
        wo_shortfall = max(0, total_demand - on_hand - open_po_qty)
        reorder_qty = max(
            0,
            round(avg_daily_use * (effective_lead_days + 2))
            - on_hand
            - open_po_qty,
        ) + wo_shortfall

        risk_rows.append(
            {
                "sku": part.sku,
                "name": part.name,
                "unit": part.unit,
                "on_hand": on_hand,
                "open_po_qty": open_po_qty,
                "planned_demand": total_demand,
                "slack_days": slack_days,
                "score": score,
                "band": band_for_score(score),
                "components": {
                    "slack": slack_score,
                    "supplier_slip": supplier_slip_points,
                    "single_source": single_source_points,
                    "data_confidence": confidence_points,
                },
                "reason": " · ".join(reason) if reason else "Healthy stock cover",
                "avg_daily_use": round(avg_daily_use, 1),
                "effective_lead_days": effective_lead_days,
                "suggested_reorder_qty": reorder_qty,
            }
        )

        days = set(usage_by_day)
        if len(days) >= 14:
            daily_use = avg_daily_use
            days_cover = (on_hand + open_po_qty) / max(daily_use, 1)
            if days_cover > 60:
                capital_rows.append(
                    {
                        "sku": part.sku,
                        "name": part.name,
                        "on_hand": on_hand,
                        "avg_daily_use": round(daily_use, 1),
                        "days_cover": round(days_cover),
                        "flag": "Over",
                        "tied_up_inr": round((on_hand + open_po_qty) * (part.unit_cost or 0), 2),
                        "action": "Defer next PO / free working capital",
                    }
                )

    risk_rows.sort(key=lambda row: (-row["score"], row["sku"]))
    seven_days_ago = ref_today - timedelta(days=7)
    incident_counts: dict[str, int] = defaultdict(int)
    for incident in incidents:
        reported = incident.reported_at
        if reported.tzinfo is None:
            reported = reported.replace(tzinfo=timezone.utc)
        if reported.date() >= seven_days_ago:
            incident_counts[incident.machine] += 1
    operational_signals = [
        {
            "type": "machine_reliability",
            "machine": machine,
            "incident_count_7d": count,
            "message": f"{machine}: {count} breakdown incidents in 7 days",
        }
        for machine, count in sorted(incident_counts.items())
        if count >= 3
    ]
    operational_signals.extend(
        {
            "type": "unacked_handover",
            "handover_id": item.id,
            "severity": item.severity,
            "message": item.text,
        }
        for item in sorted(handovers, key=lambda item: (item.severity != "high", item.ts))[:3]
    )
    summary = {
        "Red": sum(row["band"] == "Red" for row in risk_rows),
        "Amber": sum(row["band"] == "Amber" for row in risk_rows),
        "Green": sum(row["band"] == "Green" for row in risk_rows),
        "Over_stock": len(capital_rows),
    }
    return {
        "org_id": org_id,
        "as_of": ref_today.isoformat(),
        "synthetic_label": "SYNTHETIC DEMO DATASET — AARAV PUMPS (WO-2041: 500 Pump-X due day +4)",
        "summary": summary,
        "risk_lane": risk_rows,
        "capital_lane": capital_rows,
        "operational_signals": operational_signals,
    }
