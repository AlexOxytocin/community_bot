"""PostgreSQL adapter for privacy-safe pilot metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

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
)
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AssignmentDisputeModel,
    AssignmentModel,
    InteractionAlertModel,
    InvitationModel,
    InvitationRedemptionModel,
    KarmaVoteHistoryModel,
    MemberModel,
    TaskModel,
)

if TYPE_CHECKING:
    import datetime

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class PostgresPilotMetrics:
    """Load only the columns required by the aggregate report."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        """Store the isolated async session factory."""
        self._sessions = sessions

    async def load_facts(self, *, to_at: datetime.datetime) -> PilotMetricFacts:
        """Load persisted facts strictly before the requested cutoff."""
        async with self._sessions() as session, session.begin():
            return PilotMetricFacts(
                invitations=await _invitations(session, to_at),
                redemptions=await _redemptions(session, to_at),
                members=await _members(session),
                tasks=await _tasks(session, to_at),
                assignments=await _assignments(session, to_at),
                transactions=await _transactions(session, to_at),
                alerts=await _alerts(session, to_at),
                disputes=await _disputes(session, to_at),
                karma_activities=await _karma_activities(session, to_at),
            )


async def _invitations(
    session: AsyncSession,
    to_at: datetime.datetime,
) -> tuple[InvitationFact, ...]:
    rows = (
        await session.execute(
            select(
                InvitationModel.id,
                InvitationModel.max_uses,
                InvitationModel.created_at,
                InvitationModel.expires_at,
                InvitationModel.revoked_at,
            ).where(InvitationModel.created_at < to_at)
        )
    ).all()
    return tuple(InvitationFact(*row) for row in rows)


async def _redemptions(
    session: AsyncSession,
    to_at: datetime.datetime,
) -> tuple[RedemptionFact, ...]:
    rows = (
        await session.execute(
            select(
                InvitationRedemptionModel.invitation_id,
                InvitationRedemptionModel.member_id,
                InvitationRedemptionModel.redeemed_at,
                MemberModel.approved_at,
            )
            .join(MemberModel, MemberModel.id == InvitationRedemptionModel.member_id)
            .where(InvitationRedemptionModel.redeemed_at < to_at)
        )
    ).all()
    return tuple(RedemptionFact(*row) for row in rows)


async def _members(session: AsyncSession) -> tuple[MemberFact, ...]:
    rows = (
        await session.execute(select(MemberModel.id, MemberModel.status, MemberModel.approved_at))
    ).all()
    return tuple(MemberFact(*row) for row in rows)


async def _tasks(session: AsyncSession, to_at: datetime.datetime) -> tuple[TaskFact, ...]:
    rows = (
        await session.execute(
            select(
                TaskModel.id,
                TaskModel.origin,
                TaskModel.creator_id,
                TaskModel.published_at,
                TaskModel.deadline_at,
                TaskModel.cancelled_at,
            ).where(TaskModel.published_at < to_at)
        )
    ).all()
    return tuple(TaskFact(*row) for row in rows)


async def _assignments(
    session: AsyncSession,
    to_at: datetime.datetime,
) -> tuple[AssignmentFact, ...]:
    rows = (
        await session.execute(
            select(
                AssignmentModel.id,
                AssignmentModel.task_id,
                AssignmentModel.performer_id,
                AssignmentModel.accepted_at,
                AssignmentModel.submitted_at,
                AssignmentModel.cancelled_at,
            ).where(AssignmentModel.accepted_at < to_at)
        )
    ).all()
    return tuple(AssignmentFact(*row) for row in rows)


async def _transactions(
    session: AsyncSession,
    to_at: datetime.datetime,
) -> tuple[TransactionFact, ...]:
    rows = (
        await session.execute(
            select(
                AccountTransactionModel.id,
                AccountTransactionModel.member_id,
                AccountTransactionModel.transaction_type,
                AccountTransactionModel.credit_delta,
                AccountTransactionModel.experience_delta,
                AccountTransactionModel.task_id,
                AccountTransactionModel.assignment_id,
                AccountTransactionModel.reversed_transaction_id,
                AccountTransactionModel.created_at,
            ).where(AccountTransactionModel.created_at < to_at)
        )
    ).all()
    return tuple(TransactionFact(*row) for row in rows)


async def _alerts(session: AsyncSession, to_at: datetime.datetime) -> tuple[AlertFact, ...]:
    rows = (
        await session.execute(
            select(
                InteractionAlertModel.opened_at,
                InteractionAlertModel.closed_at,
                InteractionAlertModel.outcome,
            ).where(InteractionAlertModel.opened_at < to_at)
        )
    ).all()
    return tuple(AlertFact(*row) for row in rows)


async def _disputes(
    session: AsyncSession,
    to_at: datetime.datetime,
) -> tuple[datetime.datetime, ...]:
    return tuple(
        await session.scalars(
            select(AssignmentDisputeModel.opened_at).where(AssignmentDisputeModel.opened_at < to_at)
        )
    )


async def _karma_activities(
    session: AsyncSession,
    to_at: datetime.datetime,
) -> tuple[TimedMemberFact, ...]:
    rows = (
        await session.execute(
            select(
                KarmaVoteHistoryModel.actor_member_id,
                KarmaVoteHistoryModel.created_at,
            ).where(KarmaVoteHistoryModel.created_at < to_at)
        )
    ).all()
    return tuple(TimedMemberFact(*row) for row in rows)
