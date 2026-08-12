"""Telegram long-polling bot process entry point."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime
from typing import TYPE_CHECKING

import structlog
from aiogram import Bot, Dispatcher

from community_bot.application.assignments import AssignmentService
from community_bot.application.catalog import CatalogService
from community_bot.application.economy import EconomyQueryService
from community_bot.application.moderation import ModerationService
from community_bot.application.navigation import NavigationService
from community_bot.application.registration import InviteTokenCodec, RegistrationService
from community_bot.application.reputation import ReputationService
from community_bot.application.tasks import TaskService
from community_bot.bootstrap.settings import get_settings
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.observability import configure_logging, configure_sentry
from community_bot.infrastructure.outbox import PostgresNotificationQueue
from community_bot.transport.telegram.assignments import build_assignment_router
from community_bot.transport.telegram.catalog import build_catalog_router
from community_bot.transport.telegram.conversation import build_conversation_router
from community_bot.transport.telegram.moderation import build_moderation_router
from community_bot.transport.telegram.navigation import build_navigation_router
from community_bot.transport.telegram.registration import build_registration_router
from community_bot.transport.telegram.reputation import build_reputation_router
from community_bot.transport.telegram.tasks import build_task_router

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Validate configuration or run the existing Telegram routers."""
    parser = argparse.ArgumentParser(prog="community-bot")
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_sentry(
        settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release,
    )
    logger = structlog.get_logger(
        process="community-bot",
        environment=settings.environment,
        release=settings.release,
    )
    if arguments.check:
        logger.info("bootstrap_check_passed")
        return 0
    if settings.bot_token is None or settings.invite_token_secret is None:
        logger.error("bot_configuration_invalid", code="required_secret_missing")
        return 2
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("bot_shutdown_requested")
    return 0


async def _run() -> None:
    settings = get_settings()
    if settings.bot_token is None or settings.invite_token_secret is None:
        msg = "Bot secrets must be validated before runtime composition."
        raise RuntimeError(msg)
    database = Database(settings.database_url)
    queue = PostgresNotificationQueue(database.session_factory)
    bot = Bot(token=settings.bot_token.get_secret_value())
    dispatcher = _dispatcher(
        database,
        invite_token_secret=settings.invite_token_secret.get_secret_value(),
    )
    heartbeat = asyncio.create_task(_heartbeat_loop(queue), name="bot-heartbeat")
    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        await bot.session.close()
        await database.dispose()


def _dispatcher(database: Database, *, invite_token_secret: str) -> Dispatcher:
    """Compose all implemented Telegram transport routers."""
    unit_of_work = database.unit_of_work
    dispatcher = Dispatcher()
    catalog = CatalogService(unit_of_work)
    moderation = ModerationService(unit_of_work)
    registration = RegistrationService(unit_of_work, InviteTokenCodec(invite_token_secret))
    reputation = ReputationService(unit_of_work)
    tasks = TaskService(unit_of_work)
    dispatcher.include_router(
        build_navigation_router(
            navigation=NavigationService(unit_of_work),
            catalog=catalog,
            tasks=tasks,
            economy=EconomyQueryService(unit_of_work),
            registration=registration,
            reputation=reputation,
            moderation=moderation,
        )
    )
    dispatcher.include_router(build_catalog_router(catalog))
    dispatcher.include_router(build_assignment_router(AssignmentService(unit_of_work)))
    dispatcher.include_router(build_moderation_router(moderation))
    dispatcher.include_router(build_reputation_router(reputation))
    dispatcher.include_router(build_task_router(tasks, include_text_fallback=False))
    dispatcher.include_router(build_registration_router(registration, include_text_fallback=False))
    dispatcher.include_router(build_conversation_router(tasks, registration))
    return dispatcher


async def _heartbeat_loop(queue: PostgresNotificationQueue) -> None:
    """Keep bot readiness visible without coupling handlers to operations."""
    settings = get_settings()
    while True:
        await queue.heartbeat(
            process_name="community-bot",
            release=settings.release,
            migration_revision="0011",
            now=datetime.datetime.now(datetime.UTC),
        )
        await asyncio.sleep(60)
