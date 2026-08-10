# ruff: noqa: E501
"""Create assignment lifecycle, results, disputes, and ledger correlation.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the complete task exchange persistence boundary."""
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN ('published','settling','expired','partially_completed','completed','cancelled')",
    )
    op.create_table(
        "assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("performer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slot_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("review_deadline_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.Column("reject_dispute_deadline_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("terminal_command_id", postgresql.UUID(as_uuid=True)),
        sa.Column("terminal_outcome", sa.Text()),
        sa.Column("cancellation_reason", sa.Text()),
        sa.CheckConstraint("slot_number > 0", name="ck_assignments_slot_positive"),
        sa.CheckConstraint(
            "status IN ('accepted','submitted','rejected_pending_dispute','disputed',"
            "'approved','partially_approved','rejected','cancelled','no_show','reviewer_required')",
            name="ck_assignments_status",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["performer_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "performer_id", name="uq_assignments_task_performer"),
        sa.UniqueConstraint("terminal_command_id"),
    )
    op.create_index(
        "uq_assignments_occupied_slot",
        "assignments",
        ["task_id", "slot_number"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('accepted','submitted','rejected_pending_dispute','disputed',"
            "'reviewer_required','approved','partially_approved','rejected','no_show')"
        ),
    )
    op.create_index("ix_assignments_performer_status", "assignments", ["performer_id", "status"])
    op.create_table(
        "assignment_result_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("submit_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "version", name="uq_assignment_result_version"),
        sa.UniqueConstraint("submit_command_id"),
    )
    op.create_table(
        "assignment_disputes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("performer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("open_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"]),
        sa.ForeignKeyConstraint(["performer_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id"),
        sa.UniqueConstraint("open_command_id"),
    )
    op.create_table(
        "assignment_submission_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("performer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submit_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", postgresql.JSONB()),
        sa.Column("submitted_result_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"]),
        sa.ForeignKeyConstraint(["performer_id"], ["members.id"]),
        sa.ForeignKeyConstraint(["submitted_result_id"], ["assignment_result_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submit_command_id"),
    )
    op.create_index(
        "ix_assignment_submission_drafts_assignment_id",
        "assignment_submission_drafts",
        ["assignment_id"],
    )
    op.create_table(
        "reliability_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor_member_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reason", sa.Text()),
        sa.Column("supersedes_event_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"]),
        sa.ForeignKeyConstraint(["actor_member_id"], ["members.id"]),
        sa.ForeignKeyConstraint(["supersedes_event_id"], ["reliability_events.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("account_transactions", sa.Column("task_id", postgresql.UUID(as_uuid=True)))
    op.add_column("account_transactions", sa.Column("assignment_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_account_transactions_task", "account_transactions", "tasks", ["task_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_account_transactions_assignment",
        "account_transactions",
        "assignments",
        ["assignment_id"],
        ["id"],
    )
    _create_immutable_trigger("assignment_result_versions")
    _create_immutable_trigger("assignment_disputes")
    _create_immutable_trigger("reliability_events")


def downgrade() -> None:
    """Remove assignment persistence and restore task-creation schema."""
    for table in ("reliability_events", "assignment_disputes", "assignment_result_versions"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS protect_assignment_history()")
    op.drop_constraint(
        "fk_account_transactions_assignment", "account_transactions", type_="foreignkey"
    )
    op.drop_constraint("fk_account_transactions_task", "account_transactions", type_="foreignkey")
    op.drop_column("account_transactions", "assignment_id")
    op.drop_column("account_transactions", "task_id")
    op.drop_table("reliability_events")
    # The branch migration may already have been exercised locally before the
    # durable Telegram draft was added to this still-unpublished revision.
    op.execute("DROP TABLE IF EXISTS assignment_submission_drafts")
    op.drop_table("assignment_disputes")
    op.drop_table("assignment_result_versions")
    op.drop_table("assignments")
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.create_check_constraint("ck_tasks_status", "tasks", "status IN ('published','cancelled')")


def _create_immutable_trigger(table: str) -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_assignment_history() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'assignment history is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION protect_assignment_history()"
    )
