"""Store normalized member-owned profile avatars.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create one bounded normalized avatar row per member."""
    op.create_table(
        "member_avatars",
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("content_type = 'image/jpeg'", name="ck_member_avatars_content_type"),
        sa.CheckConstraint(
            "octet_length(content) BETWEEN 1 AND 524288",
            name="ck_member_avatars_content_size",
        ),
        sa.CheckConstraint("revision > 0", name="ck_member_avatars_revision"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("member_id"),
    )


def downgrade() -> None:
    """Drop member-owned avatars and restore Telegram-only fallback."""
    op.drop_table("member_avatars")
