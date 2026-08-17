from __future__ import annotations

from typing import TYPE_CHECKING

from community_bot.bootstrap.settings import Settings

if TYPE_CHECKING:
    import pytest


def test_settings_have_safe_development_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.bot_token is None
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.notification_window_start_local.hour == 9
    assert settings.notification_window_end_local.hour == 21
    assert settings.worker_batch_size == 25


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"


def test_settings_normalize_render_postgresql_urls() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgres://user:password@private-host/database",
    )

    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_settings_normalize_standard_postgresql_url() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:password@private-host/database",
    )

    assert settings.database_url.startswith("postgresql+asyncpg://")
