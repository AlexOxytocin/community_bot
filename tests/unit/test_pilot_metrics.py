from __future__ import annotations

import datetime
from uuid import UUID

import pytest

from community_bot.application.pilot import (
    AlertFact,
    AssignmentFact,
    InvitationFact,
    MemberFact,
    PilotMetricFacts,
    RedemptionFact,
    TaskFact,
    TimedMemberFact,
    TransactionFact,
    calculate_pilot_metrics,
)

UTC = datetime.UTC
START = datetime.datetime(2026, 8, 1, tzinfo=UTC)
END = datetime.datetime(2026, 8, 8, tzinfo=UTC)


def uid(value: int) -> UUID:
    return UUID(int=value)


def test_empty_report_has_null_rates_and_closed_privacy_schema() -> None:
    report = calculate_pilot_metrics(
        _facts(),
        from_at=START,
        to_at=END,
        generated_at=END,
    )

    assert report.invite_conversion.rate is None
    assert report.task_fill.rate is None
    assert report.assignment_completion.rate is None
    assert report.success.task_fill is None
    assert report.credit_distribution.cells == ()
    payload = report.model_dump_json()
    assert "telegram" not in payload.lower()
    assert "member_id" not in payload
    assert "comment" not in payload


def test_formula_boundaries_rewards_retention_and_small_cells_are_exact() -> None:
    admin, author, performer, second, third = (uid(value) for value in range(1, 6))
    invitation = uid(20)
    first_task, exact_task, excluded_task, repeat_task = (uid(value) for value in range(30, 34))
    first_assignment, exact_assignment = uid(40), uid(41)
    first_reward, partial_reward = uid(50), uid(51)
    published = START
    facts = _facts(
        invitations=(
            InvitationFact(
                invitation_id=invitation,
                max_uses=2,
                created_at=START,
                expires_at=START + datetime.timedelta(days=2),
                revoked_at=None,
            ),
        ),
        redemptions=(
            RedemptionFact(invitation, author, START, START + datetime.timedelta(hours=1)),
            RedemptionFact(invitation, performer, END, None),
        ),
        members=tuple(
            MemberFact(member_id, "active", START - datetime.timedelta(days=20))
            for member_id in (admin, author, performer, second, third)
        ),
        tasks=(
            TaskFact(
                first_task,
                "member",
                author,
                published,
                published + datetime.timedelta(days=3),
                None,
            ),
            TaskFact(
                exact_task,
                "member",
                second,
                START + datetime.timedelta(hours=2),
                START + datetime.timedelta(days=4),
                None,
            ),
            TaskFact(
                excluded_task,
                "member",
                third,
                END,
                END + datetime.timedelta(days=2),
                None,
            ),
            TaskFact(
                repeat_task,
                "member",
                performer,
                START + datetime.timedelta(days=3),
                START + datetime.timedelta(days=5),
                START + datetime.timedelta(days=4),
            ),
        ),
        assignments=(
            AssignmentFact(
                first_assignment,
                first_task,
                performer,
                START + datetime.timedelta(hours=1),
                START + datetime.timedelta(hours=2),
                None,
            ),
            AssignmentFact(
                exact_assignment,
                exact_task,
                third,
                START + datetime.timedelta(hours=50),
                None,
                START + datetime.timedelta(days=3),
            ),
        ),
        transactions=(
            TransactionFact(
                first_reward,
                performer,
                "task_reward_earned",
                2,
                2,
                first_task,
                first_assignment,
                None,
                START + datetime.timedelta(hours=3),
            ),
            TransactionFact(
                partial_reward,
                second,
                "partial_task_reward",
                1,
                1,
                exact_task,
                exact_assignment,
                None,
                END,
            ),
        ),
        alerts=(
            AlertFact(
                opened_at=START,
                closed_at=START + datetime.timedelta(days=1),
                outcome="legitimate",
            ),
        ),
        disputes=(START + datetime.timedelta(days=1),),
        karma_activities=(
            TimedMemberFact(author, END - datetime.timedelta(days=10)),
            TimedMemberFact(author, END - datetime.timedelta(days=2)),
        ),
    )

    report = calculate_pilot_metrics(facts, from_at=START, to_at=END, generated_at=END)

    assert report.invite_conversion.model_dump() == {
        "numerator": 1,
        "denominator": 2,
        "rate": "0.5000",
    }
    assert report.onboarding_completion.model_dump() == {
        "numerator": 1,
        "denominator": 1,
        "rate": "1.0000",
    }
    assert report.tasks_per_active_member.numerator == 3
    assert report.task_fill.model_dump() == {
        "numerator": 2,
        "denominator": 3,
        "rate": "0.6667",
    }
    assert report.task_fill_48h.model_dump() == {
        "numerator": 1,
        "denominator": 3,
        "rate": "0.3333",
    }
    assert report.assignment_completion.model_dump() == {
        "numerator": 1,
        "denominator": 2,
        "rate": "0.5000",
    }
    assert report.repeat_action.rate == "1.0000"
    assert report.unique_paid_pairs == 1
    assert report.weekly_retention.rate == "1.0000"
    assert report.top_20_percent_completion_share.rate == "1.0000"
    assert report.disputes_and_cancellations.disputes_opened == 1
    assert report.disputes_and_cancellations.tasks_cancelled == 1
    assert all(cell.count >= 3 for cell in report.credit_distribution.cells)
    assert all(cell.count >= 3 for cell in report.experience_distribution.cells)
    assert report.success.task_fill is False
    assert report.success.assignment_completion is False
    assert report.success.repeat_action is True


def test_report_rejects_naive_or_empty_intervals() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        calculate_pilot_metrics(
            _facts(),
            from_at=START.replace(tzinfo=None),
            to_at=END,
            generated_at=END,
        )
    with pytest.raises(ValueError, match="non-empty"):
        calculate_pilot_metrics(
            _facts(),
            from_at=END,
            to_at=END,
            generated_at=END,
        )


def _facts(  # noqa: PLR0913 - closed fact builder mirrors the report input DTO.
    *,
    invitations: tuple[InvitationFact, ...] = (),
    redemptions: tuple[RedemptionFact, ...] = (),
    members: tuple[MemberFact, ...] = (),
    tasks: tuple[TaskFact, ...] = (),
    assignments: tuple[AssignmentFact, ...] = (),
    transactions: tuple[TransactionFact, ...] = (),
    alerts: tuple[AlertFact, ...] = (),
    disputes: tuple[datetime.datetime, ...] = (),
    karma_activities: tuple[TimedMemberFact, ...] = (),
) -> PilotMetricFacts:
    return PilotMetricFacts(
        invitations=invitations,
        redemptions=redemptions,
        members=members,
        tasks=tasks,
        assignments=assignments,
        transactions=transactions,
        alerts=alerts,
        disputes=disputes,
        karma_activities=karma_activities,
    )
