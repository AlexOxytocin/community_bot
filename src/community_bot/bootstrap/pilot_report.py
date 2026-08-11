"""Read-only aggregate pilot report entry point."""

from __future__ import annotations

import argparse
import asyncio
import datetime
from typing import TYPE_CHECKING

from community_bot.application.pilot import PilotMetricsService
from community_bot.bootstrap.settings import get_settings
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.db.pilot import PostgresPilotMetrics

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Print one privacy-safe JSON report for an explicit UTC interval."""
    parser = argparse.ArgumentParser(prog="community-pilot-report")
    parser.add_argument("--from", dest="from_at", required=True, type=_timestamp)
    parser.add_argument("--to", dest="to_at", required=True, type=_timestamp)
    arguments = parser.parse_args(argv)
    print(  # noqa: T201 - this command exists to emit the aggregate report.
        asyncio.run(_report(arguments.from_at, arguments.to_at))
    )
    return 0


async def _report(from_at: datetime.datetime, to_at: datetime.datetime) -> str:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        report = await PilotMetricsService(PostgresPilotMetrics(database.session_factory)).report(
            from_at=from_at,
            to_at=to_at,
        )
        return report.model_dump_json(indent=2)
    finally:
        await database.dispose()


def _timestamp(value: str) -> datetime.datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.datetime.fromisoformat(normalized)
    except ValueError as error:
        message = "Timestamp must be valid ISO 8601."
        raise argparse.ArgumentTypeError(message) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        message = "Timestamp must include an UTC offset."
        raise argparse.ArgumentTypeError(message)
    return parsed.astimezone(datetime.UTC)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
