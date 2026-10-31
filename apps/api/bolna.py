from typing import Any

import httpx

from apps.api.config import get_settings

TERMINAL_STATUSES = {
    "completed",
    "no-answer",
    "busy",
    "failed",
    "canceled",
    "stopped",
    "error",
    "balance-low",
}


class BolnaError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"Bolna HTTP {status_code}: {message}")
        self.status_code = status_code


class BolnaClient:
    def __init__(self):
        settings = get_settings()
        if not settings.bolna_api_key:
            raise ValueError("BOLNA_API_KEY is missing. Set it in .env to enable calls.")
        self.api_key = settings.bolna_api_key
        self.base_url = settings.bolna_base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def _decode(response: httpx.Response, expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        if response.status_code not in expected:
            raise BolnaError(response.status_code, response.text)
        data = response.json()
        if not isinstance(data, dict):
            raise BolnaError(response.status_code, "Expected a JSON object response.")
        return data

    def get_user_me(self) -> dict[str, Any]:
        with httpx.Client(timeout=15) as client:
            response = client.get(f"{self.base_url}/user/me", headers=self._headers())
        return self._decode(response)

    def create_agent_v2(
        self, agent_config: dict[str, Any], system_prompt: str
    ) -> dict[str, Any]:
        body = {
            "agent_config": agent_config,
            "agent_prompts": {"task_1": {"system_prompt": system_prompt}},
        }
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{self.base_url}/v2/agent", headers=self._headers(), json=body
            )
        result = self._decode(response, (200, 201))
        if not result.get("agent_id"):
            raise BolnaError(response.status_code, "Response did not contain agent_id.")
        return result

    def place_call(
        self,
        agent_id: str,
        recipient_phone_number: str,
        user_data: dict[str, Any],
    ) -> dict[str, Any]:
        body = {
            "agent_id": agent_id,
            "recipient_phone_number": recipient_phone_number,
            "user_data": user_data,
        }
        with httpx.Client(timeout=20) as client:
            response = client.post(
                f"{self.base_url}/call", headers=self._headers(), json=body
            )
        result = self._decode(response)
        if not result.get("execution_id"):
            raise BolnaError(response.status_code, "Response did not contain execution_id.")
        return result

    def get_execution(self, execution_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=15) as client:
            response = client.get(
                f"{self.base_url}/executions/{execution_id}",
                headers=self._headers(),
            )
        return self._decode(response)


def extract_execution_fields(payload: dict[str, Any]) -> dict[str, Any]:
    telephony = payload.get("telephony_data")
    user_data = payload.get("user_data")
    cost_breakdown = payload.get("cost_breakdown")
    telephony = {} if telephony is None else telephony
    user_data = {} if user_data is None else user_data
    cost_breakdown = {} if cost_breakdown is None else cost_breakdown
    if not isinstance(telephony, dict):
        raise ValueError("Bolna telephony_data must be a JSON object.")
    if not isinstance(user_data, dict):
        raise ValueError("Bolna user_data must be a JSON object.")
    if not isinstance(cost_breakdown, dict):
        raise ValueError("Bolna cost_breakdown must be a JSON object.")
    try:
        duration = float(payload.get("conversation_duration") or 0)
        total_cost = float(payload.get("total_cost") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Bolna duration and total_cost must be numeric.") from exc
    return {
        "execution_id": str(payload.get("id") or payload.get("execution_id") or ""),
        "agent_id": str(payload.get("agent_id") or ""),
        "status": str(payload.get("status") or ""),
        "is_terminal": str(payload.get("status") or "") in TERMINAL_STATUSES,
        "conversation_duration": duration,
        "total_cost": total_cost,
        "transcript": str(payload.get("transcript") or ""),
        "extracted_data": payload.get("extracted_data"),
        "recording_url": telephony.get("recording_url"),
        "cost_breakdown": cost_breakdown,
        "session_id": str(user_data.get("session_id") or ""),
    }
