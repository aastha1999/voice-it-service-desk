import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = "servicedesk.db"
    tool_secret: str = "dev-tool-secret"
    admin_key: str = "dev-admin-key"
    confirmation_ttl_seconds: int = 120
    max_confirmation_attempts: int = 3
    mdm_retries: int = 3
    mdm_backoff_seconds: float = 0.25
    mdm_fault: str | None = None  # "outage" | "flaky" — for demos of error handling


def load_settings() -> Settings:
    return Settings(
        db_path=os.getenv("SERVICEDESK_DB", "servicedesk.db"),
        tool_secret=os.getenv("TOOL_SECRET", "dev-tool-secret"),
        admin_key=os.getenv("ADMIN_KEY", "dev-admin-key"),
        confirmation_ttl_seconds=int(os.getenv("CONFIRMATION_TTL_SECONDS", "120")),
        max_confirmation_attempts=int(os.getenv("MAX_CONFIRMATION_ATTEMPTS", "3")),
        mdm_fault=os.getenv("MDM_FAULT") or None,
    )
