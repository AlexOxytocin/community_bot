"""Focused domain tests for reputation and profile privacy."""

from __future__ import annotations

import datetime
from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from community_bot.application.reputation import LeaderboardCursor
from community_bot.domain.members import Member, MemberRole, MemberStatus
from community_bot.domain.reputation import (
    ProfileUnavailableError,
    ReliabilityFacts,
    normalize_karma_vote,
    require_profile_visible,
    require_raw_karma_read,
)
from community_bot.infrastructure.db.reputation import _cursor_sort_key


def member(
    *,
    role: MemberRole = MemberRole.MEMBER,
    status: MemberStatus = MemberStatus.ACTIVE,
    permissions: frozenset[str] = frozenset(),
) -> Member:
    """Build one security snapshot."""
    return Member(uuid4(), 1, role, status, permissions)


def test_karma_payload_normalizes_and_validates_private_comment() -> None:
    """Vote values and comments have one deterministic canonical form."""
    assert normalize_karma_vote(1, "  useful   and clear  ") == (1, "useful and clear")
    with pytest.raises(ValueError, match="must be"):
        normalize_karma_vote(2, "useful and clear")
    with pytest.raises(ValueError, match="length"):
        normalize_karma_vote(1, "short")


def test_profile_and_raw_permissions_use_the_exact_status_cross_product() -> None:
    """Safe and raw reads preserve non-active target privacy."""
    active = member()
    paused = member(status=MemberStatus.PAUSED)
    admin_review = member(role=MemberRole.ADMINISTRATOR, permissions=frozenset({"karma_review"}))
    admin_both = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset({"karma_review", "member_read"}),
    )
    moderator = member(
        role=MemberRole.MODERATOR, permissions=frozenset({"karma_review", "member_read"})
    )
    fake_permission = member(
        role=MemberRole.ADMINISTRATOR, permissions=frozenset({"karma_review_fake"})
    )
    assert require_profile_visible(active, active) is active
    with pytest.raises(ProfileUnavailableError):
        require_profile_visible(active, paused)
    require_raw_karma_read(admin_review, active)
    with pytest.raises(ProfileUnavailableError):
        require_raw_karma_read(admin_review, paused)
    require_raw_karma_read(admin_both, paused)
    with pytest.raises(ProfileUnavailableError):
        require_raw_karma_read(moderator, active)
    with pytest.raises(ProfileUnavailableError):
        require_raw_karma_read(fake_permission, active)


def test_reliability_rate_requires_five_assignments_and_supports_half_weight() -> None:
    """Public reliability hides small samples and preserves partial precision."""
    assert ReliabilityFacts(4, Decimal("3.5"), 0).rate is None
    assert ReliabilityFacts(5, Decimal("3.5"), 1).rate == Decimal("0.7")


def test_leaderboard_cursor_encodes_every_total_order_tie_breaker() -> None:
    """Every leaderboard tie-breaker and zero/sentinel boundary is strict."""
    reached = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    base = LeaderboardCursor(
        experience=Decimal(0),
        recipients=0,
        sufficient_sample=False,
        reliability=Decimal(0),
        no_show=1,
        reached_at=reached,
        member_id=UUID(int=2),
    )
    better = (
        replace(base, experience=1),
        replace(base, recipients=1),
        replace(base, sufficient_sample=True),
        replace(base, reliability=Decimal("0.5")),
        replace(base, no_show=0),
        replace(base, reached_at=reached - datetime.timedelta(seconds=1)),
        replace(base, member_id=UUID(int=1)),
    )
    assert all(_cursor_sort_key(item) < _cursor_sort_key(base) for item in better)
    round_trip = LeaderboardCursor(**{field: getattr(base, field) for field in base.__slots__})
    assert round_trip == base
