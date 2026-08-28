"""Small batch projections used to enrich Community Stats responses."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from community_bot.application.community_stats import (
    BotLeaderboardItem,
    BotLeaderboardMetric,
    StatsMemberIdentity,
)
from community_bot.domain.members import MemberStatus
from community_bot.infrastructure.db.models import (
    KarmaVoteModel,
    KarmaVoteModerationModel,
    MemberModel,
)

if TYPE_CHECKING:
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
