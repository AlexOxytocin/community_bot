"""Add durable notification delivery and process heartbeats.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()


def upgrade() -> None:
    """Create the PostgreSQL outbox delivery boundary."""
    op.add_column(
        "outbox_events",
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
    )
    op.add_column(
        "outbox_events",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "outbox_events",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column("outbox_events", sa.Column("lease_token", UUID))
    op.add_column("outbox_events", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column("outbox_events", sa.Column("last_error_code", sa.Text()))
    op.execute("UPDATE outbox_events SET status = 'materialized' WHERE published_at IS NOT NULL")
    op.create_check_constraint(
        "ck_outbox_status",
        "outbox_events",
        "status IN ('pending','processing','materialized','failed')",
    )
    op.create_check_constraint("ck_outbox_attempt_count", "outbox_events", "attempt_count >= 0")
    op.create_check_constraint(
        "ck_outbox_lease_state",
        "outbox_events",
        "(status = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
        "OR (status <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_outbox_materialized_at",
        "outbox_events",
        "(status = 'materialized' AND published_at IS NOT NULL) OR status <> 'materialized'",
    )
    op.create_check_constraint(
        "ck_outbox_failed_error",
        "outbox_events",
        "(status = 'failed' AND last_error_code IS NOT NULL) OR status <> 'failed'",
    )
    op.create_index(
        "ix_outbox_due",
        "outbox_events",
        ["status", "next_attempt_at", "created_at"],
    )

    op.create_table(
        "notifications",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("member_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("notification_type", sa.Text(), nullable=False),
        sa.Column("payload_json", JSONB, nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_token", UUID),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.Text()),
        sa.Column("deduplication_key", sa.Text(), unique=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('pending','processing','sent','failed')",
            name="ck_notifications_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_notifications_attempt_count"),
        sa.CheckConstraint(
            "(status = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_notifications_lease_state",
        ),
        sa.CheckConstraint(
            "(status = 'sent' AND sent_at IS NOT NULL) OR status <> 'sent'",
            name="ck_notifications_sent_at",
        ),
        sa.CheckConstraint(
            "(status = 'failed' AND last_error_code IS NOT NULL) OR status <> 'failed'",
            name="ck_notifications_failed_error",
        ),
    )
    op.create_index(
        "ix_notifications_due",
        "notifications",
        ["status", "next_attempt_at", "scheduled_at"],
    )
    op.create_table(
        "process_heartbeats",
        sa.Column("process_name", sa.Text(), primary_key=True),
        sa.Column("release", sa.Text(), nullable=False),
        sa.Column("migration_revision", sa.Text(), nullable=False),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    """Remove notification delivery state."""
    op.drop_table("process_heartbeats")
    op.drop_index("ix_notifications_due", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_outbox_due", table_name="outbox_events")
    for constraint in (
        "ck_outbox_failed_error",
        "ck_outbox_materialized_at",
        "ck_outbox_lease_state",
        "ck_outbox_attempt_count",
        "ck_outbox_status",
    ):
        op.drop_constraint(constraint, "outbox_events", type_="check")
    for column in (
        "last_error_code",
        "lease_expires_at",
        "lease_token",
        "next_attempt_at",
        "attempt_count",
        "status",
    ):
        op.drop_column("outbox_events", column)
