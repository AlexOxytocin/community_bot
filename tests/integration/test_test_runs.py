"""PostgreSQL proof for bidirectional live test-card isolation."""

from __future__ import annotations

import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from community_bot.application.test_runs import TestRunError as RunError
from community_bot.application.test_runs import TestRunService as RunService
from community_bot.domain.notifications import DeliveryWindow
from community_bot.infrastructure.db import tasks as task_store
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    MemberModel,
    NotificationModel,
    OutboxEventModel,
    TaskModel,
    TaskTemplateModel,
)
from community_bot.infrastructure.outbox import PostgresNotificationQueue

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_test_cards_are_visible_only_inside_the_active_run(database_url: str) -> None:
    """Participants see only test cards while outsiders see only ordinary cards."""
    database = Database(database_url)
    try:
        owner = MemberModel(
            telegram_user_id=81_001,
            display_name="Test owner",
            timezone="UTC",
            role="administrator",
            status="active",
            permissions_json=[
                "interaction_review",
                "karma_review",
                "member_read",
                "superadministrator",
            ],
        )
        participant = MemberModel(
            telegram_user_id=81_002,
            display_name="Test participant",
            timezone="UTC",
            role="member",
            status="active",
        )
        reviewer = MemberModel(
            telegram_user_id=81_005,
            display_name="Test reviewer",
            timezone="UTC",
            role="administrator",
            status="active",
            permissions_json=["interaction_review", "karma_review", "member_read"],
        )
        outsider = MemberModel(
            telegram_user_id=81_003,
            display_name="Outsider",
            timezone="UTC",
            role="member",
            status="active",
        )
        public_owner = MemberModel(
            telegram_user_id=81_004,
            display_name="Public owner",
            timezone="UTC",
            role="member",
            status="active",
        )
        async with database.session_factory.begin() as session:
            session.add_all((owner, participant, reviewer, outsider, public_owner))
        run = await RunService(database.unit_of_work).begin(
            marker="TEST-INTEGRATION-01",
            participant_telegram_user_ids=(
                owner.telegram_user_id,
                participant.telegram_user_id,
                reviewer.telegram_user_id,
            ),
        )
        now = datetime.datetime.now(datetime.UTC)
        async with database.session_factory.begin() as session:
            template = await session.scalar(
                select(TaskTemplateModel).where(TaskTemplateModel.is_active.is_(True)).limit(1)
            )
            assert template is not None
            test_task = _task(
                template=template,
                creator=owner,
                title="Isolated test card",
                test_run_id=run.scope.id,
                now=now,
            )
            public_task = _task(
                template=template,
                creator=public_owner,
                title="Public card",
                test_run_id=None,
                now=now,
            )
            session.add_all((test_task, public_task))
            await session.flush()
            session.add(
                OutboxEventModel(
                    event_type="task.published",
                    aggregate_type="task",
                    aggregate_id=test_task.id,
                    payload_json={},
                    business_key=f"test-run:{run.scope.id}:published",
                )
            )
        async with database.session_factory.begin() as session:
            inside = await task_store.list_available_tasks(
                session,
                performer_id=participant.id,
                level=99,
                limit=10,
                cursor_task_id=None,
                now=now,
            )
            outside = await task_store.list_available_tasks(
                session,
                performer_id=outsider.id,
                level=99,
                limit=10,
                cursor_task_id=None,
                now=now,
            )
            await task_store.ensure_test_access(
                session, task_id=test_task.id, member_id=participant.id
            )
            with pytest.raises(PermissionError, match="outside the actor test scope"):
                await task_store.ensure_test_access(
                    session, task_id=test_task.id, member_id=outsider.id
                )
        assert [item.title for item in inside] == ["Isolated test card"]
        assert [item.title for item in outside] == ["Public card"]
        queue = PostgresNotificationQueue(database.session_factory)
        claims = await queue.claim_outbox(
            now=now + datetime.timedelta(seconds=1),
            limit=10,
            lease_duration=datetime.timedelta(minutes=1),
        )
        assert len(claims) == 1
        await queue.materialize(claims[0], now=now, window=DeliveryWindow())
        async with database.session_factory.begin() as session:
            recipients = tuple(await session.scalars(select(NotificationModel.member_id)))
        assert set(recipients) == {participant.id, reviewer.id}
        with pytest.raises(RunError, match="tasks=1"):
            await RunService(database.unit_of_work).finish(marker=run.scope.marker)
        async with database.session_factory.begin() as session:
            await task_store.save_task_status(
                session, task_id=test_task.id, status=task_store.TaskStatus.CANCELLED
            )
            template = await session.scalar(
                select(TaskTemplateModel).where(TaskTemplateModel.is_active.is_(True)).limit(1)
            )
            assert template is not None
            session.add(
                _community_task(
                    template=template,
                    creator=owner,
                    reviewer=reviewer,
                    test_run_id=run.scope.id,
                    now=now,
                )
            )
        cleaned = await RunService(database.unit_of_work).cleanup(run.scope.marker)
        assert cleaned.blockers.tasks == 0
        finished = await RunService(database.unit_of_work).finish(marker=run.scope.marker)
        assert finished.status == "completed"
    finally:
        await database.dispose()


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


def _community_task(
    *,
    template: TaskTemplateModel,
    creator: MemberModel,
    reviewer: MemberModel,
    test_run_id: UUID,
    now: datetime.datetime,
) -> TaskModel:
    task = _task(
        template=template,
        creator=creator,
        title="Disposable community test card",
        test_run_id=test_run_id,
        now=now,
    )
    task.origin = "community"
    task.creator_id = None
    task.created_by_admin_id = creator.id
    task.reviewer_admin_id = reviewer.id
    task.community_approved_by_admin_id = creator.id
    task.reserved_credit_total = 0
    return task
