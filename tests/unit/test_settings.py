from __future__ import annotations

import pytest

from community_bot.bootstrap.settings import Settings


def test_settings_have_safe_development_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.bot_token is None
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.community_entry_topic_id == 21568
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


def test_production_settings_require_full_lowercase_git_sha() -> None:
    with pytest.raises(ValueError, match="full lowercase Git SHA"):
        Settings(_env_file=None, environment="production", release="manual")

    release = "a" * 40
    assert Settings(_env_file=None, environment="production", release=release).release == release


def test_community_chat_id_can_enable_stats_without_a_join_url() -> None:
    settings = Settings(_env_file=None, community_telegram_chat_id=-100_100)
    assert settings.community_telegram_chat_id == -100_100
    assert settings.community_telegram_join_url is None

    with pytest.raises(ValueError, match="requires COMMUNITY_TELEGRAM_CHAT_ID"):
        Settings(_env_file=None, community_telegram_join_url="https://t.me/allo_neural")

    settings = Settings(
        _env_file=None,
        community_telegram_chat_id=-100_100,
        community_telegram_join_url="https://t.me/allo_neural",
    )
    assert settings.community_telegram_chat_title == "Алло, Нейросеточная?"

    settings = Settings(
        _env_file=None,
        community_telegram_chat_id=-100_100,
        community_entry_topic_id=123,
    )
    assert settings.community_entry_topic_id == 123


def test_community_stats_settings_are_paired_and_private_origin_only() -> None:
    with pytest.raises(ValueError, match="must be set together"):
        Settings(_env_file=None, community_stats_base_url="http://stats:8080")
    with pytest.raises(ValueError, match="without credentials or path"):
        Settings(
            _env_file=None,
            community_stats_base_url="http://user:password@stats:8080/private",
            community_stats_token="long-enough-test-token",  # noqa: S106
        )
    with pytest.raises(ValueError, match="at least 16"):
        Settings(
            _env_file=None,
            community_stats_base_url="http://stats:8080",
            community_stats_token="short",  # noqa: S106
        )

    settings = Settings(
        _env_file=None,
        community_stats_base_url="http://stats:8080/",
        community_stats_token="long-enough-test-token",  # noqa: S106
        community_stats_timeout_seconds=1.5,
    )
    assert settings.community_stats_base_url == "http://stats:8080"
    assert settings.community_stats_timeout_seconds == 1.5
