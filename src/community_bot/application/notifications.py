"""Application orchestration for durable notification delivery."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from community_bot.domain.notifications import DeliveryWindow, RetryPolicy

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID


class NotificationProcessingError(RuntimeError):
    """Describe a safe, classifiable queue or delivery failure."""

    def __init__(self, error_code: str, *, permanent: bool = False) -> None:
        """Store a non-sensitive machine error code."""
        super().__init__(error_code)
        self.error_code = error_code
        self.permanent = permanent


@dataclass(frozen=True, slots=True)
class OutboxClaim:
    """Fenced claim of one domain event."""

    id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    attempt_count: int
    lease_token: UUID


@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    """Fenced claim of one addressable notification."""

    id: UUID
    member_id: UUID
    telegram_user_id: int
    notification_type: str
    payload: dict[str, Any]
    attempt_count: int
    lease_token: UUID


@dataclass(frozen=True, slots=True)
class WorkerTickResult:
    """Non-sensitive summary of one bounded worker iteration."""

    reminders_created: int
    events_materialized: int
    events_failed: int
    notifications_sent: int
    notifications_retried: int
    notifications_failed: int


class NotificationQueue(Protocol):
    """Persistence boundary used by the worker orchestration."""

    async def schedule_reminders(self, *, now: datetime.datetime, window: DeliveryWindow) -> int:
        """Stage currently due reminders and return the inserted count."""
        ...

    async def claim_outbox(
        self, *, now: datetime.datetime, limit: int, lease_duration: datetime.timedelta
    ) -> Sequence[OutboxClaim]:
        """Claim a bounded non-overlapping set of domain events."""
        ...

    async def materialize(
        self, claim: OutboxClaim, *, now: datetime.datetime, window: DeliveryWindow
    ) -> None:
        """Materialize one fenced outbox claim into recipient notifications."""
        ...

    async def fail_outbox(
        self,
        claim: OutboxClaim,
        *,
        now: datetime.datetime,
        error_code: str,
        policy: RetryPolicy,
    ) -> bool:
        """Record a safe event failure and return whether it is terminal."""
        ...

    async def claim_notifications(
        self, *, now: datetime.datetime, limit: int, lease_duration: datetime.timedelta
    ) -> Sequence[DeliveryClaim]:
        """Claim a bounded non-overlapping set of due notifications."""
        ...

    async def mark_sent(self, claim: DeliveryClaim, *, now: datetime.datetime) -> bool:
        """Persist success for the current delivery fence."""
        ...

    async def mark_delivery_failed(
        self,
        claim: DeliveryClaim,
        *,
        now: datetime.datetime,
        error_code: str,
        permanent: bool,
        policy: RetryPolicy,
    ) -> bool:
        """Persist a delivery retry or terminal failure."""
        ...

    async def heartbeat(
        self,
        *,
        process_name: str,
        release: str,
        migration_revision: str,
        now: datetime.datetime,
    ) -> None:
        """Publish one process heartbeat without sensitive data."""
        ...


class NotificationSender(Protocol):
    """External delivery boundary called only after a PostgreSQL claim commit."""

    async def send(self, claim: DeliveryClaim) -> None:
        """Send one claimed notification or raise a classified error."""
        ...


class NotificationWorker:
    """Run one bounded materialize, schedule, and delivery iteration."""

    def __init__(  # noqa: PLR0913 - explicit worker policy dependencies.
        self,
        queue: NotificationQueue,
        sender: NotificationSender,
        *,
        retry_policy: RetryPolicy | None = None,
        delivery_window: DeliveryWindow | None = None,
        batch_size: int = 25,
        lease_duration: datetime.timedelta = datetime.timedelta(minutes=2),
    ) -> None:
        """Configure explicit queue and external delivery adapters."""
        self._queue = queue
        self._sender = sender
        self._retry_policy = retry_policy or RetryPolicy()
        self._delivery_window = delivery_window or DeliveryWindow()
        self._batch_size = batch_size
        self._lease_duration = lease_duration

    async def tick(self, *, now: datetime.datetime) -> WorkerTickResult:
        """Execute one non-overlapping worker tick."""
        reminders = await self._queue.schedule_reminders(now=now, window=self._delivery_window)
        materialized = 0
        event_failures = 0
        events = await self._queue.claim_outbox(
            now=now,
            limit=self._batch_size,
            lease_duration=self._lease_duration,
        )
        for event in events:
            try:
                await self._queue.materialize(event, now=now, window=self._delivery_window)
                materialized += 1
            except NotificationProcessingError as error:
                await self._queue.fail_outbox(
                    event,
                    now=now,
                    error_code=error.error_code,
                    policy=self._retry_policy,
                )
                event_failures += 1

        sent = 0
        retried = 0
        failed = 0
        deliveries = await self._queue.claim_notifications(
            now=now,
            limit=self._batch_size,
            lease_duration=self._lease_duration,
        )
        for delivery in deliveries:
            try:
                await self._sender.send(delivery)
            except NotificationProcessingError as error:
                terminal = await self._queue.mark_delivery_failed(
                    delivery,
                    now=now,
                    error_code=error.error_code,
                    permanent=error.permanent,
                    policy=self._retry_policy,
                )
                failed += int(terminal)
                retried += int(not terminal)
            else:
                sent += int(await self._queue.mark_sent(delivery, now=now))

        return WorkerTickResult(
            reminders_created=reminders,
            events_materialized=materialized,
            events_failed=event_failures,
            notifications_sent=sent,
            notifications_retried=retried,
            notifications_failed=failed,
        )
