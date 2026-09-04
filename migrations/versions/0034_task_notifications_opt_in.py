"""Require opt-in for task notifications without changing saved preferences.

Revision ID: 0034
Revises: 0033
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Disable tasks by default for new preference rows only."""
    op.alter_column("member_notification_preferences", "tasks", server_default=sa.false())


def downgrade() -> None:
    """Restore the old insertion default, preserving explicit settings."""
    op.alter_column("member_notification_preferences", "tasks", server_default=sa.true())
