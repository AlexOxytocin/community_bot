"""PostgreSQL queue adapter for outbox materialization and delivery."""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert

from community_bot.application.notifications import (
    DeliveryClaim,
    NotificationProcessingError,
    OutboxClaim,
)
from community_bot.domain.notifications import DeliveryWindow, NotificationError, RetryPolicy
from community_bot.infrastructure.db.community_preferences import subscription_allows
from community_bot.infrastructure.db.models import (
    AssignmentModel,
    InteractionAlertModel,
    MemberModel,
    MemberNotificationPreferencesModel,
    ModerationCaseModel,
    NotificationModel,
    OutboxEventModel,
    ProcessHeartbeatModel,
    TaskCancellationRequestModel,
    TaskCancellationResponseModel,
    TaskModel,
    TestRunModel,
    TestRunParticipantModel,
)
from community_bot.infrastructure.db.test_runs import participant_ids

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_ACTIVE_ASSIGNMENT_STATUSES = {
    "accepted",
    "submitted",
    "rejected_pending_dispute",
    "disputed",
    "reviewer_required",
}
_REVIEWABLE_STATUSES = {"submitted", "reviewer_required"}
_STALE_OUTBOX_LEASE = "stale_outbox_lease"
_RECIPIENT_MISSING = "notification_recipient_missing"
_INVALID_MEMBER_TIMEZONE = "invalid_member_timezone"
_UNSUPPORTED_OUTBOX_EVENT = "unsupported_outbox_event"
_OUTBOX_AGGREGATE_MISSING = "outbox_aggregate_missing"
_AWARE_DATETIME_REQUIRED = "Datetime values must be timezone-aware."


@dataclass(frozen=True, slots=True)
class _Recipient:
    member_id: UUID
    timezone: str


