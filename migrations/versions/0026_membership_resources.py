"""Add Telegram membership resources to personal invitations.

Revision ID: 0026
Revises: 0025
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "membership_resources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_username", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("join_url", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_member_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_member_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_chat_id"),
    )
    op.create_table(
        "invitation_membership_resources",
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["membership_resources.id"]),
        sa.PrimaryKeyConstraint("invitation_id", "resource_id"),
    )


def downgrade() -> None:
    op.drop_table("invitation_membership_resources")
    op.drop_table("membership_resources")
