"""Add an opt-in direction for crypto publications.

Revision ID: 0037
Revises: 0036
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep existing consents unchanged and crypto disabled."""
    op.add_column(
        "member_notification_preferences",
        sa.Column("crypto", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "member_notification_preferences",
        sa.Column("crypto_since", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove only the crypto preference."""
    op.drop_column("member_notification_preferences", "crypto_since")
    op.drop_column("member_notification_preferences", "crypto")
