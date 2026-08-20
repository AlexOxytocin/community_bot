"""PostgreSQL persistence for karma, profiles, statistics, and leaderboard."""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, or_, select, text

from community_bot.application.reputation import (
    KarmaAggregate,
    KarmaDraft,
    KarmaVoteResult,
    LeaderboardCursor,
    LeaderboardEntry,
    LeaderboardPage,
    LeaderboardPeriod,
    MemberCatalogCursor,
    MemberCatalogPage,
    PersonalStatistics,
    RawKarmaRevision,
    RawKarmaVote,
    ReliabilityView,
    SafeProfile,
)
from community_bot.domain.reputation import KarmaStep, ReliabilityFacts
from community_bot.infrastructure.db import conversations as conversation_store
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AssignmentModel,
    ConversationStateModel,
    KarmaVoteHistoryModel,
    KarmaVoteModel,
    KarmaVoteModerationModel,
    MemberModel,
    MemberSanctionModel,
    ReliabilityEventModel,
    ReliabilityOutcomeCorrectionModel,
    TaskCategoryModel,
    TaskModel,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

_PAIR_GATE_NAMESPACE = "reputation_pair"
_TERMINAL_TYPES = {
    "approved",
    "partially_approved",
    "rejected",
    "no_show",
    "cancelled_performer",
    "cancelled_creator",
}


async def acquire_pair_gate(session: AsyncSession, first_id: UUID, second_id: UUID) -> None:
    """Serialize all karma mutations for one unordered member pair."""
    ordered = sorted((str(first_id), str(second_id)))
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:namespace || ':' || :pair, 0))"),
        {"namespace": _PAIR_GATE_NAMESPACE, "pair": ":".join(ordered)},
    )


async def karma_eligible(session: AsyncSession, first_id: UUID, second_id: UUID) -> bool:
    """Return permanent eligibility derived from an original paid member assignment."""
    count = await session.scalar(
        select(func.count(AccountTransactionModel.id))
        .join(AssignmentModel, AssignmentModel.id == AccountTransactionModel.assignment_id)
        .join(TaskModel, TaskModel.id == AssignmentModel.task_id)
        .where(
            TaskModel.origin == "member",
            AccountTransactionModel.transaction_type.in_(
                ("task_reward_earned", "partial_task_reward")
            ),
            AccountTransactionModel.credit_delta > 0,
            or_(
                and_(TaskModel.creator_id == first_id, AssignmentModel.performer_id == second_id),
                and_(TaskModel.creator_id == second_id, AssignmentModel.performer_id == first_id),
            ),
        )
    )
    return bool(count)


async def get_draft(
    session: AsyncSession, member_id: UUID, *, for_update: bool
) -> KarmaDraft | None:
    """Read a karma state while treating other flows as unavailable."""
    statement = select(ConversationStateModel).where(ConversationStateModel.member_id == member_id)
    if for_update:
        statement = statement.with_for_update()
    state = await session.scalar(statement)
    if state is None or state.flow_type != "karma":
        return None
    payload = dict(state.payload_json)
    return KarmaDraft(
        member_id=member_id,
        target_id=uuid.UUID(str(payload["target_id"])),
        value=None if payload.get("value") is None else int(payload["value"]),
        comment=None if payload.get("comment") is None else str(payload["comment"]),
        step=KarmaStep(state.current_step),
        revision=state.revision,
    )


async def begin_draft(session: AsyncSession, member_id: UUID, target_id: UUID) -> KarmaDraft:
    """Create or select karma as the one current free-text flow."""
    state = await session.scalar(
        select(ConversationStateModel)
        .where(ConversationStateModel.member_id == member_id)
        .with_for_update()
    )
    if state is not None and state.flow_type != "karma":
        message = "Finish or cancel the current conversation first."
        raise ValueError(message)
    if state is None or str(state.payload_json.get("target_id")) != str(target_id):
        await conversation_store.claim_text_flow(
            session,
            member_id=member_id,
            flow_type="karma",
            step=KarmaStep.VALUE.value,
            reference_id=target_id,
            revision=0,
            payload={"target_id": str(target_id), "value": None, "comment": None},
        )
    draft = await get_draft(session, member_id, for_update=False)
    if draft is None:
        message = "Karma conversation could not be created."
        raise RuntimeError(message)
    return draft


