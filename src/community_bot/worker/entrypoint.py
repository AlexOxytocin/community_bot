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
from community_bot.application.notifications import NotificationWorker
from community_bot.bootstrap.settings import get_settings
from community_bot.domain.notifications import DeliveryWindow
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.db.assignment_deadlines import PostgresAssignmentDeadlineSource
from community_bot.infrastructure.observability import configure_logging, configure_sentry
from community_bot.infrastructure.outbox import PostgresNotificationQueue
from community_bot.infrastructure.outbox.telegram import TelegramNotificationSender

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
    worker = NotificationWorker(
        queue,
        TelegramNotificationSender(bot),
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
    try:
        while True:
            now = datetime.datetime.now(datetime.UTC)
            deadlines_finalized = await deadlines.tick(now=now)
            result = await worker.tick(now=now)
            await queue.heartbeat(
                process_name="community-worker",
                release=settings.release,
                migration_revision="0012",
                now=now,
            )
            logger.info(
                "worker_tick_completed",
                deadlines_finalized=deadlines_finalized,
                **asdict(result),
            )
            if once:
                return
            await asyncio.sleep(settings.worker_poll_interval_seconds)
    finally:
        await bot.session.close()
        await database.dispose()
