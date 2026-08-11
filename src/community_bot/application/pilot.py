"""Privacy-safe read-only pilot metrics."""

from __future__ import annotations

import datetime
import math
import statistics
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from uuid import UUID

_RATE_QUANTUM = Decimal("0.0001")
_PAID_TYPES = {"task_reward_earned", "partial_task_reward", "community_task_reward"}
_MEMBER_PAID_TYPES = {"task_reward_earned", "partial_task_reward"}


class MetricRatio(BaseModel):
    """One fixed numerator, denominator, and nullable four-place ratio."""

    model_config = ConfigDict(extra="forbid")

    numerator: int
    denominator: int
    rate: str | None


class CommunityTaskMetrics(BaseModel):
    """Aggregate community-task counts and issued rewards."""

    model_config = ConfigDict(extra="forbid")

    published: int
    paid_completed: int
    credits_issued: int


class InteractionAlertMetrics(BaseModel):
    """Fixed aggregate interaction-alert outcomes."""

    model_config = ConfigDict(extra="forbid")

    opened: int
    closed_legitimate: int
    closed_monitor: int
    closed_penalty_recommended: int
    closed_without_outcome: int


class DisputeCancellationMetrics(BaseModel):
    """Aggregate dispute and cancellation counts."""

    model_config = ConfigDict(extra="forbid")

    disputes_opened: int
    tasks_cancelled: int
    assignments_cancelled: int


class DistributionCell(BaseModel):
    """One coarse distribution cell safe for a small cohort."""

    model_config = ConfigDict(extra="forbid")

    label: str
    count: int


class SafeDistribution(BaseModel):
    """Merged coarse cells plus values that cannot be safely labelled."""

    model_config = ConfigDict(extra="forbid")

    cells: tuple[DistributionCell, ...]
    suppressed_count: int


class PilotSuccessMetrics(BaseModel):
    """Exact product thresholds from the MVP requirements."""

    model_config = ConfigDict(extra="forbid")

    task_fill: bool | None
    assignment_completion: bool | None
    repeat_action: bool | None


