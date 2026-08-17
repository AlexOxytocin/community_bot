"""Read boundaries for quarantined synthetic test data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from community_bot.application.test_runs import TestRunScope
from community_bot.infrastructure.db.models import (
    TestRunModel,
    TestRunParticipantModel,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def active_scope(session: AsyncSession, member_id: UUID) -> TestRunScope | None:
    """Return the member's single active test scope."""
    row = (
        await session.execute(
            select(TestRunModel.id, TestRunModel.marker)
            .join(TestRunParticipantModel, TestRunParticipantModel.run_id == TestRunModel.id)
            .where(
                TestRunParticipantModel.member_id == member_id,
                TestRunParticipantModel.is_active.is_(True),
                TestRunModel.status == "active",
            )
        )
    ).one_or_none()
    return None if row is None else TestRunScope(*row)


async def participant_ids(session: AsyncSession, run_id: UUID) -> tuple[UUID, ...]:
    """Return active participants of one active run."""
    return tuple(
        await session.scalars(
            select(TestRunParticipantModel.member_id)
            .join(TestRunModel, TestRunModel.id == TestRunParticipantModel.run_id)
            .where(
                TestRunParticipantModel.run_id == run_id,
                TestRunParticipantModel.is_active.is_(True),
                TestRunModel.status == "active",
            )
        )
    )
