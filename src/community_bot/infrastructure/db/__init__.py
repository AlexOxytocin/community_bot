"""Database infrastructure adapters."""

from __future__ import annotations

from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.health import database_healthcheck

__all__ = ["Database", "database_healthcheck"]
