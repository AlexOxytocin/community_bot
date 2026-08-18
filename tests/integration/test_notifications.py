"""PostgreSQL integration tests for durable notification processing."""

from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.economy import ProductConfigBootstrapCoordinator
from community_bot.application.notifications import DeliveryClaim, NotificationWorker
from community_bot.bootstrap.migration_head import single_migration_head
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.domain.notifications import DeliveryWindow, RetryPolicy
from community_bot.infrastructure.db import Database, readiness_report
from community_bot.infrastructure.db.models import (
    AssignmentModel,
    MemberModel,
    NotificationModel,
    OutboxEventModel,
    TaskCancellationRequestModel,
    TaskCancellationResponseModel,
    TaskCategoryModel,
    TaskModel,
    TaskTemplateModel,
)
from community_bot.infrastructure.outbox import PostgresNotificationQueue

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_IN_WINDOW_UTC = datetime.datetime(2026, 1, 15, 12, tzinfo=datetime.UTC)


class _Sender:
    """Record fake Telegram deliveries without network access."""

    def __init__(self) -> None:
        self.sent: list[int] = []

    async def send(self, claim: DeliveryClaim) -> None:
        self.sent.append(claim.telegram_user_id)


async def _seed_published_task(
    database: Database,
    *,
    now: datetime.datetime | None = None,
) -> tuple[TaskModel, MemberModel]:
    now = now or datetime.datetime.now(datetime.UTC)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        owner = MemberModel(
            id=uuid4(),
            telegram_user_id=80_001,
            display_name="Owner",
            timezone="UTC",
            status="active",
            role="member",
        )
        recipient = MemberModel(
            id=uuid4(),
            telegram_user_id=80_002,
            display_name="Recipient",
            timezone="UTC",
            status="active",
            role="member",
        )
        inactive = MemberModel(
            id=uuid4(),
            telegram_user_id=80_003,
            display_name="Inactive",
            timezone="UTC",
            status="paused",
            role="member",
        )
        category = TaskCategoryModel(
            id=uuid4(), code="notification-test", name="Notification test", sort_order=500
        )
        template = TaskTemplateModel(
            id=uuid4(),
            category_id=category.id,
            code="notification-test",
            version=1,
            name="Notification test",
            description="Test",
            creator_instructions="Test",
            performer_instructions="Test",
            completion_criteria="Test",
            input_schema_json={},
            result_schema_json={},
            credit_reward=1,
            estimated_minutes=10,
            format="online",
            minimum_level=1,
            maximum_performers=1,
            moderation_required=False,
        )
        task = TaskModel(
            id=uuid4(),
            origin="member",
            template_id=template.id,
            template_version=1,
            creator_id=owner.id,
            author_display_name=owner.display_name,
            category_id=category.id,
            title="Test task",
            description="Test",
            completion_criteria="Test",
            materials_json={},
            input_payload_json={},
            credit_reward_per_performer=1,
            performer_slots=1,
            reserved_credit_total=1,
            estimated_minutes=10,
            minimum_level=1,
            format="online",
            deadline_at=now + datetime.timedelta(days=2),
            safety_snapshot_json={},
            publish_command_id=uuid4(),
            published_at=now,
        )
        session.add_all((owner, recipient, inactive, category))
        await session.flush()
        session.add(template)
        await session.flush()
        session.add(task)
    return task, recipient


async def _add_outbox(  # noqa: PLR0913 - explicit event fixture fields stay readable.
    database: Database,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    business_key: str,
    now: datetime.datetime | None = None,
) -> None:
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        event = OutboxEventModel(
            id=uuid4(),
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload_json={"token": "must-not-be-copied"},
            business_key=business_key,
        )
        if now is not None:
            event.created_at = now
            event.next_attempt_at = now
        session.add(event)


