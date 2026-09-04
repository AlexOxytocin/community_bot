"""Persist bot-first onboarding before community membership.

Revision ID: 0038
Revises: 0037
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remember only users who explicitly started the bot."""
    op.create_table(
        "bot_onboardings",
        sa.Column("telegram_user_id", sa.BigInteger(), primary_key=True),
        sa.Column("state", sa.Text(), nullable=False, server_default="waiting_for_chat"),
        sa.Column("telegram_username", sa.Text(), nullable=True),
        sa.Column("telegram_display_name", sa.Text(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "state IN ('waiting_for_chat','ready','completed')", name="ck_bot_onboarding_state"
        ),
    )


def downgrade() -> None:
    """Remove only resumable onboarding markers."""
    op.drop_table("bot_onboardings")
