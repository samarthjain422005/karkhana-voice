from apps.api.store import Part, find_part_by_sku_or_alias, get_on_hand_qty


UNIT_ALIASES = {
    "piece": {"piece", "pieces", "pc", "pcs", "nag"},
    "kg": {"kg", "kilogram", "kilograms"},
    "box": {"box", "boxes", "carton", "cartons"},
}


def evaluate_entry(
    org_id: str, part: Part | None, qty: int, unit: str
) -> tuple[str, list[str], str]:
    if part is None or part.id is None:
        return "reject", ["unknown_part"], "Part nahi mila. Naam ya SKU dobara batayein."
    if qty == 0:
        return "reject", ["zero_quantity"], "Quantity zero lag rahi hai. Number dobara batayein."

    normalized_unit = unit.strip().casefold()
    accepted_units = UNIT_ALIASES.get(part.unit.casefold(), {part.unit.casefold()})
    if normalized_unit not in accepted_units:
        return (
            "reject",
            [f"unit_mismatch:{unit}!={part.unit}"],
            f"{part.name} ka unit {part.unit} hai. Unit dobara batayein.",
        )

    flags: list[str] = []
    current = get_on_hand_qty(org_id, part.id)
    if current + qty < 0:
        flags.append(f"negative_stock:{current}+({qty})")
    if abs(qty) > 10 * max(part.typical_qty, 1):
        flags.append(f"over_10x_typical:{abs(qty)}>{10 * part.typical_qty}")
    if flags:
        return (
            "confirm",
            flags,
            f"{part.name}, {abs(qty)} {part.unit}. Kripya number digit by digit confirm karein.",
        )
    return "ok", [], f"{part.name}, {abs(qty)} {part.unit}. Kya ye sahi hai?"


def validate_alias(org_id: str, alias: str) -> Part | None:
    return find_part_by_sku_or_alias(org_id, alias)
