"""Backfill active member level config cache.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Resolve active members whose level cache was not tied to the active config."""
    op.execute(
        """
        UPDATE members AS member
        SET
            level_number = (
                SELECT level.level_number
                FROM levels AS level
                WHERE level.product_config_version_id = active.product_config_version_id
                  AND level.experience_required <= member.experience_total_cached
                ORDER BY level.experience_required DESC, level.level_number DESC
                LIMIT 1
            ),
            level_config_version_id = active.product_config_version_id
        FROM active_product_config AS active
        WHERE active.singleton_key
          AND member.status = 'active'
          AND member.level_config_version_id IS DISTINCT FROM active.product_config_version_id
        """
    )


def downgrade() -> None:
    """Do not erase repaired level caches during downgrade."""
