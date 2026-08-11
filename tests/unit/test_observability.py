"""Targeted privacy tests for logs and optional error reporting."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from pydantic import SecretStr

from community_bot.infrastructure.observability.logging import scrub_event_processor, scrub_value
from community_bot.infrastructure.observability.sentry import _before_send, configure_sentry

if TYPE_CHECKING:
    import pytest
    from sentry_sdk._types import Event


def _fake_bot_token() -> str:
    """Build a credential-shaped fixture without storing a token-shaped literal."""
    return f"{10**9}:abcdefghijklmnopqrstuvwxyzABCDEFGH"


def test_recursive_scrubber_removes_private_free_form_values() -> None:
    """Nested secrets and user-provided text never survive the shared processor."""
    event = {
        "event": "worker_failed",
        "release": "sha-1",
        "nested": {
            "bot_token": "secret",
            "comment": "private text",
            "safe_code": "telegram_timeout",
        },
        "payload": {"anything": "private"},
    }

    scrubbed = scrub_event_processor(None, "error", event)

    assert scrubbed["event"] == "worker_failed"
    assert scrubbed["release"] == "sha-1"
    assert scrubbed["nested"] == {
        "bot_token": "[REDACTED]",
        "comment": "[REDACTED]",
        "safe_code": "telegram_timeout",
    }
    assert scrubbed["payload"] == "[REDACTED]"


def test_recursive_scrubber_removes_credentials_embedded_in_plain_text() -> None:
    """Credential-shaped text is removed even under an ordinary field name."""
    fake_bot_token = _fake_bot_token()
    scrubbed = scrub_value(
        {
            "message": f"delivery failed: BOT_TOKEN={fake_bot_token}",
            "detail": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
            "endpoint": "https://private-key@example.invalid/42",
        }
    )

    assert isinstance(scrubbed, dict)
    serialized = repr(scrubbed)
    assert fake_bot_token not in serialized
    assert "abcdefghijklmnopqrstuvwxyz" not in serialized
    assert "private-key" not in serialized
    assert serialized.count("[REDACTED]") >= 3


def test_sentry_drops_free_form_exception_and_request_text() -> None:
    """Sentry retains diagnostic structure but not arbitrary private strings."""
    fake_bot_token = _fake_bot_token()
    event = {
        "message": "private participant comment",
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": f"BOT_TOKEN={fake_bot_token}",
                }
            ]
        },
        "request": {"data": "private form"},
        "user": {"id": "telegram-user"},
        "breadcrumbs": {"values": [{"message": "private navigation"}]},
    }

    scrubbed = cast("dict[str, Any]", _before_send(cast("Event", event), {}))

    assert scrubbed["message"] == "[REDACTED]"
    assert scrubbed["exception"]["values"][0] == {
        "type": "RuntimeError",
        "value": "[REDACTED]",
    }
    assert scrubbed["breadcrumbs"]["values"][0]["message"] == "[REDACTED]"
    assert "request" not in scrubbed
    assert "user" not in scrubbed


def test_sentry_is_optional_and_configured_without_pii(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent DSN is a no-op; configured reporting installs privacy guards."""
    captured: dict[str, object] = {}

    def fake_init(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("sentry_sdk.init", fake_init)

    assert not configure_sentry(None, environment="test", release="sha")
    assert configure_sentry(SecretStr("https://dsn"), environment="test", release="sha")
    assert captured["send_default_pii"] is False
    assert captured["traces_sample_rate"] == 0.0
    assert callable(captured["before_send"])
