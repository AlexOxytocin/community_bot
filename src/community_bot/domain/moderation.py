"""Moderation outcomes, sanctions, alerts, and abuse-signal rules."""

# ruff: noqa: FBT003

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


class ResolutionCode(StrEnum):
    """Supported deterministic dispute outcomes."""

    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    FULL_REFUND = "full_refund"
    CANCEL_WITHOUT_FAULT = "cancel_without_fault"
    PERFORMER_NO_SHOW = "performer_no_show"
    CREATOR_ABUSE = "creator_abuse"
    FRAUD = "fraud"


class SanctionType(StrEnum):
    """Human-issued sanction ladder."""

    NOTICE = "notice"
    WARNING = "warning"
    RESTRICTION = "restriction"
    SUSPENSION = "suspension"
    BAN = "ban"


class RestrictedAction(StrEnum):
    """Application actions that a restriction may block."""

    CREATE_TASK = "create_task"
    ACCEPT_TASK = "accept_task"
    KARMA_VOTE = "karma_vote"


class AlertOutcome(StrEnum):
    """Administrator review result for an interaction alert."""

    LEGITIMATE = "legitimate"
    MONITOR = "monitor"
    PENALTY_RECOMMENDED = "penalty_recommended"


@dataclass(frozen=True, slots=True)
class ResolutionEffect:
    """Pure resolution mapping before persistence and economy composition."""

    assignment_status: str
    payout_fraction: str
    reliability_outcome: str
    keeps_slot_occupied: bool
    risk_target: str | None = None


_RESOLUTION_EFFECTS = {
    ResolutionCode.FULL_PAYMENT: ResolutionEffect("approved", "full", "approved", True),
    ResolutionCode.PARTIAL_PAYMENT: ResolutionEffect(
        "partially_approved", "half_ceil", "partially_approved", True
    ),
    ResolutionCode.FULL_REFUND: ResolutionEffect("rejected", "none", "rejected", True),
    ResolutionCode.CANCEL_WITHOUT_FAULT: ResolutionEffect(
        "cancelled", "none", "cancelled_creator", False
    ),
    ResolutionCode.PERFORMER_NO_SHOW: ResolutionEffect("no_show", "none", "no_show", True),
    ResolutionCode.CREATOR_ABUSE: ResolutionEffect("approved", "full", "approved", True, "creator"),
    ResolutionCode.FRAUD: ResolutionEffect("rejected", "none", "rejected", True, "parties"),
}


def resolution_effect(code: ResolutionCode, *, origin: str) -> ResolutionEffect:
    """Return one applicable outcome or reject a meaningless combination."""
    if origin == "community" and code in {
        ResolutionCode.CREATOR_ABUSE,
        ResolutionCode.CANCEL_WITHOUT_FAULT,
    }:
        message = "Resolution code is not applicable to a community task."
        raise ModerationError(message)
    return _RESOLUTION_EFFECTS[code]


def validate_sanction(
    *,
    sanction_type: SanctionType,
    actions: Iterable[RestrictedAction],
    ends_at: datetime.datetime | None,
    now: datetime.datetime,
) -> tuple[RestrictedAction, ...]:
    """Validate duration and action shape independently from authorization."""
    normalized = tuple(sorted(set(actions), key=str))
    if sanction_type in {SanctionType.RESTRICTION, SanctionType.SUSPENSION}:
        if ends_at is None or ends_at <= now:
            message = "Restriction and suspension require a future end time."
            raise ModerationError(message)
    elif sanction_type is SanctionType.BAN and ends_at is not None:
        message = "A ban is indefinite and must not have an end time."
        raise ModerationError(message)
    if sanction_type is SanctionType.RESTRICTION and not normalized:
        message = "A restriction requires at least one blocked action."
        raise ModerationError(message)
    if sanction_type is not SanctionType.RESTRICTION and normalized:
        message = "Only a restriction may contain blocked actions."
        raise ModerationError(message)
    return normalized


def risk_signal_key(
    *, rule: str, occurred_at: datetime.datetime, entity_parts: Iterable[str]
) -> str:
    """Build a privacy-safe idempotency key for one UTC daily bucket."""
    bucket = occurred_at.astimezone(datetime.UTC).date().isoformat()
    projection = json.dumps(
        [rule, bucket, *sorted(entity_parts)], ensure_ascii=True, separators=(",", ":")
    )
    return hashlib.sha256(projection.encode()).hexdigest()


class ModerationError(ValueError):
    """Raised when a moderation command violates a deterministic rule."""
