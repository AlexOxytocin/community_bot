from __future__ import annotations

import datetime
import json
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

    assert report.invite_conversion_rate.rate is None
    assert report.task_fill_rate.rate is None
    assert report.assignment_completion_rate.rate is None
    assert report.success.task_fill_rate is None
    assert report.credit_distribution.cells == ()
    public_payload = json.loads(report.model_dump_json())
    assert set(public_payload) == {
        "schema_version",
        "from_at",
        "to_at",
        "generated_at",
        "invite_conversion_rate",
        "onboarding_completion_rate",
        "current_active_members",
        "tasks_per_active_member",
        "task_fill_rate",
        "task_fill_rate_48h",
        "assignment_completion_rate",
        "median_time_to_first_completion_seconds",
        "repeat_action_rate",
        "unique_paid_pairs",
        "community_tasks",
        "interaction_alerts",
        "disputes_and_cancellations",
        "weekly_retention_rate",
        "top_20_percent_completion_share",
        "credit_distribution",
        "experience_distribution",
        "success",
    }
    assert set(public_payload["success"]) == {
        "task_fill_rate",
        "assignment_completion_rate",
        "repeat_action_rate",
    }
    payload = report.model_dump_json()
    assert "telegram" not in payload.lower()
    assert "member_id" not in payload
    assert "comment" not in payload


def test_partial_reward_reversal_and_community_aggregate_are_ledger_authoritative() -> None:
    author, partial_performer, reversed_performer, community_performer = (
        uid(value) for value in range(101, 105)
    )
    member_task, reversed_task, community_task = (uid(value) for value in range(110, 113))
    partial_assignment, reversed_assignment, community_assignment = (
        uid(value) for value in range(120, 123)
    )
    partial_reward, full_reward, reversal, community_reward = (
        uid(value) for value in range(130, 134)
    )
    accepted_at = START + datetime.timedelta(hours=1)
    facts = _facts(
        members=tuple(
            MemberFact(member_id, "active", START - datetime.timedelta(days=1))
            for member_id in (author, partial_performer, reversed_performer, community_performer)
        ),
        tasks=(
            TaskFact(member_task, "member", author, START, END, None),
            TaskFact(reversed_task, "member", author, START, END, None),
            TaskFact(community_task, "community", None, START, END, None),
        ),
        assignments=(
            AssignmentFact(
                partial_assignment,
                member_task,
                partial_performer,
                accepted_at,
                accepted_at,
                None,
            ),
            AssignmentFact(
                reversed_assignment,
                reversed_task,
                reversed_performer,
                accepted_at,
                accepted_at,
                None,
            ),
            AssignmentFact(
                community_assignment,
                community_task,
                community_performer,
                accepted_at,
                accepted_at,
                None,
            ),
        ),
        transactions=(
            TransactionFact(
                partial_reward,
                partial_performer,
                "partial_task_reward",
                2,
                2,
                member_task,
                partial_assignment,
                None,
                accepted_at + datetime.timedelta(hours=1),
            ),
            TransactionFact(
                full_reward,
                reversed_performer,
                "task_reward_earned",
                3,
                3,
                reversed_task,
                reversed_assignment,
                None,
                accepted_at + datetime.timedelta(hours=1),
            ),
            TransactionFact(
                reversal,
                reversed_performer,
                "task_reward_reversal",
                -3,
                0,
                reversed_task,
                reversed_assignment,
                full_reward,
                accepted_at + datetime.timedelta(hours=2),
            ),
            TransactionFact(
                community_reward,
                community_performer,
                "community_task_reward",
                5,
                5,
                community_task,
                community_assignment,
                None,
                accepted_at + datetime.timedelta(hours=1),
            ),
        ),
    )

    report = calculate_pilot_metrics(facts, from_at=START, to_at=END, generated_at=END)

    assert report.assignment_completion_rate.model_dump() == {
        "numerator": 2,
        "denominator": 3,
        "rate": "0.6667",
    }
    assert report.unique_paid_pairs == 1
    assert report.community_tasks.model_dump() == {
        "published": 1,
        "paid_completed": 1,
        "credits_issued": 5,
    }


def test_top_share_tie_is_independent_of_input_order() -> None:
    performers = tuple(uid(value) for value in range(201, 206))
    rewards = tuple(
        TransactionFact(
            uid(220 + index),
            performer,
            "task_reward_earned",
            1,
            1,
            None,
            None,
            None,
            START + datetime.timedelta(hours=1),
        )
        for index, performer in enumerate(performers)
    )

    forward = calculate_pilot_metrics(
        _facts(transactions=rewards),
        from_at=START,
        to_at=END,
        generated_at=END,
    )
    reverse = calculate_pilot_metrics(
        _facts(transactions=tuple(reversed(rewards))),
        from_at=START,
        to_at=END,
        generated_at=END,
    )

    assert forward.top_20_percent_completion_share.model_dump() == {
        "numerator": 1,
        "denominator": 5,
        "rate": "0.2000",
    }
    assert reverse.top_20_percent_completion_share == forward.top_20_percent_completion_share