async def test_registration_approval_is_immediate_and_suppresses_inactive_recipient(
    database_url: str,
) -> None:
    """Approval bypasses quiet hours but stale active access is checked before delivery."""
    database = Database(database_url)
    outside_window = datetime.datetime(2026, 1, 15, 23, tzinfo=datetime.UTC)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        member = MemberModel(
            id=uuid4(),
            telegram_user_id=80_010,
            display_name="New member",
            timezone="UTC",
            status="active",
            role="member",
        )
        session.add(member)
    await _add_outbox(
        database,
        event_type="registration.approved",
        aggregate_type="member",
        aggregate_id=member.id,
        business_key="registration-approved-immediate",
        now=outside_window,
    )
    queue = PostgresNotificationQueue(database.session_factory)
    claims = await queue.claim_outbox(
        now=outside_window,
        limit=10,
        lease_duration=datetime.timedelta(seconds=30),
    )
    assert len(claims) == 1
    await queue.materialize(claims[0], now=outside_window, window=DeliveryWindow())
    async with sessions() as session:
        notification = await session.scalar(select(NotificationModel))
    assert notification is not None
    assert notification.scheduled_at == outside_window

    async with sessions.begin() as session:
        persisted = await session.get(MemberModel, member.id)
        assert persisted is not None
        persisted.status = "paused"
    deliveries = await queue.claim_notifications(
        now=outside_window,
        limit=10,
        lease_duration=datetime.timedelta(seconds=30),
    )
    assert deliveries == ()
    async with sessions() as session:
        assert await session.scalar(select(NotificationModel.status)) == "failed"
    await database.dispose()


async def test_two_workers_materialize_and_deliver_one_privacy_minimal_notification(
    database_url: str,
) -> None:
    """SKIP LOCKED, deduplication, recipient rules, and success survive restart."""
    database = Database(database_url)
    task, recipient = await _seed_published_task(database, now=_IN_WINDOW_UTC)
    await _add_outbox(
        database,
        event_type="task.published",
        aggregate_type="task",
        aggregate_id=task.id,
        business_key="notification-test:published",
        now=_IN_WINDOW_UTC,
    )
    first = PostgresNotificationQueue(database.session_factory)
    second = PostgresNotificationQueue(database.session_factory)
    now = _IN_WINDOW_UTC + datetime.timedelta(seconds=1)

    claim_sets = await asyncio.wait_for(
        asyncio.gather(
            first.claim_outbox(now=now, limit=1, lease_duration=datetime.timedelta(minutes=2)),
            second.claim_outbox(now=now, limit=1, lease_duration=datetime.timedelta(minutes=2)),
        ),
        timeout=10,
    )
    claims = tuple(item for group in claim_sets for item in group)
    assert len(claims) == 1
    await first.materialize(claims[0], now=now, window=DeliveryWindow())

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        notifications = (await session.scalars(select(NotificationModel))).all()
        event = await session.get(OutboxEventModel, claims[0].id)
    assert event is not None
    assert event.status == "materialized"
    assert len(notifications) == 1
    assert notifications[0].member_id == recipient.id
    assert set(notifications[0].payload_json) == {
        "event_type",
        "aggregate_type",
        "aggregate_id",
    }
    assert "must-not-be-copied" not in str(notifications[0].payload_json)

    sender = _Sender()
    worker = NotificationWorker(first, sender)
    result = await worker.tick(now=now)
    repeated = await worker.tick(now=now)
    assert result.notifications_sent == 1
    assert repeated.notifications_sent == 0
    assert sender.sent == [recipient.telegram_user_id]

    async with sessions.begin() as session:
        persisted_recipient = await session.get(MemberModel, recipient.id)
        assert persisted_recipient is not None
        persisted_recipient.status = "paused"
    await _add_outbox(
        database,
        event_type="task.published",
        aggregate_type="task",
        aggregate_id=task.id,
        business_key="notification-test:no-recipient",
        now=now + datetime.timedelta(minutes=1),
    )
    empty_claim = (
        await first.claim_outbox(
            now=now + datetime.timedelta(minutes=1),
            limit=1,
            lease_duration=datetime.timedelta(minutes=2),
        )
    )[0]
    await first.materialize(
        empty_claim,
        now=now + datetime.timedelta(minutes=1),
        window=DeliveryWindow(),
    )
    async with sessions() as session:
        empty_event = await session.get(OutboxEventModel, empty_claim.id)
        total_notifications = await session.scalar(
            select(func.count()).select_from(NotificationModel)
        )
    assert empty_event is not None
    assert empty_event.status == "materialized"
    assert total_notifications == 1
    await database.dispose()


