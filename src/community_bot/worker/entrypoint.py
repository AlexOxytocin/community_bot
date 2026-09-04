"""Background notification worker process entry point."""

from __future__ import annotations

import argparse
import asyncio
import datetime
from dataclasses import asdict
from typing import TYPE_CHECKING

import structlog
from aiogram import Bot

from community_bot.application.assignments import AssignmentDeadlineWorker, AssignmentService
from community_bot.application.membership import MembershipCheckUnavailableError
from community_bot.application.notifications import (
    DeliveryClaim,
    NotificationProcessingError,
    NotificationWorker,
)
from community_bot.bootstrap.migration_head import single_migration_head
from community_bot.bootstrap.settings import get_settings
from community_bot.domain.notifications import DeliveryWindow
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.db.assignment_deadlines import PostgresAssignmentDeadlineSource
from community_bot.infrastructure.db.community_preferences import CommunityPreferencesStore
from community_bot.infrastructure.observability import configure_logging, configure_sentry
from community_bot.infrastructure.outbox import PostgresNotificationQueue
from community_bot.infrastructure.outbox.telegram import TelegramNotificationSender
from community_bot.infrastructure.telegram_membership import AiogramTelegramMembershipChecker

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Run configuration check, one tick, or the continuous worker loop."""
    parser = argparse.ArgumentParser(prog="community-worker")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_sentry(
        settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release,
    )
    logger = structlog.get_logger(
        process="community-worker",
        environment=settings.environment,
        release=settings.release,
    )
    try:
        window = DeliveryWindow(
            start=settings.notification_window_start_local,
            end=settings.notification_window_end_local,
        )
    except ValueError:
        logger.exception("worker_configuration_invalid")
        return 2
    if arguments.check:
        logger.info("bootstrap_check_passed")
        return 0
    if settings.bot_token is None:
        logger.error("worker_configuration_invalid", code="bot_token_missing")
        return 2
    try:
        asyncio.run(_run(once=arguments.once, window=window))
    except KeyboardInterrupt:
        logger.info("worker_shutdown_requested")
    return 0


async def _run(*, once: bool, window: DeliveryWindow) -> None:
    settings = get_settings()
    if settings.bot_token is None:
        msg = "Bot token must be validated before worker composition."
        raise RuntimeError(msg)
    database = Database(settings.database_url)
    queue = PostgresNotificationQueue(database.session_factory)
    bot = Bot(token=settings.bot_token.get_secret_value())
    preferences = CommunityPreferencesStore(database.session_factory)
    membership = AiogramTelegramMembershipChecker(settings.bot_token.get_secret_value())

    async def allow_delivery(claim: DeliveryClaim) -> bool:
        if not await preferences.allows_delivery(claim.id):
            return False
        if settings.community_telegram_chat_id is None:
            return claim.notification_type != "nomad.published"
        try:
            return await membership.is_member(
                chat_id=settings.community_telegram_chat_id,
                telegram_user_id=claim.telegram_user_id,
            )
        except MembershipCheckUnavailableError as error:
            code = "membership_check_unavailable"
            raise NotificationProcessingError(code) from error

    worker = NotificationWorker(
        queue,
        TelegramNotificationSender(bot, allow_delivery=allow_delivery),
        delivery_window=window,
        batch_size=settings.worker_batch_size,
        lease_duration=datetime.timedelta(seconds=settings.worker_lease_seconds),
    )
    deadlines = AssignmentDeadlineWorker(
        PostgresAssignmentDeadlineSource(database.session_factory),
        AssignmentService(database.unit_of_work),
        batch_size=settings.worker_batch_size,
    )
    logger = structlog.get_logger(process="community-worker")
    migration_revision = single_migration_head()
    try:
        while True:
            now = datetime.datetime.now(datetime.UTC)
            if not settings.release_maintenance:
                deadlines_finalized = await deadlines.tick(now=now)
                result = await worker.tick(now=now)
                logger.info(
                    "worker_tick_completed",
                    deadlines_finalized=deadlines_finalized,
                    **asdict(result),
                )
            await queue.heartbeat(
                process_name="community-worker",
                release=settings.release,
                migration_revision=migration_revision,
                now=now,
            )
            if once:
                return
            await asyncio.sleep(settings.worker_poll_interval_seconds)
    finally:
        await membership.close()
        await bot.session.close()
        await database.dispose()
