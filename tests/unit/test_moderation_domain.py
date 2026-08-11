"""Unit tests for deterministic moderation rules."""

from __future__ import annotations

import datetime

import pytest

from community_bot.domain.moderation import (
    ModerationError,
    ResolutionCode,
    RestrictedAction,
    SanctionType,
    resolution_effect,
    risk_signal_key,
    validate_sanction,
)


def test_resolution_matrix_rejects_meaningless_community_outcomes() -> None:
    """Community tasks never invent a creator or post-submission cancellation."""
    assert (
        resolution_effect(ResolutionCode.PARTIAL_PAYMENT, origin="community").payout_fraction
        == "half_ceil"
    )
    with pytest.raises(ModerationError):
        resolution_effect(ResolutionCode.CREATOR_ABUSE, origin="community")
    with pytest.raises(ModerationError):
        resolution_effect(ResolutionCode.CANCEL_WITHOUT_FAULT, origin="community")


def test_sanction_duration_and_action_shape_are_exact() -> None:
    """Temporary status sanctions have an end and bans remain indefinite."""
    now = datetime.datetime.now(datetime.UTC)
    actions = validate_sanction(
        sanction_type=SanctionType.RESTRICTION,
        actions=(RestrictedAction.ACCEPT_TASK,),
        ends_at=now + datetime.timedelta(hours=1),
        now=now,
    )
    assert actions == (RestrictedAction.ACCEPT_TASK,)
    with pytest.raises(ModerationError):
        validate_sanction(
            sanction_type=SanctionType.SUSPENSION,
            actions=(),
            ends_at=None,
            now=now,
        )
    with pytest.raises(ModerationError):
        validate_sanction(
            sanction_type=SanctionType.BAN,
            actions=(),
            ends_at=now + datetime.timedelta(days=1),
            now=now,
        )


def test_risk_signal_identity_is_bucketed_and_order_independent() -> None:
    """Signal replay does not depend on pair input order."""
    moment = datetime.datetime(2026, 8, 11, 23, 59, tzinfo=datetime.UTC)
    first = risk_signal_key(rule="mutual", occurred_at=moment, entity_parts=("b", "a"))
    second = risk_signal_key(rule="mutual", occurred_at=moment, entity_parts=("a", "b"))
    assert first == second
    assert first != risk_signal_key(
        rule="mutual",
        occurred_at=moment + datetime.timedelta(days=1),
        entity_parts=("a", "b"),
    )
