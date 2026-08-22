"""Store the signed Telegram profile photo URL for a member.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep the optional avatar URL alongside the member profile."""
    op.add_column("members", sa.Column("avatar_url", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove the optional Telegram avatar URL."""
    op.drop_column("members", "avatar_url")
