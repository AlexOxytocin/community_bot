"""Deterministic notification scheduling and retry policies."""

from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class QueueStatus(StrEnum):
    """Persisted lifecycle shared by outbox and notifications."""

    PENDING = "pending"
    PROCESSING = "processing"
    MATERIALIZED = "materialized"
    SENT = "sent"
    FAILED = "failed"


class NotificationError(ValueError):
    """Reject invalid notification policy input."""


_POSITIVE_ATTEMPT_REQUIRED = "Attempt count must be positive."
_NAIVE_WINDOW_REQUIRED = "Delivery window times must be timezone-naive."
_ORDERED_WINDOW_REQUIRED = "Delivery window start must be before end."
_INVALID_TIMEZONE = "Member timezone is invalid."
_AWARE_DATETIME_REQUIRED = "Datetime values must be timezone-aware."


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential retry policy with deterministic jitter."""

    maximum_attempts: int = 5
    base_delay_seconds: int = 30
    maximum_delay_seconds: int = 900

    def next_attempt_at(
        self,
        *,
        now: datetime.datetime,
        attempt_count: int,
        identity: str,
    ) -> datetime.datetime:
        """Return the next UTC attempt for an already failed attempt."""
        if attempt_count < 1:
            raise NotificationError(_POSITIVE_ATTEMPT_REQUIRED)
        aware_now = _aware_utc(now)
        exponential = min(
            self.maximum_delay_seconds,
            self.base_delay_seconds * (2 ** (attempt_count - 1)),
        )
        digest = hashlib.sha256(f"{identity}:{attempt_count}".encode()).digest()
        jitter = int.from_bytes(digest[:2], byteorder="big") % max(1, self.base_delay_seconds)
        return aware_now + datetime.timedelta(seconds=exponential + jitter)


@dataclass(frozen=True, slots=True)
class DeliveryWindow:
    """A half-open participant-local notification window."""

    start: datetime.time = datetime.time(hour=9)
    end: datetime.time = datetime.time(hour=21)

    def __post_init__(self) -> None:
        """Require a simple same-day half-open window."""
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise NotificationError(_NAIVE_WINDOW_REQUIRED)
        if self.start >= self.end:
            raise NotificationError(_ORDERED_WINDOW_REQUIRED)

    def schedule(
        self,
        *,
        candidate: datetime.datetime,
        timezone_name: str,
        deadline: datetime.datetime | None = None,
    ) -> datetime.datetime:
        """Move a candidate into the configured local window without passing a deadline."""
        candidate_utc = _aware_utc(candidate)
        deadline_utc = None if deadline is None else _aware_utc(deadline)
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise NotificationError(_INVALID_TIMEZONE) from error

        local = candidate_utc.astimezone(zone)
        local_time = local.timetz().replace(tzinfo=None)
        if local_time < self.start:
            adjusted_local = datetime.datetime.combine(local.date(), self.start, zone)
        elif local_time >= self.end:
            adjusted_local = datetime.datetime.combine(
                local.date() + datetime.timedelta(days=1), self.start, zone
            )
        else:
            adjusted_local = local
        adjusted = adjusted_local.astimezone(datetime.UTC)

        if deadline_utc is None or adjusted <= deadline_utc:
            return adjusted

        deadline_local = deadline_utc.astimezone(zone)
        last_start = datetime.datetime.combine(deadline_local.date(), self.start, zone)
        if last_start > deadline_local:
            last_start -= datetime.timedelta(days=1)
        return min(deadline_utc, last_start.astimezone(datetime.UTC))


def _aware_utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise NotificationError(_AWARE_DATETIME_REQUIRED)
    return value.astimezone(datetime.UTC)
