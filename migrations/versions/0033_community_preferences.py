"""Community subscriptions and runtime registration policy.

Revision ID: 0033
Revises: 0032
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep existing admission closed and existing task notifications enabled."""
    op.create_table(
        "community_registration_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.Text(), nullable=False, server_default="standard"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("id = 1", name="ck_registration_policy_singleton"),
        sa.CheckConstraint("mode IN ('standard','simplified')", name="ck_registration_policy_mode"),
        sa.CheckConstraint("revision >= 0", name="ck_registration_policy_revision"),
    )
    op.execute("INSERT INTO community_registration_policy (id) VALUES (1)")
    op.create_table(
        "member_notification_preferences",
        sa.Column("member_id", sa.Uuid(), sa.ForeignKey("members.id"), primary_key=True),
        sa.Column("tasks", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("nomad", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tasks_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nomad_since", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("revision >= 0", name="ck_notification_preferences_revision"),
        sa.CheckConstraint(
            "NOT nomad OR nomad_since IS NOT NULL", name="ck_nomad_subscription_since"
        ),
    )


def downgrade() -> None:
    """Remove preferences only; preserve accounts, ledger and audit history."""
    op.drop_table("member_notification_preferences")
    op.drop_table("community_registration_policy")
