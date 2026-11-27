from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORE_TIMEZONE = ZoneInfo("America/Campo_Grande")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )

    google_api_key: SecretStr | None = None
    model: str = "gemini-2.5-flash"
    agent_now: datetime | None = None
    data_dir: Path = PROJECT_ROOT / "data"
    support_dir: Path = PROJECT_ROOT / "var"
    session_db_url: str = f"sqlite+aiosqlite:///{PROJECT_ROOT / 'var' / 'sessions.db'}"
    model_armor_template: str | None = None
    max_llm_calls_per_turn: int = 6
    max_message_chars: int = 2000

    @field_validator("agent_now", mode="before")
    @classmethod
    def _empty_agent_now_means_clock(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("agent_now")
    @classmethod
    def _assume_store_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=STORE_TIMEZONE)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def current_time(settings: Settings | None = None) -> datetime:
    """Return the agent's notion of "now" in the store timezone.

    `AGENT_NOW` pins the clock for reproducible tests, evals and examples; without it the
    system clock is used.
    """
    settings = settings or get_settings()
    if settings.agent_now is not None:
        return settings.agent_now.astimezone(STORE_TIMEZONE)
    return datetime.now(STORE_TIMEZONE)
