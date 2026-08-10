"""Create invitations, registration state, and editable profile fields.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the persistent invitation, registration, and profile schema."""
    op.add_column(
        "members",
        sa.Column(
            "help_categories_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "members",
        sa.Column(
            "skill_tags_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("created_by_member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("intended_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("uses_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("max_uses > 0", name="ck_invitations_max_uses"),
        sa.CheckConstraint(
            "uses_count >= 0 AND uses_count <= max_uses",
            name="ck_invitations_uses_count",
        ),
        sa.ForeignKeyConstraint(["created_by_member_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_invitations_expires_at", "invitations", ["expires_at"])
    op.create_table(
        "invitation_redemptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "redeemed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"]),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invitation_id", "member_id", name="uq_invitation_redemption_pair"),
        sa.UniqueConstraint("member_id"),
    )
    op.create_table(
        "registration_applications",
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_member_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'rejected')",
            name="ck_registration_applications_status",
        ),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_member_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("member_id"),
    )
    op.create_index(
        "ix_registration_applications_status_submitted",
        "registration_applications",
        ["status", "submitted_at"],
    )
    op.create_table(
        "conversation_states",
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flow_type", sa.Text(), nullable=False),
        sa.Column("current_step", sa.Text(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("member_id"),
    )


def downgrade() -> None:
    """Remove registration data and editable profile additions."""
    op.drop_table("conversation_states")
    op.drop_index(
        "ix_registration_applications_status_submitted",
        table_name="registration_applications",
    )
    op.drop_table("registration_applications")
    op.drop_table("invitation_redemptions")
    op.drop_index("ix_invitations_expires_at", table_name="invitations")
    op.drop_table("invitations")
    op.drop_column("members", "skill_tags_json")
    op.drop_column("members", "help_categories_json")
