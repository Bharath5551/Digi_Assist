from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    model: str = "claude-opus-5-5"
    router_model: str = "claude-haiku-5-5"
    effort: str = "medium"

    telegram_bot_token: str = ""
    telegram_owner_id: int = 0

    database_url: str = "sqlite+aiosqlite:///./assistant.db"

    google_client_id: str = ""
    google_client_secret: str = ""
    public_base_url: str = "http://localhost:8000"

    token_encryption_key: str = ""

    timezone: str = "Asia/Kolkata"
    brief_time: str = "05:00"

    max_history_messages: int = 40
    max_tool_iterations: int = 12

    @field_validator("effort")
    @classmethod
    def _effort(cls, v: str) -> str:
        if v not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("EFFORT must be one of low, medium, high, xhigh, max")
        return v

    @property
    def brief_hour_minute(self) -> tuple[int, int]:
        h, m = self.brief_time.split(":")
        return int(h), int(m)


@lru_cache
def get_settings() -> Settings:
    return Settings()
