"""Optional privacy-safe Sentry initialization."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import sentry_sdk

from community_bot.infrastructure.observability.logging import scrub_value

if TYPE_CHECKING:
    from pydantic import SecretStr
    from sentry_sdk._types import Event


def configure_sentry(
    dsn: SecretStr | None,
    *,
    environment: str,
    release: str,
) -> bool:
    """Initialize Sentry only when configured, with PII disabled."""
    if dsn is None:
        return False
    sentry_sdk.init(
        dsn=dsn.get_secret_value(),
        environment=environment,
        release=release,
        send_default_pii=False,
        traces_sample_rate=0.0,
        before_send=_before_send,
    )
    return True


def _redact_fields(value: object, fields: tuple[str, ...]) -> None:
    """Redact selected fields on a mapping in place."""
    if not isinstance(value, dict):
        return
    for field in fields:
        if field in value:
            value[field] = "[REDACTED]"


def _redact_value_items(container: object, field: str) -> None:
    """Redact one free-form field in a Sentry values list."""
    if not isinstance(container, dict):
        return
    values = container.get("values")
    if not isinstance(values, list):
        return
    for item in values:
        _redact_fields(item, (field,))


def _before_send(event: Event, _hint: dict[str, object]) -> Event:
    """Scrub error events before they leave the process."""
    scrubbed = scrub_value(event)
    if not isinstance(scrubbed, dict):
        return cast("Event", {})

    # Sentry free-form messages can contain user text even when their field names
    # are innocuous. Keep the exception type and stack, but never export message,
    # request, user, breadcrumb text, or exception values from this bot.
    scrubbed.pop("request", None)
    scrubbed.pop("user", None)
    _redact_fields(scrubbed, ("message",))
    _redact_fields(scrubbed.get("logentry"), ("message", "formatted"))
    _redact_value_items(scrubbed.get("exception"), "value")
    _redact_value_items(scrubbed.get("breadcrumbs"), "message")

    return cast("Event", scrubbed)
