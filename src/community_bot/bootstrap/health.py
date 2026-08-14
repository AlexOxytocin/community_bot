"""Machine-readable process readiness command."""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
from typing import TYPE_CHECKING

from community_bot.bootstrap.settings import get_settings
from community_bot.infrastructure.db import readiness_report

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Check one process heartbeat and critical PostgreSQL state."""
    parser = argparse.ArgumentParser(prog="community-health")
    parser.add_argument("--process", required=True, choices=("community-bot", "community-worker"))
    parser.add_argument("--not-before", type=_parse_timestamp)
    arguments = parser.parse_args(argv)
    settings = get_settings()
    report = asyncio.run(
        readiness_report(
            settings.database_url,
            process_name=arguments.process,
            heartbeat_max_age=datetime.timedelta(seconds=settings.heartbeat_max_age_seconds),
            expected_release=settings.release,
            heartbeat_not_before=arguments.not_before,
        )
    )
    print(json.dumps(report.as_dict(), sort_keys=True))  # noqa: T201 - CLI output.
    return 0 if report.healthy else 1


def _parse_timestamp(value: str) -> datetime.datetime:
    """Parse an aware ISO-8601 timestamp for deployment freshness checks."""
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as error:
        message = "timestamp must be valid ISO-8601"
        raise argparse.ArgumentTypeError(message) from error
    if parsed.tzinfo is None:
        message = "timestamp must include a UTC offset"
        raise argparse.ArgumentTypeError(message)
    return parsed.astimezone(datetime.UTC)
