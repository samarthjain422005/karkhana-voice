import hmac
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from apps.api.config import get_settings
from apps.api.guardrails import evaluate_entry, validate_alias

router = APIRouter(prefix="/tools", tags=["tools"])


class ValidateEntryRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    part_alias: str = Field(min_length=1, max_length=100)
    qty: int
    unit: str = "piece"


@router.post("/validate_entry")
def validate_entry(payload: ValidateEntryRequest, request: Request) -> dict[str, Any]:
    settings = get_settings()
    if not settings.tool_token:
        raise HTTPException(
            status_code=503, detail="TOOL_TOKEN must be configured before enabling live tools."
        )
    token = request.headers.get("x-tool-token", "")
    if not hmac.compare_digest(token, settings.tool_token):
        raise HTTPException(status_code=401, detail="Invalid tool token.")
    part = validate_alias(settings.default_org_id, payload.part_alias)
    status, flags, say = evaluate_entry(
        settings.default_org_id, part, payload.qty, payload.unit
    )
    return {
        "status": status,
        "part": part.name if part else None,
        "say": say,
        "flags": flags,
    }
