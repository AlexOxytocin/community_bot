"""PostgreSQL source for bounded assignment deadline finalization."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, exists, or_, select

from community_bot.infrastructure.db.models import AssignmentModel, TaskModel

if TYPE_CHECKING:
    import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class PostgresAssignmentDeadlineSource:
    """List due lifecycles; the application service owns locking and settlement."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        """Use the process-owned async session factory."""
        self._sessions = sessions

    async def due_task_ids(self, *, now: datetime.datetime, limit: int) -> tuple[UUID, ...]:
        """Return one deterministic bounded batch of due task IDs."""
        async with self._sessions() as session:
            values = await session.scalars(
                select(TaskModel.id)
                .where(
                    TaskModel.deadline_at <= now,
                    or_(
                        TaskModel.status.in_(("published", "closed_for_new_performers")),
                        and_(
                            TaskModel.status == "settling",
                            exists(
                                select(1).where(
                                    AssignmentModel.task_id == TaskModel.id,
                                    AssignmentModel.status == "accepted",
                                )
                            ),
                        ),
                    ),
                )
                .order_by(TaskModel.deadline_at, TaskModel.id)
                .limit(limit)
            )
            return tuple(values)

    async def due_review_ids(self, *, now: datetime.datetime, limit: int) -> tuple[UUID, ...]:
        """Select overdue submitted results independently of the task deadline."""
        async with self._sessions() as session:
            values = await session.scalars(
                select(AssignmentModel.id)
                .where(
                    AssignmentModel.status == "submitted",
                    AssignmentModel.review_deadline_at <= now,
                )
                .order_by(AssignmentModel.review_deadline_at, AssignmentModel.id)
                .limit(limit)
            )
            return tuple(values)

    async def due_rejection_ids(self, *, now: datetime.datetime, limit: int) -> tuple[UUID, ...]:
        """Select rejections whose dispute window ended without an open dispute."""
        async with self._sessions() as session:
            values = await session.scalars(
                select(AssignmentModel.id)
                .where(
                    AssignmentModel.status == "rejected_pending_dispute",
                    AssignmentModel.reject_dispute_deadline_at <= now,
                )
                .order_by(AssignmentModel.reject_dispute_deadline_at, AssignmentModel.id)
                .limit(limit)
            )
            return tuple(values)