class PostgresNotificationQueue:
    """Coordinate queue claims without holding locks across external calls."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        """Use a process-owned factory that creates one session per operation."""
        self._sessions = sessions

    async def claim_outbox(
        self, *, now: datetime.datetime, limit: int, lease_duration: datetime.timedelta
    ) -> Sequence[OutboxClaim]:
        """Claim non-overlapping due events with transaction-scoped row locks."""
        now = _utc(now)
        async with self._sessions() as session, session.begin():
            rows = (
                await session.scalars(
                    select(OutboxEventModel)
                    .where(
                        or_(
                            and_(
                                OutboxEventModel.status == "pending",
                                OutboxEventModel.next_attempt_at <= now,
                            ),
                            and_(
                                OutboxEventModel.status == "processing",
                                OutboxEventModel.lease_expires_at <= now,
                            ),
                        )
                    )
                    .order_by(OutboxEventModel.next_attempt_at, OutboxEventModel.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            claims: list[OutboxClaim] = []
            for row in rows:
                token = uuid.uuid4()
                row.status = "processing"
                row.attempt_count += 1
                row.lease_token = token
                row.lease_expires_at = now + lease_duration
                row.last_error_code = None
                claims.append(
                    OutboxClaim(
                        id=row.id,
                        event_type=row.event_type,
                        aggregate_type=row.aggregate_type,
                        aggregate_id=row.aggregate_id,
                        attempt_count=row.attempt_count,
                        lease_token=token,
                    )
                )
            return tuple(claims)

    async def materialize(  # noqa: C901 - explicit allowlisted event projections.
        self, claim: OutboxClaim, *, now: datetime.datetime, window: DeliveryWindow
    ) -> None:
        """Create all addressable notifications and finish the exact event lease."""
        now = _utc(now)
        async with self._sessions() as session, session.begin():
            event = await session.scalar(
                select(OutboxEventModel)
                .where(
                    OutboxEventModel.id == claim.id,
                    OutboxEventModel.status == "processing",
                    OutboxEventModel.lease_token == claim.lease_token,
                )
                .with_for_update()
            )
            if event is None:
                raise NotificationProcessingError(_STALE_OUTBOX_LEASE, permanent=True)
            recipients = await self._event_recipients(session, event)
            safe_payload: dict[str, object] = (
                {"amount": event.payload_json["amount"]}
                if event.event_type == "wallet.transfer_received"
                else {}
            )
            if event.event_type == "task.cancellation_requested":
                title = event.payload_json.get("title")
                task_id = event.payload_json.get("task_id")
                if isinstance(title, str) and isinstance(task_id, str):
                    safe_payload = {"title": title, "task_id": task_id}
            elif event.event_type == "nomad.published":
                safe_payload = {
                    "message_url": event.payload_json["message_url"],
                    "occurred_at": event.payload_json["occurred_at"],
                }
            elif event.event_type == "assignment_rejection_pending_dispute":
                rejection_reason = event.payload_json.get("rejection_reason")
                rejection_comment = event.payload_json.get("rejection_comment")
                if isinstance(rejection_reason, str):
                    safe_payload = {"rejection_reason": rejection_reason}
                    if isinstance(rejection_comment, str):
                        safe_payload["rejection_comment"] = rejection_comment
            for recipient in recipients:
                occurred_at = (
                    datetime.datetime.fromisoformat(str(safe_payload["occurred_at"]))
                    if event.event_type == "nomad.published"
                    else event.created_at
                )
                if not await subscription_allows(
                    session, recipient.member_id, event.event_type, occurred_at
                ):
                    continue
                if event.event_type == "registration.approved":
                    scheduled_at = now
                else:
                    try:
                        scheduled_at = window.schedule(
                            candidate=now,
                            timezone_name=recipient.timezone,
                        )
                    except NotificationError as error:
                        raise NotificationProcessingError(
                            _INVALID_MEMBER_TIMEZONE, permanent=True
                        ) from error
                await self._insert_notification(
                    session,
                    member_id=recipient.member_id,
                    notification_type=event.event_type,
                    payload={
                        "event_type": event.event_type,
                        "aggregate_type": event.aggregate_type,
                        "aggregate_id": str(event.aggregate_id),
                        **safe_payload,
                    },
                    scheduled_at=scheduled_at,
                    deduplication_key=f"outbox:{event.id}:member:{recipient.member_id}",
                )
            event.status = "materialized"
            event.published_at = now
            event.lease_token = None
            event.lease_expires_at = None
            event.last_error_code = None

    async def fail_outbox(
        self,
        claim: OutboxClaim,
        *,
        now: datetime.datetime,
        error_code: str,
        policy: RetryPolicy,
    ) -> bool:
        """Retry or terminate one exact event claim."""
        now = _utc(now)
        async with self._sessions() as session, session.begin():
            event = await session.scalar(
                select(OutboxEventModel)
                .where(
                    OutboxEventModel.id == claim.id,
                    OutboxEventModel.status == "processing",
                    OutboxEventModel.lease_token == claim.lease_token,
                )
                .with_for_update()
            )
            if event is None:
                return False
            terminal = event.attempt_count >= policy.maximum_attempts
            event.status = "failed" if terminal else "pending"
            event.last_error_code = error_code
            event.lease_token = None
            event.lease_expires_at = None
            if not terminal:
                event.next_attempt_at = policy.next_attempt_at(
                    now=now,
                    attempt_count=event.attempt_count,
                    identity=str(event.id),
                )
            return terminal

    async def schedule_reminders(self, *, now: datetime.datetime, window: DeliveryWindow) -> int:
        """Idempotently stage task and review reminders from current domain state."""
        now = _utc(now)
        created = 0
        async with self._sessions() as session, session.begin():
            assignments = (
                await session.scalars(
                    select(AssignmentModel).where(
                        AssignmentModel.status.in_(_ACTIVE_ASSIGNMENT_STATUSES)
                    )
                )
            ).all()
            for assignment in assignments:
                member = await session.get(MemberModel, assignment.performer_id)
                task = await session.get(TaskModel, assignment.task_id)
                if member is None or task is None:
                    continue
                if task.status in {"published", "settling"} and task.deadline_at > now:
                    deadline_candidate = task.deadline_at - datetime.timedelta(hours=24)
                    if deadline_candidate <= now:
                        created += await self._stage_reminder(
                            session,
                            member=member,
                            notification_type="task_deadline_reminder",
                            aggregate_id=assignment.id,
                            candidate=deadline_candidate,
                            deadline=task.deadline_at,
                            window=window,
                            suffix=task.deadline_at.isoformat(),
                        )
                if (
                    assignment.status in _REVIEWABLE_STATUSES
                    and assignment.review_deadline_at is not None
                    and assignment.review_deadline_at > now
                ):
                    reviewers = await self._review_recipients(
                        session,
                        task=task,
                        performer_id=assignment.performer_id,
                    )
                    for reviewer in reviewers:
                        for elapsed_hours in (24, 48):
                            candidate = assignment.review_deadline_at - datetime.timedelta(
                                hours=72 - elapsed_hours
                            )
                            if candidate > now:
                                continue
                            created += await self._stage_reminder(
                                session,
                                member=reviewer,
                                notification_type=f"review_reminder_{elapsed_hours}h",
                                aggregate_id=assignment.id,
                                candidate=candidate,
                                deadline=assignment.review_deadline_at,
                                window=window,
                                suffix=assignment.review_deadline_at.isoformat(),
                            )
            return created

    async def claim_notifications(
        self, *, now: datetime.datetime, limit: int, lease_duration: datetime.timedelta
    ) -> Sequence[DeliveryClaim]:
        """Claim due addressable notifications and return minimal delivery DTOs."""
        now = _utc(now)
        async with self._sessions() as session, session.begin():
            rows = (
                await session.scalars(
                    select(NotificationModel)
                    .where(
                        NotificationModel.scheduled_at <= now,
                        or_(
                            and_(
                                NotificationModel.status == "pending",
                                NotificationModel.next_attempt_at <= now,
                            ),
                            and_(
                                NotificationModel.status == "processing",
                                NotificationModel.lease_expires_at <= now,
                            ),
                        ),
                    )
                    .order_by(NotificationModel.next_attempt_at, NotificationModel.scheduled_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            claims: list[DeliveryClaim] = []
            for row in rows:
                member = await session.get(MemberModel, row.member_id)
                if member is None:
                    row.status = "failed"
                    row.last_error_code = "notification_recipient_missing"
                    continue
                if not await self._notification_is_current(session, row, member=member, now=now):
                    row.status = "failed"
                    row.last_error_code = "notification_obsolete"
                    row.lease_token = None
                    row.lease_expires_at = None
                    continue
                token = uuid.uuid4()
                row.status = "processing"
                row.attempt_count += 1
                row.lease_token = token
                row.lease_expires_at = now + lease_duration
                row.last_error_code = None
                claims.append(
                    DeliveryClaim(
                        id=row.id,
                        member_id=row.member_id,
                        telegram_user_id=member.telegram_user_id,
                        notification_type=row.notification_type,
                        payload=dict(row.payload_json),
                        attempt_count=row.attempt_count,
                        lease_token=token,
                    )
                )
            return tuple(claims)

    async def mark_sent(self, claim: DeliveryClaim, *, now: datetime.datetime) -> bool:
        """Record success only for the current fenced lease."""
        async with self._sessions() as session, session.begin():
            row = await self._locked_delivery(session, claim)
            if row is None:
                return False
            row.status = "sent"
            row.sent_at = _utc(now)
            row.lease_token = None
            row.lease_expires_at = None
            row.last_error_code = None
            return True

    async def mark_delivery_failed(
        self,
        claim: DeliveryClaim,
        *,
        now: datetime.datetime,
        error_code: str,
        permanent: bool,
        policy: RetryPolicy,
    ) -> bool:
        """Record bounded retry or terminal delivery failure."""
        now = _utc(now)
        async with self._sessions() as session, session.begin():
            row = await self._locked_delivery(session, claim)
            if row is None:
                return False
            terminal = permanent or row.attempt_count >= policy.maximum_attempts
            row.status = "failed" if terminal else "pending"
            row.last_error_code = error_code
            row.lease_token = None
            row.lease_expires_at = None
            if not terminal:
                row.next_attempt_at = policy.next_attempt_at(
                    now=now,
                    attempt_count=row.attempt_count,
                    identity=str(row.id),
                )
            return terminal

    async def heartbeat(
        self,
        *,
        process_name: str,
        release: str,
        migration_revision: str,
        now: datetime.datetime,
    ) -> None:
        """Upsert one non-sensitive process readiness heartbeat."""
        statement = insert(ProcessHeartbeatModel).values(
            process_name=process_name,
            release=release,
            migration_revision=migration_revision,
            observed_at=_utc(now),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[ProcessHeartbeatModel.process_name],
            set_={
                "release": statement.excluded.release,
                "migration_revision": statement.excluded.migration_revision,
                "observed_at": statement.excluded.observed_at,
            },
        )
        async with self._sessions() as session, session.begin():
            await session.execute(statement)

    async def _event_recipients(  # noqa: C901, PLR0912, PLR0915 - explicit event map.
        self, session: AsyncSession, event: OutboxEventModel
    ) -> tuple[_Recipient, ...]:
        member_ids: set[UUID] = set()
        if event.event_type == "nomad.published" and event.aggregate_type == "nomad_post":
            members = await session.scalars(
                select(MemberModel)
                .join(
                    MemberNotificationPreferencesModel,
                    MemberNotificationPreferencesModel.member_id == MemberModel.id,
                )
                .where(
                    MemberModel.status == "active",
                    MemberNotificationPreferencesModel.nomad.is_(True),
                )
            )
            return tuple(_Recipient(member.id, member.timezone) for member in members)
        if event.aggregate_type == "task":
            task = await session.get(TaskModel, event.aggregate_id)
            if task is None:
                raise NotificationProcessingError(_OUTBOX_AGGREGATE_MISSING, permanent=True)
            if event.event_type == "task.published":
                if task.test_run_id is not None:
                    member_ids.update(
                        await session.scalars(
                            select(TestRunParticipantModel.member_id)
                            .join(TestRunModel, TestRunModel.id == TestRunParticipantModel.run_id)
                            .where(
                                TestRunParticipantModel.run_id == task.test_run_id,
                                TestRunParticipantModel.is_active.is_(True),
                                TestRunModel.status == "active",
                            )
                        )
                    )
                else:
                    active_test_member = (
                        select(TestRunParticipantModel.member_id)
                        .join(TestRunModel, TestRunModel.id == TestRunParticipantModel.run_id)
                        .where(
                            TestRunParticipantModel.is_active.is_(True),
                            TestRunModel.status == "active",
                        )
                    )
                    member_ids.update(
                        await session.scalars(
                            select(MemberModel.id).where(
                                MemberModel.status == "active",
                                MemberModel.id.not_in(active_test_member),
                            )
                        )
                    )
                if task.creator_id is not None:
                    member_ids.discard(task.creator_id)
            else:
                if task.creator_id is not None:
                    member_ids.add(task.creator_id)
                member_ids.update(
                    await session.scalars(
                        select(AssignmentModel.performer_id).where(
                            AssignmentModel.task_id == task.id
                        )
                    )
                )
        elif event.aggregate_type == "assignment":
            assignment = await session.get(AssignmentModel, event.aggregate_id)
            if assignment is None:
                raise NotificationProcessingError(_OUTBOX_AGGREGATE_MISSING, permanent=True)
            member_ids.add(assignment.performer_id)
            task = await session.get(TaskModel, assignment.task_id)
            if task is not None and task.creator_id is not None:
                member_ids.add(task.creator_id)
            if event.event_type == "assignment_disputed":
                member_ids.update(
                    await session.scalars(
                        select(MemberModel.id).where(
                            MemberModel.status == "active",
                            MemberModel.role.in_(("moderator", "administrator")),
                        )
                    )
                )
        elif event.aggregate_type == "task_cancellation_response":
            response = await session.get(TaskCancellationResponseModel, event.aggregate_id)
            if response is None:
                raise NotificationProcessingError(_OUTBOX_AGGREGATE_MISSING, permanent=True)
            member_ids.add(response.performer_id)
        elif event.aggregate_type == "task_cancellation_request":
            request = await session.get(TaskCancellationRequestModel, event.aggregate_id)
            if request is None:
                raise NotificationProcessingError(_OUTBOX_AGGREGATE_MISSING, permanent=True)
            member_ids.add(request.requested_by_member_id)
        elif event.aggregate_type == "moderation_case":
            case = await session.get(ModerationCaseModel, event.aggregate_id)
            if case is None:
                raise NotificationProcessingError(_OUTBOX_AGGREGATE_MISSING, permanent=True)
            member_ids.add(case.opened_by_member_id)
            assignment = await session.get(AssignmentModel, case.assignment_id)
            if assignment is not None:
                member_ids.add(assignment.performer_id)
                task = await session.get(TaskModel, assignment.task_id)
                if task is not None and task.creator_id is not None:
                    member_ids.add(task.creator_id)
                if task is not None and task.test_run_id is not None:
                    member_ids.intersection_update(await participant_ids(session, task.test_run_id))
        elif event.aggregate_type == "interaction_alert":
            alert = await session.get(InteractionAlertModel, event.aggregate_id)
            if alert is None:
                raise NotificationProcessingError(_OUTBOX_AGGREGATE_MISSING, permanent=True)
            administrators = await session.scalars(
                select(MemberModel.id).where(
                    MemberModel.role == "administrator",
                    MemberModel.status == "active",
                    MemberModel.permissions_json.contains(["interaction_review"]),
                )
            )
            member_ids.update(administrators)
        elif event.aggregate_type == "member" and event.event_type in {
            "registration.approved",
            "wallet.transfer_received",
        }:
            member_ids.add(event.aggregate_id)
        elif event.aggregate_type == "member" and event.event_type == "registration.submitted":
            member_ids.update(
                await session.scalars(
                    select(MemberModel.id).where(
                        MemberModel.status == "active",
                        MemberModel.role.in_(("moderator", "administrator")),
                    )
                )
            )
        else:
            raise NotificationProcessingError(_UNSUPPORTED_OUTBOX_EVENT, permanent=True)

        if not member_ids:
            return ()
        members = (
            await session.scalars(
                select(MemberModel).where(
                    MemberModel.id.in_(member_ids),
                    MemberModel.status == "active",
                )
            )
        ).all()
        return tuple(_Recipient(member_id=item.id, timezone=item.timezone) for item in members)

    async def _review_recipients(
        self,
        session: AsyncSession,
        *,
        task: TaskModel,
        performer_id: UUID,
    ) -> tuple[MemberModel, ...]:
        """Resolve the member-task owner or independent community administrators."""
        if task.creator_id is not None:
            creator = await session.get(MemberModel, task.creator_id)
            return () if creator is None else (creator,)
        administrators = (
            await session.scalars(
                select(MemberModel).where(
                    MemberModel.role == "administrator",
                    MemberModel.status == "active",
                    MemberModel.id != performer_id,
                )
            )
        ).all()
        if task.test_run_id is not None:
            participant_set = set(await participant_ids(session, task.test_run_id))
            administrators = [item for item in administrators if item.id in participant_set]
        return tuple(administrators)

    async def _notification_is_current(  # noqa: C901, PLR0911 - explicit lifecycle checks.
        self,
        session: AsyncSession,
        notification: NotificationModel,
        *,
        member: MemberModel,
        now: datetime.datetime,
    ) -> bool:
        """Suppress a scheduled reminder after its domain state becomes terminal."""
        if member.status != "active" or not await subscription_allows(
            session, member.id, notification.notification_type, notification.created_at
        ):
            return False
        if notification.notification_type == "task.cancellation_requested":
            aggregate_id = notification.payload_json.get("aggregate_id")
            if not isinstance(aggregate_id, str):
                return False
            try:
                response_id = uuid.UUID(aggregate_id)
            except ValueError:
                return False
            row = (
                await session.execute(
                    select(
                        TaskCancellationResponseModel,
                        TaskCancellationRequestModel,
                        AssignmentModel,
                        TaskModel,
                    )
                    .join(
                        TaskCancellationRequestModel,
                        TaskCancellationRequestModel.id == TaskCancellationResponseModel.request_id,
                    )
                    .join(
                        AssignmentModel,
                        AssignmentModel.id == TaskCancellationResponseModel.assignment_id,
                    )
                    .join(TaskModel, TaskModel.id == TaskCancellationRequestModel.task_id)
                    .where(TaskCancellationResponseModel.id == response_id)
                )
            ).one_or_none()
            if row is None:
                return False
            response, request, assignment, task = row
            return (
                response.performer_id == member.id
                and response.status == "pending"
                and request.status == "pending"
                and assignment.status == "accepted"
                and task.status in {"published", "closed_for_new_performers"}
                and task.deadline_at > now
            )
        if notification.notification_type not in {
            "task_deadline_reminder",
            "review_reminder_24h",
            "review_reminder_48h",
        }:
            return (
                notification.notification_type != "registration.approved"
                or member.status == "active"
            )
        aggregate_id = notification.payload_json.get("aggregate_id")
        if not isinstance(aggregate_id, str):
            return False
        try:
            assignment_id = uuid.UUID(aggregate_id)
        except ValueError:
            return False
        assignment = await session.get(AssignmentModel, assignment_id)
        if assignment is None:
            return False
        if notification.notification_type == "task_deadline_reminder":
            task = await session.get(TaskModel, assignment.task_id)
            return (
                assignment.status in _ACTIVE_ASSIGNMENT_STATUSES
                and task is not None
                and task.status in {"published", "settling"}
                and task.deadline_at > now
            )
        return (
            assignment.status in _REVIEWABLE_STATUSES
            and assignment.review_deadline_at is not None
            and assignment.review_deadline_at > now
        )

    async def _stage_reminder(  # noqa: PLR0913 - explicit reminder identity fields.
        self,
        session: AsyncSession,
        *,
        member: MemberModel,
        notification_type: str,
        aggregate_id: UUID,
        candidate: datetime.datetime,
        deadline: datetime.datetime,
        window: DeliveryWindow,
        suffix: str,
    ) -> int:
        try:
            scheduled_at = window.schedule(
                candidate=candidate,
                timezone_name=member.timezone,
                deadline=deadline,
            )
            status = "pending"
            error_code = None
        except NotificationError:
            scheduled_at = _utc(candidate)
            status = "failed"
            error_code = "invalid_member_timezone"
        return await self._insert_notification(
            session,
            member_id=member.id,
            notification_type=notification_type,
            payload={"aggregate_id": str(aggregate_id), "deadline_at": deadline.isoformat()},
            scheduled_at=scheduled_at,
            deduplication_key=(f"reminder:{notification_type}:{aggregate_id}:{member.id}:{suffix}"),
            status=status,
            error_code=error_code,
        )

    async def _insert_notification(  # noqa: PLR0913 - persistence record fields.
        self,
        session: AsyncSession,
        *,
        member_id: UUID,
        notification_type: str,
        payload: dict[str, Any],
        scheduled_at: datetime.datetime,
        deduplication_key: str,
        status: str = "pending",
        error_code: str | None = None,
    ) -> int:
        statement = (
            insert(NotificationModel)
            .values(
                id=uuid.uuid4(),
                member_id=member_id,
                notification_type=notification_type,
                payload_json=payload,
                status=status,
                scheduled_at=scheduled_at,
                next_attempt_at=scheduled_at,
                last_error_code=error_code,
                deduplication_key=deduplication_key,
            )
            .on_conflict_do_nothing(index_elements=[NotificationModel.deduplication_key])
            .returning(NotificationModel.id)
        )
        return int((await session.scalar(statement)) is not None)

    async def _locked_delivery(
        self, session: AsyncSession, claim: DeliveryClaim
    ) -> NotificationModel | None:
        return await session.scalar(
            select(NotificationModel)
            .where(
                NotificationModel.id == claim.id,
                NotificationModel.status == "processing",
                NotificationModel.lease_token == claim.lease_token,
            )
            .with_for_update()
        )


def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(_AWARE_DATETIME_REQUIRED)
    return value.astimezone(datetime.UTC)
