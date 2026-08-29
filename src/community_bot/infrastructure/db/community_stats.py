"""Small batch projections used to enrich Community Stats responses."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from community_bot.application.community_stats import (
    BOT_ACHIEVEMENT_THRESHOLDS,
    BotAchievementCode,
    BotAchievementValues,
    BotLeaderboardItem,
    BotLeaderboardMetric,
    StatsMemberIdentity,
    achievement_level,
)
from community_bot.domain.members import MemberStatus
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    KarmaVoteModel,
    KarmaVoteModerationModel,
    MemberModel,
    TaskModel,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def member_identities(
    session: AsyncSession, telegram_user_ids: tuple[int, ...]
) -> tuple[StatsMemberIdentity, ...]:
    """Resolve Stats Telegram IDs to active public profiles in one query."""
    if not telegram_user_ids:
        return ()
    rows = (
        await session.execute(
            select(MemberModel.id, MemberModel.telegram_user_id, MemberModel.display_name).where(
                MemberModel.telegram_user_id.in_(telegram_user_ids),
                MemberModel.status == MemberStatus.ACTIVE.value,
            )
        )
    ).all()
    return tuple(
        StatsMemberIdentity(row.id, row.telegram_user_id, row.display_name) for row in rows
    )


async def bot_leaderboard(
    session: AsyncSession, *, metric: BotLeaderboardMetric, limit: int
) -> tuple[BotLeaderboardItem, ...]:
    """Rank Bot-owned experience or anonymous karma without per-member queries."""
    latest_moderation_state = (
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
        .correlate(KarmaVoteModel)
        .scalar_subquery()
    )
    karma_scores = (
        select(
            KarmaVoteModel.target_id.label("member_id"),
            func.coalesce(
                func.sum(KarmaVoteModel.value).filter(
                    func.coalesce(latest_moderation_state, "included") != "excluded"
                ),
                0,
            ).label("karma"),
        )
        .group_by(KarmaVoteModel.target_id)
        .subquery()
    )
    value = (
        MemberModel.experience_total_cached
        if metric == "experience"
        else func.coalesce(karma_scores.c.karma, 0)
    )
    statement = (
        select(MemberModel.id, MemberModel.display_name, value.label("value"))
        .outerjoin(karma_scores, karma_scores.c.member_id == MemberModel.id)
        .where(MemberModel.status == MemberStatus.ACTIVE.value)
        .order_by(value.desc(), func.lower(MemberModel.display_name), MemberModel.id)
        .limit(limit)
    )
    rows = (await session.execute(statement)).all()
    return tuple(
        BotLeaderboardItem(row.id, row.display_name, int(row.value), rank)
        for rank, row in enumerate(rows, start=1)
    )


def _bot_achievement_metrics(  # noqa: ANN202 - private SQL projection tuple.
    member_id: UUID | None = None,
):
    running_balance_query = select(
        AccountTransactionModel.member_id.label("member_id"),
        func.sum(AccountTransactionModel.credit_delta)
        .over(
            partition_by=AccountTransactionModel.member_id,
            order_by=(
                AccountTransactionModel.created_at,
                AccountTransactionModel.id,
            ),
            rows=(None, 0),
        )
        .label("running_balance"),
    )
    if member_id is not None:
        running_balance_query = running_balance_query.where(
            AccountTransactionModel.member_id == member_id
        )
    running_balances = running_balance_query.subquery()
    maximum_balances = (
        select(
            running_balances.c.member_id,
            func.max(running_balances.c.running_balance).label("maximum_credit_balance"),
        )
        .group_by(running_balances.c.member_id)
        .subquery()
    )
    created_task_query = select(
        TaskModel.creator_id.label("member_id"),
        func.count(TaskModel.id).label("created_tasks"),
    ).where(TaskModel.creator_id.is_not(None), TaskModel.test_run_id.is_(None))
    if member_id is not None:
        created_task_query = created_task_query.where(TaskModel.creator_id == member_id)
    created_tasks = created_task_query.group_by(TaskModel.creator_id).subquery()
    return maximum_balances, created_tasks


async def bot_achievement_values(
    session: AsyncSession,
    member_id: UUID,
) -> BotAchievementValues:
    """Read maximum historical balance and published member-task count in one query."""
    maximum_balances, created_tasks = _bot_achievement_metrics(member_id)
    row = (
        await session.execute(
            select(
                func.coalesce(maximum_balances.c.maximum_credit_balance, 0),
                func.coalesce(created_tasks.c.created_tasks, 0),
            )
            .select_from(MemberModel)
            .outerjoin(maximum_balances, maximum_balances.c.member_id == MemberModel.id)
            .outerjoin(created_tasks, created_tasks.c.member_id == MemberModel.id)
            .where(MemberModel.id == member_id)
        )
    ).one()
    return BotAchievementValues(
        maximum_credit_balance=max(0, int(row[0])),
        created_tasks=int(row[1]),
    )


async def bot_achievement_leaderboard(
    session: AsyncSession,
    *,
    code: BotAchievementCode,
    limit: int,
) -> tuple[BotLeaderboardItem, ...]:
    """Rank only unlocked Bot-owned achievement levels without exposing raw balances."""
    maximum_balances, created_tasks = _bot_achievement_metrics()
    rows = (
        await session.execute(
            select(
                MemberModel.id,
                MemberModel.display_name,
                func.coalesce(maximum_balances.c.maximum_credit_balance, 0).label(
                    "maximum_credit_balance"
                ),
                func.coalesce(created_tasks.c.created_tasks, 0).label("created_tasks"),
            )
            .outerjoin(maximum_balances, maximum_balances.c.member_id == MemberModel.id)
            .outerjoin(created_tasks, created_tasks.c.member_id == MemberModel.id)
            .where(MemberModel.status == MemberStatus.ACTIVE.value)
        )
    ).all()
    value_name = "maximum_credit_balance" if code == "wealth" else "created_tasks"
    ranked = sorted(
        (
            (
                achievement_level(
                    max(0, int(getattr(row, value_name))),
                    BOT_ACHIEVEMENT_THRESHOLDS[code],
                ),
                max(0, int(getattr(row, value_name))),
                row,
            )
            for row in rows
        ),
        key=lambda item: (-item[0], -item[1], item[2].display_name.casefold(), str(item[2].id)),
    )
    unlocked = [item for item in ranked if item[0] > 0][:limit]
    return tuple(
        BotLeaderboardItem(row.id, row.display_name, level, rank)
        for rank, (level, _current, row) in enumerate(unlocked, start=1)
    )
