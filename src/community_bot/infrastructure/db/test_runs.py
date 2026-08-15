# ruff: noqa: ANN201, EM101, TRY003
"""PostgreSQL persistence for isolated live test runs."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from sqlalchemy import exists, func, select, update

from community_bot.application.test_runs import (
    TestRunBlockers,
    TestRunError,
    TestRunScope,
    TestRunSnapshot,
)
from community_bot.domain.members import MemberStatus
from community_bot.infrastructure.db.models import (
    AssignmentModel,
    MemberModel,
    TaskCreationDraftModel,
    TaskModel,
    TestRunModel,
    TestRunParticipantModel,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

_ACTIVE_ASSIGNMENTS = (
    "accepted",
    "submitted",
    "rejected_pending_dispute",
    "disputed",
    "reviewer_required",
)


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


async def create_run(
    session: AsyncSession,
    *,
    marker: str,
    started_by_member_id: UUID,
    participant_ids: Sequence[UUID],
) -> TestRunSnapshot:
    """Create one active run and claim each participant exactly once."""
    if await session.scalar(select(TestRunModel.id).where(TestRunModel.marker == marker)):
        raise TestRunError("Test marker already exists.")
    active = await session.scalar(
        select(TestRunParticipantModel.member_id).where(
            TestRunParticipantModel.member_id.in_(participant_ids),
            TestRunParticipantModel.is_active.is_(True),
        )
    )
    if active is not None:
        raise TestRunError("A participant already belongs to another active test run.")
    run = TestRunModel(marker=marker, started_by_member_id=started_by_member_id)
    session.add(run)
    await session.flush()
    session.add_all(
        TestRunParticipantModel(run_id=run.id, member_id=member_id) for member_id in participant_ids
    )
    await session.flush()
    return TestRunSnapshot(
        TestRunScope(run.id, marker),
        "active",
        len(participant_ids),
        TestRunBlockers(0, 0, 0),
    )


async def snapshot(
    session: AsyncSession, marker: str, *, for_update: bool = False
) -> TestRunSnapshot | None:
    """Load one run and count its nonterminal objects."""
    statement = select(TestRunModel).where(TestRunModel.marker == marker)
    if for_update:
        statement = statement.with_for_update()
    run = await session.scalar(statement)
    if run is None:
        return None
    participants = int(
        await session.scalar(
            select(func.count(TestRunParticipantModel.member_id)).where(
                TestRunParticipantModel.run_id == run.id
            )
        )
        or 0
    )
    drafts = int(
        await session.scalar(
            select(func.count(TaskCreationDraftModel.id)).where(
                TaskCreationDraftModel.test_run_id == run.id,
                TaskCreationDraftModel.current_step != "published",
            )
        )
        or 0
    )
    tasks = int(
        await session.scalar(
            select(func.count(TaskModel.id)).where(
                TaskModel.test_run_id == run.id,
                TaskModel.status.in_(("published", "settling")),
            )
        )
        or 0
    )
    assignments = int(
        await session.scalar(
            select(func.count(AssignmentModel.id))
            .join(TaskModel, TaskModel.id == AssignmentModel.task_id)
            .where(
                TaskModel.test_run_id == run.id,
                AssignmentModel.status.in_(_ACTIVE_ASSIGNMENTS),
            )
        )
        or 0
    )
    return TestRunSnapshot(
        TestRunScope(run.id, run.marker),
        run.status,
        participants,
        TestRunBlockers(drafts, tasks, assignments),
    )


async def finish(session: AsyncSession, marker: str, *, failed: bool) -> TestRunSnapshot:
    """Finish one already checked run and release its participants."""
    run = await session.scalar(
        select(TestRunModel).where(TestRunModel.marker == marker).with_for_update()
    )
    if run is None:
        raise TestRunError("Test run does not exist.")
    now = datetime.datetime.now(datetime.UTC)
    run.status = "failed" if failed else "completed"
    run.ended_at = now
    await session.execute(
        update(TestRunParticipantModel)
        .where(TestRunParticipantModel.run_id == run.id)
        .values(is_active=False, left_at=now)
    )
    await session.flush()
    result = await snapshot(session, marker)
    if result is None:  # pragma: no cover - row is locked in this transaction.
        raise TestRunError("Test run disappeared during completion.")
    return result


async def cleanup(session: AsyncSession, marker: str) -> int:
    """Cancel only unclaimed published community cards in an active test run."""
    run = await session.scalar(
        select(TestRunModel).where(
            TestRunModel.marker == marker,
            TestRunModel.status == "active",
        )
    )
    if run is None:
        raise TestRunError("Active test run does not exist.")
    now = datetime.datetime.now(datetime.UTC)
    cancelled_ids = tuple(
        await session.scalars(
            update(TaskModel)
            .where(
                TaskModel.test_run_id == run.id,
                TaskModel.origin == "community",
                TaskModel.status == "published",
                ~exists().where(
                    AssignmentModel.task_id == TaskModel.id,
                    AssignmentModel.status.in_(_ACTIVE_ASSIGNMENTS),
                ),
            )
            .values(status="cancelled", cancelled_at=now, updated_at=now)
            .returning(TaskModel.id)
        )
    )
    await session.flush()
    return len(cancelled_ids)


def active_member_models_statement(telegram_user_ids: Sequence[int]):
    """Build the exact active-member lookup used by the application adapter."""
    return select(MemberModel).where(
        MemberModel.telegram_user_id.in_(telegram_user_ids),
        MemberModel.status == MemberStatus.ACTIVE.value,
    )
