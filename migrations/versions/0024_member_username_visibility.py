"""Add a member-controlled public username visibility flag.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep existing usernames public until their owners change the setting."""
    op.add_column(
        "members",
        sa.Column(
            "show_telegram_username",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column("members", "show_telegram_username", server_default=None)


def downgrade() -> None:
    """Remove the member privacy preference."""
    op.drop_column("members", "show_telegram_username")