async def test_cancellation_request_materializes_actions_and_becomes_obsolete(  # noqa: PLR0915
    database_url: str,
) -> None:
    """Only the assigned performer receives a current durable cancellation prompt."""
    database = Database(database_url)
    task, performer = await _seed_published_task(database, now=_IN_WINDOW_UTC)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    response_id = uuid4()
    request_id = uuid4()
    async with sessions.begin() as session:
        assignment = AssignmentModel(
            id=uuid4(), task_id=task.id, performer_id=performer.id, slot_number=1
        )
        request = TaskCancellationRequestModel(
            id=request_id,
            task_id=task.id,
            requested_by_member_id=task.creator_id,
            status="pending",
        )
        response = TaskCancellationResponseModel(
            id=response_id,
            request_id=request_id,
            assignment_id=assignment.id,
            performer_id=performer.id,
            status="pending",
        )
        session.add_all((assignment, request))
        await session.flush()
        session.add(response)
        await session.flush()
        session.add(
            OutboxEventModel(
                id=uuid4(),
                event_type="task.cancellation_requested",
                aggregate_type="task_cancellation_response",
                aggregate_id=response_id,
                payload_json={
                    "task_id": str(task.id),
                    "title": task.title,
                    "private": "must-not-be-copied",
                },
                business_key="notification-test:cancellation-requested",
                created_at=_IN_WINDOW_UTC,
                next_attempt_at=_IN_WINDOW_UTC,
            )
        )
    queue = PostgresNotificationQueue(database.session_factory)
    claims = await queue.claim_outbox(
        now=_IN_WINDOW_UTC,
        limit=1,
        lease_duration=datetime.timedelta(minutes=2),
    )
    assert len(claims) == 1
    await queue.materialize(claims[0], now=_IN_WINDOW_UTC, window=DeliveryWindow())
    async with sessions() as session:
        notification = await session.scalar(
            select(NotificationModel).where(
                NotificationModel.notification_type == "task.cancellation_requested"
            )
        )
    assert notification is not None
    assert notification.member_id == performer.id
    assert notification.payload_json["aggregate_id"] == str(response_id)
    assert notification.payload_json["title"] == task.title
    assert "private" not in notification.payload_json

    async with sessions.begin() as session:
        stored_request = await session.get(TaskCancellationRequestModel, request_id)
        stored_response = await session.get(TaskCancellationResponseModel, response_id)
        assert stored_request is not None
        assert stored_response is not None
        stored_request.status = "declined"
        stored_response.status = "declined"
    deliveries = await queue.claim_notifications(
        now=_IN_WINDOW_UTC + datetime.timedelta(seconds=1),
        limit=1,
        lease_duration=datetime.timedelta(minutes=2),
    )
    assert deliveries == ()
    async with sessions() as session:
        obsolete = await session.get(NotificationModel, notification.id)
    assert obsolete is not None
    assert obsolete.status == "failed"
    assert obsolete.last_error_code == "notification_obsolete"

    after_deadline = task.deadline_at + datetime.timedelta(seconds=1)
    deadline_notification_id = uuid4()
    async with sessions.begin() as session:
        stored_request = await session.get(TaskCancellationRequestModel, request_id)
        stored_response = await session.get(TaskCancellationResponseModel, response_id)
        assert stored_request is not None
        assert stored_response is not None
        stored_request.status = "pending"
        stored_response.status = "pending"
        session.add(
            NotificationModel(
                id=deadline_notification_id,
                member_id=performer.id,
                notification_type="task.cancellation_requested",
                payload_json={"aggregate_id": str(response_id), "title": task.title},
                scheduled_at=after_deadline,
                next_attempt_at=after_deadline,
                deduplication_key="notification-test:cancellation-after-deadline",
            )
        )
    assert not await queue.claim_notifications(
        now=after_deadline,
        limit=1,
        lease_duration=datetime.timedelta(minutes=2),
    )
    async with sessions() as session:
        deadline_obsolete = await session.get(NotificationModel, deadline_notification_id)
    assert deadline_obsolete is not None
    assert deadline_obsolete.status == "failed"
    assert deadline_obsolete.last_error_code == "notification_obsolete"
    await database.dispose()


