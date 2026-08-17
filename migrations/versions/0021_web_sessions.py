"""Add short-lived Mini App web sessions.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the single digest-keyed session table."""
    op.create_table(
        "web_sessions",
        sa.Column("token_digest", sa.LargeBinary(), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("octet_length(token_digest) = 32", name="ck_web_sessions_digest"),
        sa.CheckConstraint("expires_at > created_at", name="ck_web_sessions_expiry"),
        sa.CheckConstraint(
            "authenticated_at <= expires_at", name="ck_web_sessions_authenticated_at"
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_web_sessions_revoked_at",
        ),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("token_digest"),
    )


def downgrade() -> None:
    """Remove only short-lived web sessions."""
    op.drop_table("web_sessions")
