"""Environment-backed application settings."""

from __future__ import annotations

import datetime
import re
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MIN_SERVICE_TOKEN_LENGTH = 16


class Settings(BaseSettings):
    """Load process settings from environment variables and an optional `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = (
        "postgresql+asyncpg://community_bot:community_bot@localhost:5432/community_bot"
    )
    bot_token: SecretStr | None = None
    telegram_bot_username: str | None = None
    community_telegram_chat_id: int | None = None
    community_telegram_chat_title: str = "Алло, Нейросеточная?"
    community_telegram_join_url: str | None = None
    mini_app_origin: str | None = None
    local_review_telegram_user_id: int | None = None
    local_review_invitation_token: SecretStr | None = None
    invite_token_secret: SecretStr | None = None
    sentry_dsn: SecretStr | None = None
    release: str = "local"
    notification_window_start_local: datetime.time = datetime.time(hour=9)
    notification_window_end_local: datetime.time = datetime.time(hour=21)
    worker_batch_size: int = 25
    worker_poll_interval_seconds: float = 2.0
    worker_lease_seconds: int = 120
    heartbeat_max_age_seconds: int = 180
    community_stats_base_url: str | None = None
    community_stats_token: SecretStr | None = None
    community_stats_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    @field_validator("database_url")
    @classmethod
    def normalize_database_driver(cls, value: str) -> str:
        """Use asyncpg for common PostgreSQL connection strings."""
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("telegram_bot_username")
    @classmethod
    def normalize_bot_username(cls, value: str | None) -> str | None:
        """Store a Telegram bot username without its optional at-sign."""
        if value is None:
            return None
        normalized = value.strip().removeprefix("@").strip()
        if re.fullmatch(r"[A-Za-z0-9_]{5,32}", normalized) is None:
            msg = "TELEGRAM_BOT_USERNAME must be a valid Telegram username"
            raise ValueError(msg)
        return normalized

    @field_validator("community_stats_base_url")
    @classmethod
    def normalize_stats_base_url(cls, value: str | None) -> str | None:
        """Accept only an explicit HTTP origin for the private Stats service."""
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            msg = "COMMUNITY_STATS_BASE_URL must be an HTTP(S) origin without credentials or path"
            raise ValueError(msg)
        return normalized

    @model_validator(mode="after")
    def require_immutable_production_release(self) -> Settings:
        """Reject ambiguous runtime identity in the production configuration."""
        if self.environment == "production" and re.fullmatch(r"[0-9a-f]{40}", self.release) is None:
            msg = "production RELEASE must be a full lowercase Git SHA"
            raise ValueError(msg)
        if self.local_review_telegram_user_id is not None and (
            self.environment != "development"
            or not 1 <= self.local_review_telegram_user_id <= 2**63 - 1
        ):
            msg = "local review identity requires development and a valid Telegram user ID"
            raise ValueError(msg)
        if self.local_review_invitation_token is not None and (
            self.environment != "development" or self.local_review_telegram_user_id is None
        ):
            msg = "local review invitation requires a development review identity"
            raise ValueError(msg)
        if self.community_telegram_join_url is not None and self.community_telegram_chat_id is None:
            msg = "COMMUNITY_TELEGRAM_JOIN_URL requires COMMUNITY_TELEGRAM_CHAT_ID"
            raise ValueError(msg)
        stats_values = (self.community_stats_base_url, self.community_stats_token)
        if any(value is not None for value in stats_values) and not all(
            value is not None for value in stats_values
        ):
            msg = "COMMUNITY_STATS_BASE_URL and COMMUNITY_STATS_TOKEN must be set together"
            raise ValueError(msg)
        if (
            self.community_stats_token is not None
            and len(self.community_stats_token.get_secret_value()) < _MIN_SERVICE_TOKEN_LENGTH
        ):
            msg = "COMMUNITY_STATS_TOKEN must contain at least 16 characters"
            raise ValueError(msg)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings singleton."""
    return Settings()
