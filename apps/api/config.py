from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bolna_api_key: str = ""
    bolna_agent_id_close: str = ""
    bolna_agent_id_open: str = ""
    bolna_agent_id_alert: str = ""
    bolna_base_url: str = "https://api.bolna.ai"
    public_base_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./karkhana.db"
    webhook_secret: str = ""
    tool_token: str = ""
    cron_secret: str = ""
    enforce_bolna_ip_allowlist: bool = False
    demo_daily_cap: int = 20
    demo_per_phone_daily_cap: int = 2
    wallet_floor: float = 1.0
    demo_escalation_seconds: int = 60
    open_brief_time: str = "08:00"
    test_recipient_phone: str = ""
    parser_provider: str = ""
    parser_model: str = ""
    parser_api_key: str = ""
    default_org_id: str = "org_aarav_pumps"
    prompt_version_close: str = "close-v1.0"
    prompt_version_open: str = "open-v1.0"
    prompt_version_alert: str = "alert-v1.0"

    @property
    def bolna_webhook_ips(self) -> set[str]:
        return {"13.203.39.153", "13.126.9.249", "13.202.133.53"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
