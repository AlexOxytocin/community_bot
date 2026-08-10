"""Shared safe bootstrap behavior for executable processes."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import structlog

from community_bot.bootstrap.settings import get_settings
from community_bot.infrastructure.observability.logging import configure_logging

if TYPE_CHECKING:
    from collections.abc import Sequence


def run_process(process_name: str, argv: Sequence[str] | None = None) -> int:
    """Run a bootstrap check or fail safely until the process runtime exists."""
    parser = argparse.ArgumentParser(prog=process_name)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate process configuration without external operations.",
    )
    arguments = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = structlog.get_logger(process=process_name, environment=settings.environment)

    if arguments.check:
        logger.info("bootstrap_check_passed")
        return 0

    logger.error("runtime_not_implemented")
    return 2
