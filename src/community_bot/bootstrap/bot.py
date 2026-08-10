"""Telegram bot process entry point."""

from __future__ import annotations

from typing import TYPE_CHECKING

from community_bot.bootstrap.runner import run_process

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Run the safe bot bootstrap entry point."""
    return run_process("community-bot", argv)
