"""Manage an isolated production smoke scope from local Telegram profiles."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops._runtime import OpsError, fail

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_TELEGRAM_TOOL = Path(r"C:\Users\User\.codex\tools\telegram.ps1")
DEFAULT_CONTAINER = "community-bot-bot-1"


def main(argv: Sequence[str] | None = None) -> int:
    """Open, inspect, clean, or finish one marked live smoke scope."""
    parser = argparse.ArgumentParser(prog="smoke_production.py")
    parser.add_argument("--server", required=True)
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--telegram-tool", type=Path, default=DEFAULT_TELEGRAM_TOOL)
    subparsers = parser.add_subparsers(dest="command", required=True)
    begin = subparsers.add_parser("begin")
    begin.add_argument("marker")
    begin.add_argument("--profiles", nargs="+", default=("default", "tg-test"))
    status = subparsers.add_parser("status")
    status.add_argument("marker")
    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("marker")
    finish = subparsers.add_parser("finish")
    finish.add_argument("marker")
    finish.add_argument("--failed", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_command(args)
    except OpsError as exc:
        fail(str(exc))
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


def run_command(args: argparse.Namespace) -> dict[str, object]:
    """Execute one remote scope command using structured subprocess arguments."""
    remote = [
        "ssh",
        args.server,
        "docker",
        "exec",
        "-i",
        args.container,
        "community-test-run",
        args.command,
        args.marker,
    ]
    payload = None
    if args.command == "begin":
        identities = [_telegram_identity(args.telegram_tool, profile) for profile in args.profiles]
        payload = json.dumps({"participant_telegram_user_ids": identities})
    elif args.command == "finish" and args.failed:
        remote.append("--failed")
    completed = subprocess.run(
        remote,
        input=payload,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "remote test-run command failed"
        raise OpsError(detail)
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise OpsError("Remote test-run command returned invalid JSON.") from exc
    if not isinstance(result, dict):
        raise OpsError("Remote test-run command returned an invalid result object.")
    return result


def _telegram_identity(tool: Path, profile: str) -> int:
    """Read one local profile identity without including it in output or command logs."""
    command = [
        "powershell",
        "-NoProfile",
        "-File",
        str(tool),
        "-Profile",
        profile,
        "whoami",
    ]
    completed = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise OpsError(f"Telegram profile {profile!r} is unavailable.")
    try:
        result = json.loads(completed.stdout)
        identity = int(result["id"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise OpsError(f"Telegram profile {profile!r} returned an invalid identity.") from exc
    return identity


if __name__ == "__main__":
    raise SystemExit(main())