class PilotMetricsReport(BaseModel):
    """Versioned aggregate report that contains no participant-shaped fields."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "community_bot.pilot_metrics.v1"
    from_at: datetime.datetime
    to_at: datetime.datetime
    generated_at: datetime.datetime
    invite_conversion: MetricRatio
    onboarding_completion: MetricRatio
    current_active_members: int
    tasks_per_active_member: MetricRatio
    task_fill: MetricRatio
    task_fill_48h: MetricRatio
    assignment_completion: MetricRatio
    median_time_to_first_completion_seconds: int | None
    repeat_action: MetricRatio
    unique_paid_pairs: int
    community_tasks: CommunityTaskMetrics
    interaction_alerts: InteractionAlertMetrics
    disputes_and_cancellations: DisputeCancellationMetrics
    weekly_retention: MetricRatio
    top_20_percent_completion_share: MetricRatio
    credit_distribution: SafeDistribution
    experience_distribution: SafeDistribution
    success: PilotSuccessMetrics


@dataclass(frozen=True, slots=True)
class InvitationFact:
    """Invitation capacity and lifecycle timestamps used by aggregate metrics."""

    invitation_id: UUID
    max_uses: int
    created_at: datetime.datetime
    expires_at: datetime.datetime | None
    revoked_at: datetime.datetime | None


@dataclass(frozen=True, slots=True)
class RedemptionFact:
    """Invitation redemption joined to the member approval timestamp."""

    invitation_id: UUID
    member_id: UUID
    redeemed_at: datetime.datetime
    approved_at: datetime.datetime | None


@dataclass(frozen=True, slots=True)
class MemberFact:
    """Current member status without profile or Telegram data."""

    member_id: UUID
    status: str
    approved_at: datetime.datetime | None


@dataclass(frozen=True, slots=True)
class TaskFact:
    """Task lifecycle facts needed for aggregate pilot measures."""

    task_id: UUID
    origin: str
    creator_id: UUID | None
    published_at: datetime.datetime
    deadline_at: datetime.datetime
    cancelled_at: datetime.datetime | None


@dataclass(frozen=True, slots=True)
class AssignmentFact:
    """Assignment lifecycle facts without result payload or private text."""

    assignment_id: UUID
    task_id: UUID
    performer_id: UUID
    accepted_at: datetime.datetime
    submitted_at: datetime.datetime | None
    cancelled_at: datetime.datetime | None


@dataclass(frozen=True, slots=True)
class TransactionFact:
    """Immutable ledger fact used as the economic source of truth."""

    transaction_id: UUID
    member_id: UUID
    transaction_type: str
    credit_delta: int
    experience_delta: int
    task_id: UUID | None
    assignment_id: UUID | None
    reversed_transaction_id: UUID | None
    created_at: datetime.datetime


@dataclass(frozen=True, slots=True)
class AlertFact:
    """Privacy-minimal interaction alert lifecycle."""

    opened_at: datetime.datetime
    closed_at: datetime.datetime | None
    outcome: str | None


@dataclass(frozen=True, slots=True)
class TimedMemberFact:
    """One member-scoped activity timestamp without its payload."""

    member_id: UUID
    occurred_at: datetime.datetime


@dataclass(frozen=True, slots=True)
class PilotMetricFacts:
    """Closed fact bundle loaded by the infrastructure adapter."""

    invitations: tuple[InvitationFact, ...]
    redemptions: tuple[RedemptionFact, ...]
    members: tuple[MemberFact, ...]
    tasks: tuple[TaskFact, ...]
    assignments: tuple[AssignmentFact, ...]
    transactions: tuple[TransactionFact, ...]
    alerts: tuple[AlertFact, ...]
    disputes: tuple[datetime.datetime, ...]
    karma_activities: tuple[TimedMemberFact, ...]


class PilotMetricsPort(Protocol):
    """Load privacy-minimal facts for one report cutoff."""

    async def load_facts(self, *, to_at: datetime.datetime) -> PilotMetricFacts:
        """Load facts with persisted event time strictly before the cutoff."""
        ...


class PilotMetricsService:
    """Build the versioned report through a read-only adapter."""

    def __init__(self, port: PilotMetricsPort) -> None:
        """Store the read-only metrics adapter."""
        self._port = port

    async def report(
        self,
        *,
        from_at: datetime.datetime,
        to_at: datetime.datetime,
        generated_at: datetime.datetime | None = None,
    ) -> PilotMetricsReport:
        """Return one aggregate report for the UTC half-open interval."""
        normalized_from = _utc(from_at)
        normalized_to = _utc(to_at)
        if normalized_from >= normalized_to:
            msg = "Pilot report interval must be non-empty."
            raise ValueError(msg)
        normalized_generated = _utc(generated_at or datetime.datetime.now(datetime.UTC))
        facts = await self._port.load_facts(to_at=normalized_to)
        return calculate_pilot_metrics(
            facts,
            from_at=normalized_from,
            to_at=normalized_to,
            generated_at=normalized_generated,
        )


def calculate_pilot_metrics(
    facts: PilotMetricFacts,
    *,
    from_at: datetime.datetime,
    to_at: datetime.datetime,
    generated_at: datetime.datetime,
) -> PilotMetricsReport:
    """Calculate deterministic aggregates from a closed fact bundle."""
    from_at = _utc(from_at)
    to_at = _utc(to_at)
    generated_at = _utc(generated_at)
    if from_at >= to_at:
        msg = "Pilot report interval must be non-empty."
        raise ValueError(msg)
    window_tasks = tuple(task for task in facts.tasks if _inside(task.published_at, from_at, to_at))
    active_member_ids = {member.member_id for member in facts.members if member.status == "active"}
    assignments_by_task = _assignments_by_task(facts.assignments)
    effective_rewards = _effective_rewards(facts.transactions, to_at=to_at)
    task_by_id = {task.task_id: task for task in facts.tasks}
    assignment_by_id = {assignment.assignment_id: assignment for assignment in facts.assignments}

    invite_conversion = _invite_conversion(facts, from_at=from_at, to_at=to_at)
    onboarding = _onboarding(facts.redemptions, from_at=from_at, to_at=to_at)
    task_fill, task_fill_48h = _task_fill(
        window_tasks,
        assignments_by_task,
        to_at=to_at,
    )
    assignment_completion = _assignment_completion(
        facts.assignments,
        effective_rewards,
        from_at=from_at,
        to_at=to_at,
    )
    repeat_action = _repeat_action(
        facts,
        effective_rewards,
        from_at=from_at,
        to_at=to_at,
    )
    weekly_retention = _weekly_retention(facts, to_at=to_at)
    top_share = _top_completion_share(effective_rewards, from_at=from_at, to_at=to_at)
    credit_totals, experience_totals = _ledger_totals(facts.transactions, to_at=to_at)

    member_rewards = tuple(
        reward
        for reward in effective_rewards
        if reward.transaction_type in _MEMBER_PAID_TYPES
        and _inside(reward.created_at, from_at, to_at)
    )
    paid_pairs = _paid_pairs(member_rewards, task_by_id, assignment_by_id)
    community_rewards = tuple(
        reward
        for reward in effective_rewards
        if reward.transaction_type == "community_task_reward"
        and _inside(reward.created_at, from_at, to_at)
    )
    paid_community_tasks = {reward.task_id for reward in community_rewards if reward.task_id}

    return PilotMetricsReport(
        from_at=from_at,
        to_at=to_at,
        generated_at=generated_at,
        invite_conversion=invite_conversion,
        onboarding_completion=onboarding,
        current_active_members=len(active_member_ids),
        tasks_per_active_member=_ratio(len(window_tasks), len(active_member_ids)),
        task_fill=task_fill,
        task_fill_48h=task_fill_48h,
        assignment_completion=assignment_completion,
        median_time_to_first_completion_seconds=_median_first_completion(
            facts.members,
            effective_rewards,
            from_at=from_at,
            to_at=to_at,
        ),
        repeat_action=repeat_action,
        unique_paid_pairs=len(paid_pairs),
        community_tasks=CommunityTaskMetrics(
            published=sum(task.origin == "community" for task in window_tasks),
            paid_completed=len(paid_community_tasks),
            credits_issued=sum(reward.credit_delta for reward in community_rewards),
        ),
        interaction_alerts=_alert_metrics(facts.alerts, from_at=from_at, to_at=to_at),
        disputes_and_cancellations=_dispute_cancellation_metrics(
            facts,
            from_at=from_at,
            to_at=to_at,
        ),
        weekly_retention=weekly_retention,
        top_20_percent_completion_share=top_share,
        credit_distribution=_safe_distribution(
            [credit_totals.get(member_id, 0) for member_id in active_member_ids],
            boundaries=(
                (0, 0, "0"),
                (1, 4, "1-4"),
                (5, 9, "5-9"),
                (10, 19, "10-19"),
                (20, None, "20+"),
            ),
        ),
        experience_distribution=_safe_distribution(
            [experience_totals.get(member_id, 0) for member_id in active_member_ids],
            boundaries=(
                (0, 0, "0"),
                (1, 9, "1-9"),
                (10, 24, "10-24"),
                (25, 49, "25-49"),
                (50, 99, "50-99"),
                (100, None, "100+"),
            ),
        ),
        success=PilotSuccessMetrics(
            task_fill=_passes(task_fill, Decimal("0.7000")),
            assignment_completion=_passes(assignment_completion, Decimal("0.7500")),
            repeat_action=_passes(repeat_action, Decimal("0.6000")),
        ),
    )


def _invite_conversion(
    facts: PilotMetricFacts,
    *,
    from_at: datetime.datetime,
    to_at: datetime.datetime,
) -> MetricRatio:
    closed = tuple(
        invitation
        for invitation in facts.invitations
        if _inside(invitation.created_at, from_at, to_at)
        and (
            (invitation.expires_at is not None and invitation.expires_at < to_at)
            or (invitation.revoked_at is not None and invitation.revoked_at < to_at)
            or sum(
                redemption.invitation_id == invitation.invitation_id
                and redemption.redeemed_at < to_at
                for redemption in facts.redemptions
            )
            >= invitation.max_uses
        )
    )
    denominator = sum(invitation.max_uses for invitation in closed)
    closed_ids = {invitation.invitation_id for invitation in closed}
    numerator = sum(
        redemption.invitation_id in closed_ids and redemption.redeemed_at < to_at
        for redemption in facts.redemptions
    )
    return _ratio(numerator, denominator)


def _onboarding(
    redemptions: tuple[RedemptionFact, ...],
    *,
    from_at: datetime.datetime,
    to_at: datetime.datetime,
) -> MetricRatio:
    cohort = tuple(item for item in redemptions if _inside(item.redeemed_at, from_at, to_at))
    completed = sum(item.approved_at is not None and item.approved_at < to_at for item in cohort)
    return _ratio(completed, len(cohort))


def _task_fill(
    tasks: tuple[TaskFact, ...],
    assignments_by_task: dict[UUID, tuple[AssignmentFact, ...]],
    *,
    to_at: datetime.datetime,
) -> tuple[MetricRatio, MetricRatio]:
    matured = tuple(
        task
        for task in tasks
        if min(task.published_at + datetime.timedelta(hours=48), task.deadline_at) < to_at
    )
    filled = 0
    filled_48h = 0
    for task in matured:
        accepted = tuple(
            assignment
            for assignment in assignments_by_task.get(task.task_id, ())
            if assignment.accepted_at < to_at
        )
        filled += bool(accepted)
        filled_48h += any(
            assignment.accepted_at < task.published_at + datetime.timedelta(hours=48)
            for assignment in accepted
        )
    return _ratio(filled, len(matured)), _ratio(filled_48h, len(matured))


def _assignment_completion(
    assignments: tuple[AssignmentFact, ...],
    rewards: tuple[TransactionFact, ...],
    *,
    from_at: datetime.datetime,
    to_at: datetime.datetime,
) -> MetricRatio:
    cohort = tuple(item for item in assignments if _inside(item.accepted_at, from_at, to_at))
    rewarded = {item.assignment_id for item in rewards if item.created_at < to_at}
    return _ratio(sum(item.assignment_id in rewarded for item in cohort), len(cohort))


def _median_first_completion(
    members: tuple[MemberFact, ...],
    rewards: tuple[TransactionFact, ...],
    *,
    from_at: datetime.datetime,
    to_at: datetime.datetime,
) -> int | None:
    durations: list[int] = []
    for member in members:
        if member.approved_at is None or not _inside(member.approved_at, from_at, to_at):
            continue
        first = min(
            (reward.created_at for reward in rewards if reward.member_id == member.member_id),
            default=None,
        )
        if first is not None and first < to_at and first >= member.approved_at:
            durations.append(int((first - member.approved_at).total_seconds()))
    return int(statistics.median(durations)) if durations else None


def _repeat_action(
    facts: PilotMetricFacts,
    rewards: tuple[TransactionFact, ...],
    *,
    from_at: datetime.datetime,
    to_at: datetime.datetime,
) -> MetricRatio:
    first_rewards: dict[UUID, datetime.datetime] = {}
    for reward in rewards:
        if _inside(reward.created_at, from_at, to_at):
            current = first_rewards.get(reward.member_id)
            if current is None or reward.created_at < current:
                first_rewards[reward.member_id] = reward.created_at
    repeated = 0
    for member_id, first_at in first_rewards.items():
        published_again = any(
            task.creator_id == member_id and first_at < task.published_at < to_at
            for task in facts.tasks
        )
        accepted_again = any(
            assignment.performer_id == member_id and first_at < assignment.accepted_at < to_at
            for assignment in facts.assignments
        )
        repeated += published_again or accepted_again
    return _ratio(repeated, len(first_rewards))


def _weekly_retention(facts: PilotMetricFacts, *, to_at: datetime.datetime) -> MetricRatio:
    current_from = to_at - datetime.timedelta(days=7)
    previous_from = to_at - datetime.timedelta(days=14)
    activities = _activities(facts)
    previous = {
        item.member_id
        for item in activities
        if _inside(item.occurred_at, previous_from, current_from)
    }
    current = {
        item.member_id for item in activities if _inside(item.occurred_at, current_from, to_at)
    }
    return _ratio(len(previous & current), len(previous))


def _top_completion_share(
    rewards: tuple[TransactionFact, ...],
    *,
    from_at: datetime.datetime,
    to_at: datetime.datetime,
) -> MetricRatio:
    counts = Counter(
        reward.member_id for reward in rewards if _inside(reward.created_at, from_at, to_at)
    )
    if not counts:
        return _ratio(0, 0)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].hex))
    top_size = math.ceil(len(ordered) * 0.2)
    return _ratio(sum(count for _, count in ordered[:top_size]), sum(counts.values()))


def _alert_metrics(
    alerts: tuple[AlertFact, ...],
    *,
    from_at: datetime.datetime,
    to_at: datetime.datetime,
) -> InteractionAlertMetrics:
    closed = tuple(
        alert
        for alert in alerts
        if alert.closed_at is not None and _inside(alert.closed_at, from_at, to_at)
    )
    return InteractionAlertMetrics(
        opened=sum(_inside(alert.opened_at, from_at, to_at) for alert in alerts),
        closed_legitimate=sum(alert.outcome == "legitimate" for alert in closed),
        closed_monitor=sum(alert.outcome == "monitor" for alert in closed),
        closed_penalty_recommended=sum(alert.outcome == "penalty_recommended" for alert in closed),
        closed_without_outcome=sum(alert.outcome is None for alert in closed),
    )


def _dispute_cancellation_metrics(
    facts: PilotMetricFacts,
    *,
    from_at: datetime.datetime,
    to_at: datetime.datetime,
) -> DisputeCancellationMetrics:
    return DisputeCancellationMetrics(
        disputes_opened=sum(_inside(value, from_at, to_at) for value in facts.disputes),
        tasks_cancelled=sum(
            task.cancelled_at is not None and _inside(task.cancelled_at, from_at, to_at)
            for task in facts.tasks
        ),
        assignments_cancelled=sum(
            item.cancelled_at is not None and _inside(item.cancelled_at, from_at, to_at)
            for item in facts.assignments
        ),
    )


def _safe_distribution(
    values: list[int],
    *,
    boundaries: tuple[tuple[int, int | None, str], ...],
) -> SafeDistribution:
    counts = [
        sum(_in_bucket(value, lower, upper) for value in values) for lower, upper, _ in boundaries
    ]
    groups = [[index] for index in range(len(boundaries))]
    index = 0
    while index < len(groups):
        count = sum(counts[item] for item in groups[index])
        if count not in {1, 2}:
            index += 1
            continue
        if len(groups) == 1:
            return SafeDistribution(cells=(), suppressed_count=count)
        target = index + 1 if index + 1 < len(groups) else index - 1
        if target > index:
            groups[target] = groups[index] + groups[target]
            groups.pop(index)
        else:
            groups[target].extend(groups[index])
            groups.pop(index)
            index = max(0, target)
    cells = tuple(
        DistributionCell(
            label=_merged_label(group, boundaries),
            count=sum(counts[item] for item in group),
        )
        for group in groups
        if sum(counts[item] for item in group) > 0
    )
    return SafeDistribution(cells=cells, suppressed_count=0)


def _activities(facts: PilotMetricFacts) -> tuple[TimedMemberFact, ...]:
    task_activities = tuple(
        TimedMemberFact(task.creator_id, task.published_at)
        for task in facts.tasks
        if task.creator_id is not None
    )
    accepted = tuple(
        TimedMemberFact(item.performer_id, item.accepted_at) for item in facts.assignments
    )
    submitted = tuple(
        TimedMemberFact(item.performer_id, item.submitted_at)
        for item in facts.assignments
        if item.submitted_at is not None
    )
    return task_activities + accepted + submitted + facts.karma_activities


def _effective_rewards(
    transactions: tuple[TransactionFact, ...],
    *,
    to_at: datetime.datetime,
) -> tuple[TransactionFact, ...]:
    reversed_ids = {
        item.reversed_transaction_id
        for item in transactions
        if item.reversed_transaction_id is not None and item.created_at < to_at
    }
    return tuple(
        item
        for item in transactions
        if item.transaction_type in _PAID_TYPES
        and item.created_at < to_at
        and item.transaction_id not in reversed_ids
    )


def _ledger_totals(
    transactions: tuple[TransactionFact, ...],
    *,
    to_at: datetime.datetime,
) -> tuple[Counter[UUID], Counter[UUID]]:
    credit_totals: Counter[UUID] = Counter()
    experience: Counter[UUID] = Counter()
    for item in transactions:
        if item.created_at < to_at:
            credit_totals[item.member_id] += item.credit_delta
            experience[item.member_id] += item.experience_delta
    return credit_totals, experience


def _paid_pairs(
    rewards: tuple[TransactionFact, ...],
    tasks: dict[UUID, TaskFact],
    assignments: dict[UUID, AssignmentFact],
) -> set[tuple[UUID, UUID]]:
    pairs: set[tuple[UUID, UUID]] = set()
    for reward in rewards:
        if reward.task_id is None or reward.assignment_id is None:
            continue
        task = tasks.get(reward.task_id)
        assignment = assignments.get(reward.assignment_id)
        if task is not None and task.creator_id is not None and assignment is not None:
            pairs.add(_pair(task.creator_id, assignment.performer_id))
    return pairs


def _assignments_by_task(
    assignments: tuple[AssignmentFact, ...],
) -> dict[UUID, tuple[AssignmentFact, ...]]:
    grouped: dict[UUID, list[AssignmentFact]] = {}
    for assignment in assignments:
        grouped.setdefault(assignment.task_id, []).append(assignment)
    return {key: tuple(value) for key, value in grouped.items()}


def _ratio(numerator: int, denominator: int) -> MetricRatio:
    value = None
    if denominator:
        value = str(
            (Decimal(numerator) / Decimal(denominator)).quantize(
                _RATE_QUANTUM,
                rounding=ROUND_HALF_UP,
            )
        )
    return MetricRatio(numerator=numerator, denominator=denominator, rate=value)


def _passes(metric: MetricRatio, threshold: Decimal) -> bool | None:
    return None if metric.rate is None else Decimal(metric.rate) >= threshold


def _inside(value: datetime.datetime, start: datetime.datetime, end: datetime.datetime) -> bool:
    return start <= value < end


def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "Pilot report timestamps must be timezone-aware."
        raise ValueError(msg)
    return value.astimezone(datetime.UTC)


def _pair(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    return (first, second) if first.int < second.int else (second, first)


def _in_bucket(value: int, lower: int, upper: int | None) -> bool:
    return value >= lower and (upper is None or value <= upper)


def _merged_label(
    group: list[int],
    boundaries: tuple[tuple[int, int | None, str], ...],
) -> str:
    if len(group) == 1:
        return boundaries[group[0]][2]
    lower = boundaries[group[0]][0]
    upper = boundaries[group[-1]][1]
    return f"{lower}+" if upper is None else f"{lower}-{upper}"
