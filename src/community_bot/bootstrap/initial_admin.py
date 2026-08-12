"""CLI entry point for the one-time first-administrator bootstrap."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING, Never

import structlog

from community_bot.application.initial_admin import (
    InitialAdministratorCommand,
    InitialAdministratorConflictError,
    InitialAdministratorProfileRepairCommand,
    InitialAdministratorProfileRepairResult,
    InitialAdministratorReason,
    InitialAdministratorResult,
    InitialAdministratorService,
)
from community_bot.bootstrap.settings import get_settings
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.observability import configure_logging, configure_sentry

if TYPE_CHECKING:
    from collections.abc import Sequence
    from io import TextIOBase


class _SafeArgumentParser(argparse.ArgumentParser):
    """Reject invalid input without echoing user-provided argument values."""

    def error(self, message: str) -> Never:
        """Return argparse code 2 with a privacy-safe generic message."""
        del message
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Bootstrap the first administrator or fail closed without private logs."""
    parser = _SafeArgumentParser(prog="community-bootstrap-admin")
    parser.add_argument("--telegram-user-id", required=True, type=int)
    parser.add_argument(
        "--reason",
        required=True,
        choices=[reason.value for reason in InitialAdministratorReason],
    )
    arguments = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_sentry(
        settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release,
    )
    try:
        command = InitialAdministratorCommand(
            telegram_user_id=arguments.telegram_user_id,
            reason=InitialAdministratorReason(arguments.reason),
        )
        result = asyncio.run(_bootstrap(settings.database_url, command))
    except (InitialAdministratorConflictError, ValueError):
        structlog.get_logger(process="community-bootstrap-admin").error(
            "initial_administrator_bootstrap_rejected"
        )
        return 2
    except Exception:  # noqa: BLE001 - CLI must fail closed with a safe log.
        structlog.get_logger(process="community-bootstrap-admin").error(
            "initial_administrator_bootstrap_failed"
        )
        return 1

    structlog.get_logger(process="community-bootstrap-admin").info(
        "initial_administrator_bootstrap_succeeded",
        outcome="created" if result.created else "already_applied",
    )
    return 0


def repair_main(
    argv: Sequence[str] | None = None,
    input_stream: TextIOBase | None = None,
) -> int:
    """Read private repair values from stdin and keep them out of process argv."""
    parser = _SafeArgumentParser(prog="community-repair-bootstrap-admin-profile")
    parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_sentry(
        settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release,
    )
    try:
        source = sys.stdin if input_stream is None else input_stream
        telegram_user_id = int(source.readline().strip())
        display_name = source.readline().strip()
        command = InitialAdministratorProfileRepairCommand(
            telegram_user_id=telegram_user_id,
            display_name=display_name,
        )
        result = asyncio.run(_repair(settings.database_url, command))
    except (InitialAdministratorConflictError, ValueError):
        structlog.get_logger(process="community-repair-bootstrap-admin-profile").error(
            "initial_administrator_profile_repair_rejected"
        )
        return 2
    except Exception:  # noqa: BLE001 - CLI must fail closed with a safe log.
        structlog.get_logger(process="community-repair-bootstrap-admin-profile").error(
            "initial_administrator_profile_repair_failed"
        )
        return 1

    structlog.get_logger(process="community-repair-bootstrap-admin-profile").info(
        "initial_administrator_profile_repair_succeeded",
        outcome="changed" if result.changed else "already_applied",
    )
    return 0


async def _bootstrap(
    database_url: str,
    command: InitialAdministratorCommand,
) -> InitialAdministratorResult:
    database = Database(database_url)
    try:
        return await InitialAdministratorService(
            database.initial_administrator_unit_of_work
        ).bootstrap(command)
    finally:
        await database.dispose()


async def _repair(
    database_url: str,
    command: InitialAdministratorProfileRepairCommand,
) -> InitialAdministratorProfileRepairResult:
    database = Database(database_url)
    try:
        return await InitialAdministratorService(
            database.initial_administrator_unit_of_work
        ).repair_profile(command)
    finally:
        await database.dispose()