async def test_expired_lease_is_reclaimed_and_stale_completion_is_rejected(
    database_url: str,
) -> None:
    """A restarted worker safely owns expired work and fences the old token."""
    database = Database(database_url)
    _, recipient = await _seed_published_task(database)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    now = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    async with sessions.begin() as session:
        session.add(
            NotificationModel(
                id=uuid4(),
                member_id=recipient.id,
                notification_type="task.published",
                payload_json={},
                scheduled_at=now,
                next_attempt_at=now,
                deduplication_key="lease-reclaim",
            )
        )
    queue = PostgresNotificationQueue(database.session_factory)
    old = (
        await queue.claim_notifications(
            now=now, limit=1, lease_duration=datetime.timedelta(seconds=30)
        )
    )[0]
    assert not await queue.claim_notifications(
        now=now + datetime.timedelta(seconds=20),
        limit=1,
        lease_duration=datetime.timedelta(seconds=30),
    )
    new = (
        await queue.claim_notifications(
            now=now + datetime.timedelta(seconds=31),
            limit=1,
            lease_duration=datetime.timedelta(seconds=30),
        )
    )[0]
    assert new.lease_token != old.lease_token
    assert not await queue.mark_sent(old, now=now + datetime.timedelta(seconds=32))
    assert await queue.mark_sent(new, now=now + datetime.timedelta(seconds=32))
    assert not await queue.claim_notifications(
        now=now + datetime.timedelta(days=1),
        limit=1,
        lease_duration=datetime.timedelta(seconds=30),
    )

    retry_time = now + datetime.timedelta(days=2)
    async with sessions.begin() as session:
        session.add(
            NotificationModel(
                id=uuid4(),
                member_id=recipient.id,
                notification_type="task.published",
                payload_json={},
                scheduled_at=retry_time,
                next_attempt_at=retry_time,
                deduplication_key="bounded-retry",
            )
        )
    retry_claim = (
        await queue.claim_notifications(
            now=retry_time,
            limit=1,
            lease_duration=datetime.timedelta(seconds=30),
        )
    )[0]
    assert not await queue.mark_delivery_failed(
        retry_claim,
        now=retry_time,
        error_code="telegram_temporarily_unavailable",
        permanent=False,
        policy=RetryPolicy(),
    )
    terminal_claim = (
        await queue.claim_notifications(
            now=retry_time + datetime.timedelta(hours=1),
            limit=1,
            lease_duration=datetime.timedelta(seconds=30),
        )
    )[0]
    assert await queue.mark_delivery_failed(
        terminal_claim,
        now=retry_time + datetime.timedelta(hours=1),
        error_code="telegram_recipient_unavailable",
        permanent=True,
        policy=RetryPolicy(),
    )
    await database.dispose()


