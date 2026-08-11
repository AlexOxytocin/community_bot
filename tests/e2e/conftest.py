"""Reuse the isolated PostgreSQL 18 fixtures for end-to-end stories."""

from __future__ import annotations

from tests.integration.conftest import database_url, postgresql_server_url

__all__ = ["database_url", "postgresql_server_url"]
