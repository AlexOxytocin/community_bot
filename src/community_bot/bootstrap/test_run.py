"""Operator CLI for isolated live test-run scopes."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import TYPE_CHECKING

from community_bot.application.test_runs import TestRunError, TestRunService
from community_bot.bootstrap.settings import get_settings
from community_bot.infrastructure.db import Database

if TYPE_CHECKING:
    from collections.abc import Sequence

    from community_bot.application.test_runs import TestRunSnapshot


def main(argv: Sequence[str] | None = None) -> int:
    """Start, inspect, clean, or finish a run without printing participant identities."""
    parser = argparse.ArgumentParser(prog="community-test-run")
    subparsers = parser.add_subparsers(dest="command", required=True)
    begin = subparsers.add_parser("begin")
    begin.add_argument("marker")
    status = subparsers.add_parser("status")
    status.add_argument("marker")
    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("marker")
    finish = subparsers.add_parser("finish")
    finish.add_argument("marker")
    finish.add_argument("--failed", action="store_true")
    args = parser.parse_args(argv)
    try:
        snapshot = asyncio.run(_run(args))
    except (TestRunError, json.JSONDecodeError, ValueError) as exc:
        parser.exit(2, f"test-run error: {exc}\n")
    sys.stdout.write(
        json.dumps(
            {
                "marker": snapshot.scope.marker,
                "status": snapshot.status,
                "participant_count": snapshot.participant_count,
                "blockers": {
                    "drafts": snapshot.blockers.drafts,
                    "tasks": snapshot.blockers.tasks,
                    "assignments": snapshot.blockers.assignments,
                },
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


async def _run(args: argparse.Namespace) -> TestRunSnapshot:
    database = Database(get_settings().database_url)
    service = TestRunService(database.unit_of_work)
    try:
        if args.command == "begin":
            payload = json.load(sys.stdin)
            values = payload.get("participant_telegram_user_ids")
            if not isinstance(values, list) or not all(isinstance(item, int) for item in values):
                message = "stdin must contain integer participant_telegram_user_ids."
                raise ValueError(message)
            return await service.begin(
                marker=args.marker,
                participant_telegram_user_ids=values,
            )
        if args.command == "finish":
            return await service.finish(marker=args.marker, failed=args.failed)
        if args.command == "cleanup":
            return await service.cleanup(args.marker)
        return await service.status(args.marker)
    finally:
        await database.dispose()