async def save_draft(  # noqa: PLR0913 - exact state fields are intentionally explicit.
    session: AsyncSession,
    *,
    member_id: UUID,
    expected_revision: int,
    value: int | None,
    comment: str | None,
    step: KarmaStep,
) -> KarmaDraft:
    """Advance a locked karma state by one exact revision."""
    state = await session.scalar(
        select(ConversationStateModel)
        .where(ConversationStateModel.member_id == member_id)
        .with_for_update()
    )
    if state is None or state.flow_type != "karma" or state.revision != expected_revision:
        message = "Karma conversation revision is stale."
        raise ValueError(message)
    payload = dict(state.payload_json)
    payload["value"] = value
    payload["comment"] = comment
    state.payload_json = payload
    state.current_step = step.value
    state.revision += 1
    await session.flush()
    draft = await get_draft(session, member_id, for_update=False)
    if draft is None:
        message = "Karma conversation disappeared."
        raise RuntimeError(message)
    return draft


async def delete_draft(session: AsyncSession, member_id: UUID, expected_revision: int) -> None:
    """Delete only a locked exact karma state."""
    state = await session.scalar(
        select(ConversationStateModel)
        .where(ConversationStateModel.member_id == member_id)
        .with_for_update()
    )
    if state is None or state.flow_type != "karma" or state.revision != expected_revision:
        message = "Karma conversation revision is stale."
        raise ValueError(message)
    await session.delete(state)
    await session.flush()


async def upsert_vote(  # noqa: PLR0913 - immutable vote payload stays explicit.
    session: AsyncSession,
    *,
    rater_id: UUID,
    target_id: UUID,
    value: int,
    comment: str,
    command_id: UUID,
) -> KarmaVoteResult:
    """Insert or revise one current vote and append immutable history."""
    stored_row = (
        await session.execute(
            select(KarmaVoteHistoryModel, KarmaVoteModel)
            .join(KarmaVoteModel, KarmaVoteModel.id == KarmaVoteHistoryModel.karma_vote_id)
            .where(KarmaVoteHistoryModel.command_id == command_id)
        )
    ).one_or_none()
    if stored_row is not None:
        history, stored_vote = stored_row
        if (
            history.actor_member_id != rater_id
            or stored_vote.target_id != target_id
            or history.new_value != value
            or history.new_comment != comment
        ):
            message = "Karma command payload conflicts with its stored revision."
            raise ValueError(message)
        stored = await vote_by_command(session, command_id)
        if stored is None:
            message = "Stored karma command cannot be reconstructed."
            raise RuntimeError(message)
        return replace(stored, replayed=True)
    vote = await session.scalar(
        select(KarmaVoteModel)
        .where(KarmaVoteModel.rater_id == rater_id, KarmaVoteModel.target_id == target_id)
        .with_for_update()
    )
    if vote is None:
        vote = KarmaVoteModel(
            id=uuid.uuid4(),
            rater_id=rater_id,
            target_id=target_id,
            value=value,
            comment=comment,
            revision=1,
            last_command_id=command_id,
        )
        session.add(vote)
        await session.flush()
        old_value = None
        old_comment = None
    else:
        old_value = vote.value
        old_comment = vote.comment
        vote.value = value
        vote.comment = comment
        vote.revision += 1
        vote.last_command_id = command_id
    session.add(
        KarmaVoteHistoryModel(
            id=uuid.uuid4(),
            karma_vote_id=vote.id,
            revision=vote.revision,
            old_value=old_value,
            new_value=value,
            old_comment=old_comment,
            new_comment=comment,
            command_id=command_id,
            actor_member_id=rater_id,
        )
    )
    await session.flush()
    aggregate = await karma_aggregate(session, target_id)
    return KarmaVoteResult(
        vote_id=vote.id,
        revision=vote.revision,
        aggregate_score=aggregate.score,
        aggregate_count=aggregate.count,
    )


