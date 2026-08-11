"""Structured logging configuration."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import MutableMapping
    from typing import Any

import structlog

_REDACTED = "[REDACTED]"
_TELEGRAM_TOKEN_RE = re.compile(r"(?<!\d)\d{8,12}:[A-Za-z0-9_-]{30,}\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(bot[_-]?token|token|password|secret|invite[_-]?(?:code|token)|"
    r"authorization|cookie|session|dsn)\b\s*[:=]\s*[^\s,;]+"
)
_URL_USERINFO_RE = re.compile(r"(?i)\bhttps?://[^/@\s]+@")
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "bot_token",
        "comment",
        "cookie",
        "dsn",
        "evidence",
        "invite_code",
        "invite_token",
        "materials",
        "password",
        "payload",
        "reason",
        "secret",
        "session",
        "token",
    }
)


def configure_logging(log_level: str) -> None:
    """Configure standard-library and structured logging for one process."""
    logging.basicConfig(format="%(message)s", level=log_level, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            scrub_event_processor,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def scrub_value(value: object, *, key: str | None = None) -> object:
    """Recursively remove secrets and free-form private fields."""
    normalized_key = "" if key is None else key.lower()
    if any(marker in normalized_key for marker in _SENSITIVE_KEYS):
        return _REDACTED
    if isinstance(value, dict):
        return {
            str(item_key): scrub_value(item, key=str(item_key)) for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [scrub_value(item) for item in value]
    if isinstance(value, str):
        scrubbed = _TELEGRAM_TOKEN_RE.sub(_REDACTED, value)
        scrubbed = _BEARER_RE.sub(_REDACTED, scrubbed)
        scrubbed = _SECRET_ASSIGNMENT_RE.sub(_REDACTED, scrubbed)
        return _URL_USERINFO_RE.sub(f"https://{_REDACTED}@", scrubbed)
    return value


def scrub_event_processor(
    _logger: object, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Apply the shared scrubber to one structured log event."""
    scrubbed = scrub_value(event_dict)
    return scrubbed if isinstance(scrubbed, dict) else {}
