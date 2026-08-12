"""Retire synthetic pilot rows from the live member and task surfaces.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove known synthetic pilot rows from active production discovery."""
    op.execute(
        """
        UPDATE tasks
        SET status = 'cancelled', cancelled_at = COALESCE(cancelled_at, now())
        WHERE status = 'published'
          AND (
              author_display_name LIKE 'CB29 Synthetic %'
              OR title LIKE 'CB29 %'
          )
        """
    )
    op.execute(
        """
        UPDATE members
        SET status = 'left'
        WHERE status = 'active'
          AND display_name LIKE 'CB29 Synthetic %'
        """
    )


def downgrade() -> None:
    """Do not reactivate retired synthetic pilot rows during downgrade."""
