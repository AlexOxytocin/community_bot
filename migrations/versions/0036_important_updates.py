"""Add an opt-in direction for important community updates.

Revision ID: 0036
Revises: 0035
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep existing choices and start the new subscription disabled."""
    op.add_column(
        "member_notification_preferences",
        sa.Column("important", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "member_notification_preferences",
        sa.Column("important_since", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove only the important-updates preference."""
    op.drop_column("member_notification_preferences", "important_since")
    op.drop_column("member_notification_preferences", "important")
