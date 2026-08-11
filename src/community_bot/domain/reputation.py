"""Karma, profile visibility, reliability, and leaderboard rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from community_bot.domain.members import Member, MemberRole, MemberStatus

if TYPE_CHECKING:
    from uuid import UUID

MIN_KARMA_COMMENT_LENGTH = 10
MAX_KARMA_COMMENT_LENGTH = 300
MIN_RELIABILITY_SAMPLE = 5
KARMA_REVIEW_PERMISSION = "karma_review"
MEMBER_READ_PERMISSION = "member_read"


class ReputationError(ValueError):
    """Base error for deterministic reputation validation."""


class ProfileUnavailableError(PermissionError):
    """Hide absent and unauthorized profile targets behind one error."""


class KarmaStep(StrEnum):
    """Persistent steps of the karma input flow."""

    VALUE = "value"
    COMMENT = "comment"
    PREVIEW = "preview"


@dataclass(frozen=True, slots=True)
class ReliabilityFacts:
    """Aggregated effective reliability facts for one member."""

    accepted: int
    approved_weight: Decimal
    no_show: int

    @property
    def sufficient_sample(self) -> bool:
        """Return whether the public rate has enough observations."""
        return self.accepted >= MIN_RELIABILITY_SAMPLE

    @property
    def rate(self) -> Decimal | None:
        """Return the exact rate or hide it for a small sample."""
        if not self.sufficient_sample:
            return None
        return self.approved_weight / Decimal(self.accepted)


def normalize_karma_vote(value: int, comment: str) -> tuple[int, str]:
    """Validate and normalize one private karma vote payload."""
    if value not in {-1, 0, 1}:
        message = "Karma value must be -1, 0, or 1."
        raise ReputationError(message)
    normalized = " ".join(comment.split())
    if not MIN_KARMA_COMMENT_LENGTH <= len(normalized) <= MAX_KARMA_COMMENT_LENGTH:
        message = "Karma comment length must be between 10 and 300 characters."
        raise ReputationError(message)
    return value, normalized


def require_karma_actor(actor: Member, target: Member, *, eligible: bool) -> None:
    """Authorize a current karma mutation without exposing eligibility details."""
    if (
        actor.status is not MemberStatus.ACTIVE
        or target.status is not MemberStatus.ACTIVE
        or actor.id == target.id
        or not eligible
    ):
        message = "Karma vote is not allowed."
        raise PermissionError(message)


def can_read_safe_profile(actor: Member, target: Member) -> bool:
    """Return whether the actor may receive the target safe projection."""
    if actor.id == target.id:
        return actor.status in {MemberStatus.ACTIVE, MemberStatus.PAUSED}
    if actor.status is not MemberStatus.ACTIVE:
        return False
    if target.status is MemberStatus.ACTIVE:
        return True
    return actor.role is MemberRole.ADMINISTRATOR and MEMBER_READ_PERMISSION in actor.permissions


def require_raw_karma_read(actor: Member, target: Member) -> None:
    """Authorize raw karma while preserving non-active profile privacy."""
    allowed = (
        actor.status is MemberStatus.ACTIVE
        and actor.role is MemberRole.ADMINISTRATOR
        and KARMA_REVIEW_PERMISSION in actor.permissions
        and (target.status is MemberStatus.ACTIVE or MEMBER_READ_PERMISSION in actor.permissions)
    )
    if not allowed:
        message = "Raw karma is unavailable."
        raise ProfileUnavailableError(message)


def require_profile_visible(actor: Member, target: Member | None) -> Member:
    """Return a visible target or raise the shared non-disclosure error."""
    if target is None or not can_read_safe_profile(actor, target):
        message = "Profile unavailable."
        raise ProfileUnavailableError(message)
    return target


def reputation_pair_key(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    """Return a stable unordered member-pair identity."""
    return (first, second) if str(first) <= str(second) else (second, first)
