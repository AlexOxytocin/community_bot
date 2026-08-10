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


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
