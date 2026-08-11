"""PostgreSQL outbox adapter boundary."""

from __future__ import annotations

from community_bot.infrastructure.outbox.postgres import PostgresNotificationQueue

__all__ = ["PostgresNotificationQueue"]
