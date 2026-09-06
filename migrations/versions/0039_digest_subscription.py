"""Add the default-on weekly digest subscription.

Revision ID: 0039
Revises: 0038
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Enable the new digest for current and future members without historical catch-up."""
    op.add_column(
        "member_notification_preferences",
        sa.Column("digest", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "member_notification_preferences",
        sa.Column(
            "digest_since",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )
    op.execute("UPDATE member_notification_preferences SET revision=revision+1")


def downgrade() -> None:
    """Remove only the digest preference."""
    op.drop_column("member_notification_preferences", "digest_since")
    op.drop_column("member_notification_preferences", "digest")
