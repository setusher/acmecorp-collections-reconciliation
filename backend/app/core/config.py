"""Application settings, read from environment variables (and an optional .env file)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(REPO_ROOT / "backend" / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "acmecorp"

    admin_username: str = "admin"
    admin_password: str = "change-me"
    secret_key: str = "dev-insecure-secret-change-me"
    session_hours: int = 12

    frontend_origin: str = "http://localhost:5173"
    app_as_of_date: str | None = None

    # Email
    org_email_address: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_ssl: bool = True
    imap_folder: str = "INBOX"
    inbox_poll_seconds: int = 60

    # Collections policy
    reminder_interval_days: int = 7
    reminder_schedule_minutes: int = 0

    # LLM
    llm_provider: str = "none"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_fallback_model: str = ""
    llm_base_url: str = ""
    llm_timeout_seconds: float = 30.0

    # Uploads
    max_upload_bytes: int = 2 * 1024 * 1024
    max_statement_rows: int = 5000

    seed_customer_emails: str = ""

    data_dir: Path = Field(default=DATA_DIR)

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.org_email_address)

    @property
    def imap_configured(self) -> bool:
        return bool(self.imap_host and self.imap_username and self.imap_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
