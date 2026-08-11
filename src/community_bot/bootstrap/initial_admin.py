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
    InitialAdministratorReason,
    InitialAdministratorResult,
    InitialAdministratorService,
)
from community_bot.bootstrap.settings import get_settings
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.observability import configure_logging, configure_sentry

if TYPE_CHECKING:
    from collections.abc import Sequence


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
