"""Add durable creator cancellation requests and performer responses.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_cancellation_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','completed','declined','obsolete')",
            name="ck_task_cancellation_requests_status",
        ),
        sa.ForeignKeyConstraint(["requested_by_member_id"], ["members.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_task_cancellation_requests_task_id",
        "task_cancellation_requests",
        ["task_id"],
    )
    op.create_index(
        "uq_task_cancellation_requests_pending",
        "task_cancellation_requests",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "task_cancellation_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("performer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','accepted','declined','obsolete')",
            name="ck_task_cancellation_responses_status",
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"]),
        sa.ForeignKeyConstraint(["performer_id"], ["members.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["task_cancellation_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id", "assignment_id", name="uq_task_cancellation_response_assignment"
        ),
    )
    op.create_index(
        "ix_task_cancellation_responses_request_id",
        "task_cancellation_responses",
        ["request_id"],
    )
    op.create_index(
        "ix_task_cancellation_responses_performer_id",
        "task_cancellation_responses",
        ["performer_id"],
    )


def downgrade() -> None:
    op.drop_table("task_cancellation_responses")
    op.drop_table("task_cancellation_requests")
