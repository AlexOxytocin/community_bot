"""ASGI entry point for the internal Community Mini App service."""

from __future__ import annotations

import argparse
import asyncio
import datetime
from typing import TYPE_CHECKING

import uvicorn

from community_bot.bootstrap.settings import get_settings
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.observability import configure_logging, configure_sentry
from community_bot.transport.web import create_web_app

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Validate or run the internal web process."""
    parser = argparse.ArgumentParser(prog="community-web")
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_sentry(
        settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release,
    )
    database = Database(settings.database_url)
    app = create_web_app(
        settings=settings,
        database=database,
        heartbeat_not_before=datetime.datetime.now(datetime.UTC),
    )
    if arguments.check:
        asyncio.run(database.dispose())
        return 0
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)  # noqa: S104
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
