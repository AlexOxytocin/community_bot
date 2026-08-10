"""Structured logging configuration."""

from __future__ import annotations

import logging

import structlog


def configure_logging(log_level: str) -> None:
    """Configure standard-library and structured logging for one process."""
    logging.basicConfig(format="%(message)s", level=log_level, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