async def test_reminders_are_idempotent_and_address_the_performer_and_reviewer(
    database_url: str,
) -> None:
    """Deadline goes to the performer while 24h/48h review reminders go to the owner."""
    database = Database(database_url)
    task, performer = await _seed_published_task(database, now=_IN_WINDOW_UTC)
    submitted_at = task.published_at
    assignment = AssignmentModel(
        id=uuid4(),
        task_id=task.id,
        performer_id=performer.id,
        slot_number=1,
        status="submitted",
        submitted_at=submitted_at,
        review_deadline_at=submitted_at + datetime.timedelta(hours=72),
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add(assignment)
    queue = PostgresNotificationQueue(database.session_factory)

    first_due = submitted_at + datetime.timedelta(hours=25)
    second_due = submitted_at + datetime.timedelta(hours=49)
    assert await queue.schedule_reminders(now=first_due, window=DeliveryWindow()) == 2
    assert await queue.schedule_reminders(now=first_due, window=DeliveryWindow()) == 0
    assert await queue.schedule_reminders(now=second_due, window=DeliveryWindow()) == 1

    async with sessions() as session:
        reminders = (await session.scalars(select(NotificationModel))).all()
    by_type = {item.notification_type: item.member_id for item in reminders}
    assert by_type["task_deadline_reminder"] == performer.id
    assert by_type["review_reminder_24h"] == task.creator_id
    assert by_type["review_reminder_48h"] == task.creator_id

    async with sessions.begin() as session:
        persisted_assignment = await session.get(AssignmentModel, assignment.id)
        assert persisted_assignment is not None
        persisted_assignment.status = "approved"
    assert not await queue.claim_notifications(
        now=second_due + datetime.timedelta(hours=1),
        limit=10,
        lease_duration=datetime.timedelta(seconds=30),
    )
    async with sessions() as session:
        reminder_statuses = (await session.scalars(select(NotificationModel.status))).all()
    assert reminder_statuses == ["failed", "failed", "failed"]
    assert await queue.schedule_reminders(now=second_due, window=DeliveryWindow()) == 0
    await database.dispose()


async def test_poison_event_is_bounded_and_does_not_block_neighbor(
    database_url: str,
) -> None:
    """Unsupported materialization terminates after five attempts while valid work completes."""
    database = Database(database_url)
    task, recipient = await _seed_published_task(database)
    await _add_outbox(
        database,
        event_type="unsupported",
        aggregate_type="unsupported",
        aggregate_id=uuid4(),
        business_key="poison",
    )
    await _add_outbox(
        database,
        event_type="task.published",
        aggregate_type="task",
        aggregate_id=task.id,
        business_key="neighbor",
    )
    queue = PostgresNotificationQueue(database.session_factory)
    sender = _Sender()
    worker = NotificationWorker(
        queue,
        sender,
        retry_policy=RetryPolicy(maximum_attempts=5),
    )
    start = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    for attempt in range(5):
        await worker.tick(now=start + datetime.timedelta(days=attempt))

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        poison = await session.scalar(
            select(OutboxEventModel).where(OutboxEventModel.business_key == "poison")
        )
        neighbor = await session.scalar(
            select(OutboxEventModel).where(OutboxEventModel.business_key == "neighbor")
        )
        notification_count = await session.scalar(
            select(func.count()).select_from(NotificationModel)
        )
    assert poison is not None
    assert poison.status == "failed"
    assert poison.attempt_count == 5
    assert poison.last_error_code == "unsupported_outbox_event"
    assert neighbor is not None
    assert neighbor.status == "materialized"
    assert notification_count == 1
    assert sender.sent == [recipient.telegram_user_id]
    await database.dispose()


async def test_readiness_checks_head_heartbeat_and_failed_outbox(  # noqa: PLR0915
    database_url: str,
) -> None:
    """Readiness is green only with the current schema, fresh process, and no poison rows."""
    database = Database(database_url)
    queue = PostgresNotificationQueue(database.session_factory)
    now = datetime.datetime.now(datetime.UTC)
    await queue.heartbeat(
        process_name="community-worker",
        release="sha",
        migration_revision=single_migration_head(),
        now=now,
    )
    missing_config = await readiness_report(
        database_url,
        process_name="community-worker",
        heartbeat_max_age=datetime.timedelta(minutes=3),
        now=now,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        admin = MemberModel(
            telegram_user_id=89_001,
            display_name="Readiness administrator",
            timezone="UTC",
            role="administrator",
            status="active",
        )
        session.add(admin)
    active = await ProductConfigBootstrapCoordinator(
        database.unit_of_work,
        load_product_config_candidate,
    ).prepare(
        candidate_path=Path("config/product-config.v2.json"),
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    healthy = await readiness_report(
        database_url,
        process_name="community-worker",
        heartbeat_max_age=datetime.timedelta(minutes=3),
        expected_release="sha",
        heartbeat_not_before=now - datetime.timedelta(seconds=1),
        now=now,
    )
    wrong_release = await readiness_report(
        database_url,
        process_name="community-worker",
        heartbeat_max_age=datetime.timedelta(minutes=3),
        expected_release="other-sha",
        now=now,
    )
    before_deploy = await readiness_report(
        database_url,
        process_name="community-worker",
        heartbeat_max_age=datetime.timedelta(minutes=3),
        expected_release="sha",
        heartbeat_not_before=now + datetime.timedelta(seconds=1),
        now=now,
    )
    restart_at = now + datetime.timedelta(seconds=1)
    await queue.heartbeat(
        process_name="community-worker",
        release="sha",
        migration_revision=single_migration_head(),
        now=restart_at,
    )
    after_restart_tick = await readiness_report(
        database_url,
        process_name="community-worker",
        heartbeat_max_age=datetime.timedelta(minutes=3),
        expected_release="sha",
        heartbeat_not_before=restart_at,
        now=restart_at,
    )
    stale = await readiness_report(
        database_url,
        process_name="community-worker",
        heartbeat_max_age=datetime.timedelta(minutes=3),
        now=now + datetime.timedelta(minutes=4),
    )
    await queue.heartbeat(
        process_name="community-worker",
        release="sha",
        migration_revision="wrong-revision",
        now=now,
    )
    wrong_revision = await readiness_report(
        database_url,
        process_name="community-worker",
        heartbeat_max_age=datetime.timedelta(minutes=3),
        expected_release="sha",
        now=now,
    )
    await queue.heartbeat(
        process_name="community-worker",
        release="sha",
        migration_revision=single_migration_head(),
        now=now + datetime.timedelta(seconds=6),
    )
    future = await readiness_report(
        database_url,
        process_name="community-worker",
        heartbeat_max_age=datetime.timedelta(minutes=3),
        expected_release="sha",
        now=now,
    )
    async with sessions.begin() as session:
        await session.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('unexpected-head')")
        )
    multiple_db_heads = await readiness_report(
        database_url,
        process_name="community-worker",
        heartbeat_max_age=datetime.timedelta(minutes=3),
        expected_release="sha",
        now=now,
    )
    async with sessions.begin() as session:
        await session.execute(
            text("DELETE FROM alembic_version WHERE version_num = 'unexpected-head'")
        )

    async with sessions.begin() as session:
        persisted = await session.get(MemberModel, admin.id)
        assert persisted is not None
        persisted.level_config_version_id = None
    stale_config = await readiness_report(
        database_url,
        process_name="community-worker",
        heartbeat_max_age=datetime.timedelta(minutes=3),
        now=now,
    )

    assert not missing_config.healthy
    assert missing_config.code == "product_config_incomplete"
    assert healthy.healthy
    assert healthy.product_config
    assert healthy.code == "ready"
    assert not wrong_release.healthy
    assert wrong_release.code == "heartbeat_release_mismatch"
    assert not before_deploy.healthy
    assert before_deploy.code == "heartbeat_before_deploy"
    assert after_restart_tick.healthy
    assert after_restart_tick.code == "ready"
    assert not stale.healthy
    assert stale.code == "heartbeat_stale"
    assert not wrong_revision.healthy
    assert wrong_revision.code == "heartbeat_revision_mismatch"
    assert not future.healthy
    assert future.code == "heartbeat_in_future"
    assert not multiple_db_heads.healthy
    assert multiple_db_heads.code == "migration_mismatch"
    assert not stale_config.healthy
    assert stale_config.code == "product_config_incomplete"
    assert active.version == 2
    await database.dispose()