def test_small_cohort_is_suppressed_when_no_safe_cell_can_be_formed() -> None:
    members = (uid(301), uid(302))
    report = calculate_pilot_metrics(
        _facts(
            members=tuple(MemberFact(member_id, "active", START) for member_id in members),
        ),
        from_at=START,
        to_at=END,
        generated_at=END,
    )

    assert report.credit_distribution.model_dump() == {"cells": (), "suppressed_count": 2}
    assert report.experience_distribution.model_dump() == {"cells": (), "suppressed_count": 2}


def test_representative_a_to_d_dataset_has_expected_report() -> None:
    member_a, member_b, member_c, member_d = (uid(value) for value in range(401, 405))
    invitation = uid(410)
    member_task, community_task = uid(420), uid(421)
    member_assignment, community_assignment = uid(430), uid(431)
    member_reward, community_reward = uid(440), uid(441)
    facts = _facts(
        invitations=(
            InvitationFact(
                invitation,
                2,
                START,
                START + datetime.timedelta(days=1),
                None,
            ),
        ),
        redemptions=(
            RedemptionFact(invitation, member_a, START, START + datetime.timedelta(hours=1)),
            RedemptionFact(invitation, member_b, START, None),
        ),
        members=tuple(
            MemberFact(member_id, "active", START - datetime.timedelta(days=1))
            for member_id in (member_a, member_b, member_c, member_d)
        ),
        tasks=(
            TaskFact(
                member_task,
                "member",
                member_a,
                START,
                START + datetime.timedelta(days=2),
                None,
            ),
            TaskFact(
                community_task,
                "community",
                None,
                START,
                START + datetime.timedelta(days=2),
                None,
            ),
        ),
        assignments=(
            AssignmentFact(
                member_assignment,
                member_task,
                member_b,
                START + datetime.timedelta(hours=1),
                START + datetime.timedelta(hours=2),
                None,
            ),
            AssignmentFact(
                community_assignment,
                community_task,
                member_c,
                START + datetime.timedelta(hours=1),
                START + datetime.timedelta(hours=2),
                None,
            ),
        ),
        transactions=(
            TransactionFact(
                member_reward,
                member_b,
                "task_reward_earned",
                3,
                3,
                member_task,
                member_assignment,
                None,
                START + datetime.timedelta(hours=3),
            ),
            TransactionFact(
                community_reward,
                member_c,
                "community_task_reward",
                4,
                4,
                community_task,
                community_assignment,
                None,
                START + datetime.timedelta(hours=3),
            ),
        ),
        alerts=(AlertFact(START, START + datetime.timedelta(hours=4), "monitor"),),
        disputes=(START + datetime.timedelta(hours=5),),
        karma_activities=(
            TimedMemberFact(member_a, END - datetime.timedelta(days=10)),
            TimedMemberFact(member_a, END - datetime.timedelta(days=2)),
        ),
    )

    report = calculate_pilot_metrics(facts, from_at=START, to_at=END, generated_at=END)

    assert report.invite_conversion_rate.model_dump() == {
        "numerator": 2,
        "denominator": 2,
        "rate": "1.0000",
    }
    assert report.onboarding_completion_rate.model_dump() == {
        "numerator": 1,
        "denominator": 2,
        "rate": "0.5000",
    }
    assert report.task_fill_rate.rate == "1.0000"
    assert report.assignment_completion_rate.rate == "1.0000"
    assert report.weekly_retention_rate.model_dump() == {
        "numerator": 1,
        "denominator": 1,
        "rate": "1.0000",
    }
    assert report.community_tasks.credits_issued == 4
    assert report.interaction_alerts.closed_monitor == 1
    assert report.disputes_and_cancellations.disputes_opened == 1
    assert report.schema_version == "community_bot.pilot_metrics.v1"


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

    assert report.invite_conversion_rate.model_dump() == {
        "numerator": 1,
        "denominator": 2,
        "rate": "0.5000",
    }
    assert report.onboarding_completion_rate.model_dump() == {
        "numerator": 1,
        "denominator": 1,
        "rate": "1.0000",
    }
    assert report.tasks_per_active_member.numerator == 3
    assert report.task_fill_rate.model_dump() == {
        "numerator": 2,
        "denominator": 3,
        "rate": "0.6667",
    }
    assert report.task_fill_rate_48h.model_dump() == {
        "numerator": 1,
        "denominator": 3,
        "rate": "0.3333",
    }
    assert report.assignment_completion_rate.model_dump() == {
        "numerator": 1,
        "denominator": 2,
        "rate": "0.5000",
    }
    assert report.repeat_action_rate.rate == "1.0000"
    assert report.unique_paid_pairs == 1
    assert report.weekly_retention_rate.rate == "1.0000"
    assert report.top_20_percent_completion_share.rate == "1.0000"
    assert report.disputes_and_cancellations.disputes_opened == 1
    assert report.disputes_and_cancellations.tasks_cancelled == 1
    assert all(cell.count >= 3 for cell in report.credit_distribution.cells)
    assert all(cell.count >= 3 for cell in report.experience_distribution.cells)
    assert report.success.task_fill_rate is False
    assert report.success.assignment_completion_rate is False
    assert report.success.repeat_action_rate is True


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
