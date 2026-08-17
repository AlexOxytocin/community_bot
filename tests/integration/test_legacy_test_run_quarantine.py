"""Post-removal regression gate for retained synthetic-data quarantine."""

# ruff: noqa: PLR0915, PT018

from __future__ import annotations

import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from community_bot.domain.notifications import DeliveryWindow
from community_bot.infrastructure.db import assignments as assignment_store
from community_bot.infrastructure.db import tasks as task_store
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AssignmentModel,
    MemberModel,
    NotificationModel,
    OutboxEventModel,
    TaskModel,
    TaskTemplateModel,
)
from community_bot.infrastructure.db.models import (
    TestRunModel as RunModel,
)
from community_bot.infrastructure.db.models import (
    TestRunParticipantModel as RunParticipantModel,
)
from community_bot.infrastructure.outbox import PostgresNotificationQueue

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_legacy_test_rows_remain_quarantined_without_the_old_cli(
    database_url: str,
) -> None:
    """Active and completed test rows never enter ordinary views or recipients."""
    database = Database(database_url)
    now = datetime.datetime.now(datetime.UTC)
    active_owner = _member(110_001, "Active owner", role="administrator")
    active_participant = _member(110_002, "Active participant")
    completed_owner = _member(110_003, "Completed owner", role="administrator")
    completed_participant = _member(110_004, "Completed participant")
    outsider = _member(110_005, "Ordinary member")
    public_owner = _member(110_006, "Public owner")
    async with database.session_factory.begin() as session:
        session.add_all(
            (
                active_owner,
                active_participant,
                completed_owner,
                completed_participant,
                outsider,
                public_owner,
            )
        )
        await session.flush()
        active_run = RunModel(
            marker="TEST-POST-REMOVAL-ACTIVE",
            started_by_member_id=active_owner.id,
        )
        completed_run = RunModel(
            marker="TEST-POST-REMOVAL-COMPLETED",
            status="completed",
            started_by_member_id=completed_owner.id,
            ended_at=now,
        )
        session.add_all((active_run, completed_run))
        await session.flush()
        session.add_all(
            (
                RunParticipantModel(
                    run_id=active_run.id,
                    member_id=active_owner.id,
                ),
                RunParticipantModel(
                    run_id=active_run.id,
                    member_id=active_participant.id,
                ),
                RunParticipantModel(
                    run_id=completed_run.id,
                    member_id=completed_owner.id,
                    is_active=False,
                    left_at=now,
                ),
                RunParticipantModel(
                    run_id=completed_run.id,
                    member_id=completed_participant.id,
                    is_active=False,
                    left_at=now,
                ),
            )
        )
        template = await session.scalar(
            select(TaskTemplateModel).where(TaskTemplateModel.is_active.is_(True)).limit(1)
        )
        assert template is not None
        active_task = _task(
            template=template,
            creator=active_owner,
            title="Active synthetic task",
            test_run_id=active_run.id,
            now=now,
        )
        completed_task = _task(
            template=template,
            creator=completed_owner,
            title="Completed synthetic task",
            test_run_id=completed_run.id,
            now=now,
        )
        public_task = _task(
            template=template,
            creator=public_owner,
            title="Public task",
            test_run_id=None,
            now=now,
        )
        session.add_all((active_task, completed_task, public_task))
        await session.flush()
        completed_assignment = AssignmentModel(
            task_id=completed_task.id,
            performer_id=completed_participant.id,
            slot_number=1,
            status="accepted",
        )
        session.add(completed_assignment)
        active_event = OutboxEventModel(
            event_type="task.published",
            aggregate_type="task",
            aggregate_id=active_task.id,
            payload_json={},
            business_key=f"active-run:{active_run.id}:published",
        )
        completed_event = OutboxEventModel(
            event_type="task.published",
            aggregate_type="task",
            aggregate_id=completed_task.id,
            payload_json={},
            business_key=f"completed-run:{completed_run.id}:published",
        )
        session.add_all((active_event, completed_event))
        await session.flush()
        completed_event_id = completed_event.id

    async with database.session_factory.begin() as session:
        active_view = await task_store.list_available_tasks(
            session,
            performer_id=active_participant.id,
            level=99,
            limit=10,
            cursor_task_id=None,
            now=now,
        )
        completed_view = await task_store.list_available_tasks(
            session,
            performer_id=completed_participant.id,
            level=99,
            limit=10,
            cursor_task_id=None,
            now=now,
        )
        ordinary_view = await task_store.list_available_tasks(
            session,
            performer_id=outsider.id,
            level=99,
            limit=10,
            cursor_task_id=None,
            now=now,
        )
        completed_assignments = await assignment_store.list_assignments(
            session, completed_participant.id
        )
        with pytest.raises(PermissionError, match="outside the actor test scope"):
            await task_store.ensure_test_access(
                session,
                task_id=completed_task.id,
                member_id=completed_participant.id,
            )
    assert [item.title for item in active_view] == ["Active synthetic task"]
    assert [item.title for item in completed_view] == ["Public task"]
    assert [item.title for item in ordinary_view] == ["Public task"]
    assert completed_assignments == ()

    queue = PostgresNotificationQueue(database.session_factory)
    claims = await queue.claim_outbox(
        now=now + datetime.timedelta(seconds=1),
        limit=10,
        lease_duration=datetime.timedelta(minutes=1),
    )
    assert len(claims) == 2
    for claim in claims:
        await queue.materialize(claim, now=now, window=DeliveryWindow())
    async with database.session_factory.begin() as session:
        notification_count = await session.scalar(select(func.count(NotificationModel.id)))
        recipients = set(await session.scalars(select(NotificationModel.member_id)))
        stored_event = await session.get(OutboxEventModel, completed_event_id)
    assert notification_count == 1
    assert recipients == {active_participant.id}
    assert stored_event is not None and stored_event.status == "materialized"
    await database.dispose()


def _member(telegram_user_id: int, display_name: str, *, role: str = "member") -> MemberModel:
    return MemberModel(
        id=uuid4(),
        telegram_user_id=telegram_user_id,
        display_name=display_name,
        timezone="UTC",
        role=role,
        status="active",
    )


def _task(
    *,
    template: TaskTemplateModel,
    creator: MemberModel,
    title: str,
    test_run_id: UUID | None,
    now: datetime.datetime,
) -> TaskModel:
    return TaskModel(
        origin="member",
        test_run_id=test_run_id,
        template_id=template.id,
        template_version=template.version,
        creator_id=creator.id,
        author_display_name=creator.display_name,
        category_id=template.category_id,
        title=title,
        description="Test description",
        completion_criteria="Test completion criteria",
        materials_json={"text": "No materials"},
        input_payload_json={"context": "Test input"},
        credit_reward_per_performer=template.credit_reward,
        performer_slots=1,
        reserved_credit_total=template.credit_reward,
        estimated_minutes=template.estimated_minutes,
        minimum_level=template.minimum_level,
        format="online",
        city=None,
        deadline_at=now + datetime.timedelta(days=1),
        status="published",
        safety_snapshot_json={"public_input_keys": ["context"]},
        publish_command_id=uuid4(),
    )
