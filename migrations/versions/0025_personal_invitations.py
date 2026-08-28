"""Add username-bound personal invitations.

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
    """Persist the normalized Telegram username targeted by a personal invitation."""
    op.add_column(
        "invitations",
        sa.Column("intended_telegram_username", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_invitations_intended_username",
        "invitations",
        (
            "intended_telegram_username IS NULL OR "
            "intended_telegram_username ~ '^[a-z0-9_]{5,32}$'"
        ),
    )


def downgrade() -> None:
    """Remove username targeting while preserving legacy invitation behavior."""
    op.drop_constraint(
        "ck_invitations_intended_username",
        "invitations",
        type_="check",
    )
    op.drop_column("invitations", "intended_telegram_username")