async def vote_by_command(session: AsyncSession, command_id: UUID) -> KarmaVoteResult | None:
    """Return a stored vote revision by immutable command identity."""
    row = (
        await session.execute(
            select(KarmaVoteHistoryModel, KarmaVoteModel.target_id)
            .join(KarmaVoteModel, KarmaVoteModel.id == KarmaVoteHistoryModel.karma_vote_id)
            .where(KarmaVoteHistoryModel.command_id == command_id)
        )
    ).one_or_none()
    if row is None:
        return None
    history, target_id = row
    aggregate = await karma_aggregate(session, target_id)
    return KarmaVoteResult(
        vote_id=history.karma_vote_id,
        revision=history.revision,
        aggregate_score=aggregate.score,
        aggregate_count=aggregate.count,
        replayed=True,
    )


async def karma_aggregate(session: AsyncSession, target_id: UUID) -> KarmaAggregate:
    """Return anonymous aggregate from current vote rows only."""
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(KarmaVoteModel.value), 0), func.count(KarmaVoteModel.id)
            ).where(
                KarmaVoteModel.target_id == target_id,
                func.coalesce(
                    select(KarmaVoteModerationModel.state)
                    .where(
                        KarmaVoteModerationModel.karma_vote_id == KarmaVoteModel.id,
                        KarmaVoteModerationModel.vote_revision == KarmaVoteModel.revision,
                    )
                    .order_by(
                        KarmaVoteModerationModel.created_at.desc(),
                        KarmaVoteModerationModel.id.desc(),
                    )
                    .limit(1)
                    .scalar_subquery(),
                    "included",
                )
                != "excluded",
            )
        )
    ).one()
    return KarmaAggregate(score=int(row[0]), count=int(row[1]))


async def raw_karma(session: AsyncSession, target_id: UUID) -> tuple[RawKarmaVote, ...]:
    """Return private current rows and immutable history after authorization."""
    rows = (
        await session.scalars(
            select(KarmaVoteModel)
            .where(KarmaVoteModel.target_id == target_id)
            .order_by(KarmaVoteModel.rater_id)
        )
    ).all()
    result: list[RawKarmaVote] = []
    for row in rows:
        history_rows = (
            await session.scalars(
                select(KarmaVoteHistoryModel)
                .where(KarmaVoteHistoryModel.karma_vote_id == row.id)
                .order_by(KarmaVoteHistoryModel.revision)
            )
        ).all()
        history = tuple(
            RawKarmaRevision(
                revision=item.revision,
                old_value=item.old_value,
                new_value=item.new_value,
                old_comment=item.old_comment,
                new_comment=item.new_comment,
                actor_member_id=item.actor_member_id,
                created_at=item.created_at,
            )
            for item in history_rows
        )
        result.append(
            RawKarmaVote(
                vote_id=row.id,
                rater_id=row.rater_id,
                value=row.value,
                comment=row.comment,
                revision=row.revision,
                history=history,
            )
        )
    return tuple(result)


async def reliability(  # noqa: C901 - chain folding is kept together as one oracle.
    session: AsyncSession, member_id: UUID
) -> ReliabilityView:
    """Compute effective reliability from acceptance, terminal roots, and corrections."""
    assignment_ids = (
        await session.scalars(
            select(AssignmentModel.id).where(AssignmentModel.performer_id == member_id)
        )
    ).all()
    if not assignment_ids:
        return _reliability_view(ReliabilityFacts(0, Decimal(0), 0))
    events = (
        await session.scalars(
            select(ReliabilityEventModel)
            .where(ReliabilityEventModel.assignment_id.in_(assignment_ids))
            .order_by(ReliabilityEventModel.created_at, ReliabilityEventModel.id)
        )
    ).all()
    by_assignment: dict[UUID, list[ReliabilityEventModel]] = defaultdict(list)
    for event in events:
        by_assignment[event.assignment_id].append(event)
    accepted = 0
    approved_weight = Decimal(0)
    no_show = 0
    for assignment_events in by_assignment.values():
        if not any(item.event_type == "accepted" for item in assignment_events):
            continue
        root = next(
            (
                item
                for item in assignment_events
                if item.supersedes_event_id is None and item.event_type in _TERMINAL_TYPES
            ),
            None,
        )
        if root is None:
            continue
        children = {
            item.supersedes_event_id: item
            for item in assignment_events
            if item.supersedes_event_id is not None
        }
        leaf = root
        while leaf.id in children:
            leaf = children[leaf.id]
        correction = await session.scalar(
            select(ReliabilityOutcomeCorrectionModel)
            .where(ReliabilityOutcomeCorrectionModel.assignment_id == root.assignment_id)
            .order_by(
                ReliabilityOutcomeCorrectionModel.resolution_version.desc(),
                ReliabilityOutcomeCorrectionModel.created_at.desc(),
            )
            .limit(1)
        )
        effective_outcome = root.event_type if correction is None else correction.new_outcome
        if effective_outcome in {"cancelled_creator", "responsibility_excused"} or (
            leaf.event_type == "responsibility_excused"
        ):
            continue
        accepted += 1
        if effective_outcome == "approved":
            approved_weight += Decimal(1)
        elif effective_outcome == "partially_approved":
            approved_weight += Decimal("0.5")
        elif effective_outcome == "no_show":
            no_show += 1
    return _reliability_view(ReliabilityFacts(accepted, approved_weight, no_show))


async def safe_profile(session: AsyncSession, member_id: UUID) -> SafeProfile | None:
    """Build a privacy-safe profile without selecting private karma rows."""
    member = await session.get(MemberModel, member_id)
    if member is None:
        return None
    aggregate = await karma_aggregate(session, member_id)
    reliability_view = await reliability(session, member_id)
    experience = await _experience_total(session, member_id)
    return SafeProfile(
        member_id=member.id,
        telegram_username=member.telegram_username,
        display_name=member.display_name,
        city=member.city,
        short_bio=member.short_bio,
        skill_tags=tuple(member.skill_tags_json),
        experience_total=experience,
        level_number=member.level_number,
        karma=aggregate,
        reliability=reliability_view,
    )


async def member_catalog_cursor(
    session: AsyncSession, member_id: UUID, *, query: str | None
) -> MemberCatalogCursor | None:
    """Resolve an active catalog row into the stable keyset cursor."""
    normalized_name = func.lower(MemberModel.display_name)
    statement = select(normalized_name, MemberModel.id).where(
        MemberModel.id == member_id,
        _effectively_active_clause(),
    )
    if query is not None:
        statement = statement.where(_member_catalog_search_clause(query))
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        return None
    return MemberCatalogCursor(str(row[0]), row[1])


async def safe_profiles(
    session: AsyncSession,
    *,
    limit: int,
    cursor: MemberCatalogCursor | None,
    query: str | None,
) -> MemberCatalogPage:
    """Return an active-profile keyset page in stable name/UUID order."""
    normalized_name = func.lower(MemberModel.display_name)
    statement = select(MemberModel.id).where(_effectively_active_clause())
    if query is not None:
        statement = statement.where(_member_catalog_search_clause(query))
    if cursor is not None:
        statement = statement.where(
            or_(
                normalized_name > cursor.normalized_display_name,
                and_(
                    normalized_name == cursor.normalized_display_name,
                    MemberModel.id > cursor.member_id,
                ),
            )
        )
    member_ids = (
        await session.scalars(statement.order_by(normalized_name, MemberModel.id).limit(limit + 1))
    ).all()
    has_more = len(member_ids) > limit
    member_ids = member_ids[:limit]
    profiles: list[SafeProfile] = []
    for member_id in member_ids:
        profile = await safe_profile(session, member_id)
        if profile is not None:
            profiles.append(profile)
    next_cursor = None
    if has_more and profiles:
        last = profiles[-1]
        next_cursor = MemberCatalogCursor(last.display_name.casefold(), last.member_id)
    return MemberCatalogPage(tuple(profiles), next_cursor)


def _member_catalog_search_clause(query: str) -> ColumnElement[bool]:
    escaped = _escape_like(query)
    pattern = f"%{escaped}%"
    return or_(
        func.lower(MemberModel.display_name).like(pattern, escape="\\"),
        func.lower(func.coalesce(MemberModel.telegram_username, "")).like(pattern, escape="\\"),
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def personal_statistics(session: AsyncSession, member_id: UUID) -> PersonalStatistics:
    """Aggregate one member's contribution statistics."""
    assignments = (
        await session.scalars(
            select(AssignmentModel).where(AssignmentModel.performer_id == member_id)
        )
    ).all()
    assignment_ids = [item.id for item in assignments]
    categories: tuple[str, ...] = ()
    recipients = 0
    if assignment_ids:
        categories = tuple(
            (
                await session.scalars(
                    select(TaskCategoryModel.name)
                    .join(TaskModel, TaskModel.category_id == TaskCategoryModel.id)
                    .join(AssignmentModel, AssignmentModel.task_id == TaskModel.id)
                    .where(
                        AssignmentModel.id.in_(assignment_ids),
                        AssignmentModel.status.in_(("approved", "partially_approved")),
                    )
                    .distinct()
                    .order_by(TaskCategoryModel.name)
                )
            ).all()
        )
        recipients = int(
            await session.scalar(
                select(func.count(func.distinct(TaskModel.creator_id)))
                .join(AssignmentModel, AssignmentModel.task_id == TaskModel.id)
                .where(
                    AssignmentModel.id.in_(assignment_ids),
                    TaskModel.origin == "member",
                    AssignmentModel.status.in_(("approved", "partially_approved")),
                )
            )
            or 0
        )
    reliability_view = await reliability(session, member_id)
    return PersonalStatistics(
        completed=sum(item.status == "approved" for item in assignments),
        partially_completed=sum(item.status == "partially_approved" for item in assignments),
        experience_earned=await _experience_total(session, member_id),
        unique_recipients=recipients,
        categories=categories,
        no_show=reliability_view.no_show,
        reliability=reliability_view,
        created=int(
            await session.scalar(
                select(func.count(TaskModel.id)).where(TaskModel.creator_id == member_id)
            )
            or 0
        ),
    )


async def leaderboard(
    session: AsyncSession,
    *,
    limit: int,
    cursor: LeaderboardCursor | None,
    period: LeaderboardPeriod,
) -> LeaderboardPage:
    """Return a stable ledger-authoritative leaderboard page."""
    members = (
        await session.scalars(
            select(MemberModel).where(_effectively_active_clause()).order_by(MemberModel.id)
        )
    ).all()
    cutoff = {
        "week": dt.datetime.now(dt.UTC) - dt.timedelta(days=7),
        "month": dt.datetime.now(dt.UTC) - dt.timedelta(days=30),
        "all": None,
    }[period]
    ranked: list[tuple[tuple[Any, ...], int, MemberModel, int, ReliabilityView, int, datetime]] = []
    for member in members:
        experience, reached_at = await _experience_and_reached_at(session, member, cutoff=cutoff)
        recipients = await _unique_recipients(session, member.id)
        reliability_view = await reliability(session, member.id)
        rate = reliability_view.rate or Decimal(0)
        key = (
            -experience,
            -recipients,
            -int(reliability_view.rate is not None),
            -rate,
            reliability_view.no_show,
            reached_at,
            str(member.id),
        )
        ranked.append((key, 0, member, recipients, reliability_view, experience, reached_at))
    ranked.sort(key=lambda item: item[0])
    ranked = [
        (key, rank, member, recipients, reliability_view, experience, reached_at)
        for rank, (
            key,
            _,
            member,
            recipients,
            reliability_view,
            experience,
            reached_at,
        ) in enumerate(ranked, start=1)
    ]
    if cursor is not None:
        cursor_key = _cursor_sort_key(cursor)
        ranked = [item for item in ranked if item[0] > cursor_key]
    selected = ranked[:limit]
    entries = tuple(
        LeaderboardEntry(
            rank=rank,
            member_id=member.id,
            display_name=member.display_name,
            experience=experience,
            unique_recipients=recipients,
            reliability=reliability_view.rate,
            no_show=reliability_view.no_show,
            reached_at=reached_at,
        )
        for _, rank, member, recipients, reliability_view, experience, reached_at in selected
    )
    next_cursor = None
    if len(ranked) > limit and selected:
        _, _, member, recipients, reliability_view, experience, reached_at = selected[-1]
        next_cursor = LeaderboardCursor(
            experience=experience,
            recipients=recipients,
            sufficient_sample=reliability_view.rate is not None,
            reliability=reliability_view.rate or Decimal(0),
            no_show=reliability_view.no_show,
            reached_at=reached_at,
            member_id=member.id,
        )
    return LeaderboardPage(entries, next_cursor)


async def _experience_total(session: AsyncSession, member_id: UUID) -> int:
    return int(
        await session.scalar(
            select(func.coalesce(func.sum(AccountTransactionModel.experience_delta), 0)).where(
                AccountTransactionModel.member_id == member_id
            )
        )
        or 0
    )


async def _experience_and_reached_at(
    session: AsyncSession, member: MemberModel, *, cutoff: dt.datetime | None = None
) -> tuple[int, datetime]:
    statement = select(AccountTransactionModel).where(
        AccountTransactionModel.member_id == member.id
    )
    if cutoff is not None:
        statement = statement.where(AccountTransactionModel.created_at >= cutoff)
    transactions = (
        await session.scalars(
            statement.order_by(AccountTransactionModel.created_at, AccountTransactionModel.id)
        )
    ).all()
    total = sum(item.experience_delta for item in transactions)
    if total == 0:
        return 0, member.registered_at
    running = 0
    reached_at = member.registered_at
    for item in transactions:
        running += item.experience_delta
        if running == total:
            reached_at = item.created_at
            break
    return total, reached_at


async def _unique_recipients(session: AsyncSession, member_id: UUID) -> int:
    return int(
        await session.scalar(
            select(func.count(func.distinct(TaskModel.creator_id)))
            .join(AssignmentModel, AssignmentModel.task_id == TaskModel.id)
            .join(
                AccountTransactionModel,
                AccountTransactionModel.assignment_id == AssignmentModel.id,
            )
            .where(
                AssignmentModel.performer_id == member_id,
                TaskModel.origin == "member",
                AccountTransactionModel.transaction_type.in_(
                    ("task_reward_earned", "partial_task_reward")
                ),
                AccountTransactionModel.credit_delta > 0,
            )
        )
        or 0
    )


def _reliability_view(facts: ReliabilityFacts) -> ReliabilityView:
    return ReliabilityView(
        accepted=facts.accepted,
        approved_weight=facts.approved_weight,
        no_show=facts.no_show,
        rate=facts.rate,
    )


def _cursor_sort_key(cursor: LeaderboardCursor) -> tuple[Any, ...]:
    return (
        -cursor.experience,
        -cursor.recipients,
        -int(cursor.sufficient_sample),
        -cursor.reliability,
        cursor.no_show,
        cursor.reached_at,
        str(cursor.member_id),
    )


def _effectively_active_clause():  # noqa: ANN202 - SQLAlchemy boolean expression.
    """Treat an elapsed suspension as active even before the expiry worker runs."""
    now = dt.datetime.now(dt.UTC)
    has_expired = (
        select(MemberSanctionModel.id)
        .where(
            MemberSanctionModel.target_member_id == MemberModel.id,
            MemberSanctionModel.state == "active",
            MemberSanctionModel.applied_status == "suspended",
            MemberSanctionModel.ends_at <= now,
            MemberSanctionModel.previous_status == "active",
        )
        .exists()
    )
    has_live = (
        select(MemberSanctionModel.id)
        .where(
            MemberSanctionModel.target_member_id == MemberModel.id,
            MemberSanctionModel.state == "active",
            MemberSanctionModel.applied_status == "suspended",
            MemberSanctionModel.ends_at > now,
        )
        .exists()
    )
    return or_(
        MemberModel.status == "active",
        and_(MemberModel.status == "suspended", has_expired, ~has_live),
    )
