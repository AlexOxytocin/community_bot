"""Add isolated live test runs.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create test-run scopes and attach task data to them."""
    op.create_table(
        "test_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marker", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("started_by_member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'failed')", name="ck_test_runs_status"
        ),
        sa.CheckConstraint("marker LIKE 'TEST-%'", name="ck_test_runs_marker"),
        sa.ForeignKeyConstraint(["started_by_member_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("marker"),
    )
    op.create_table(
        "test_run_participants",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["test_runs.id"]),
        sa.PrimaryKeyConstraint("run_id", "member_id"),
    )
    op.create_index(
        "uq_test_run_participants_active_member",
        "test_run_participants",
        ["member_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.add_column(
        "task_creation_drafts",
        sa.Column("test_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_task_creation_drafts_test_run",
        "task_creation_drafts",
        "test_runs",
        ["test_run_id"],
        ["id"],
    )
    op.execute("DROP TRIGGER trg_tasks_immutable ON tasks")
    op.add_column(
        "tasks",
        sa.Column("test_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key("fk_tasks_test_run", "tasks", "test_runs", ["test_run_id"], ["id"])
    op.create_index("ix_tasks_test_run_id", "tasks", ["test_run_id"])
    op.execute(
        """
        CREATE TRIGGER trg_tasks_immutable
        BEFORE UPDATE OR DELETE ON tasks
        FOR EACH ROW EXECUTE FUNCTION protect_task_snapshot()
        """
    )


def downgrade() -> None:
    """Remove test-run scoping."""
    op.execute("DROP TRIGGER trg_tasks_immutable ON tasks")
    op.drop_index("ix_tasks_test_run_id", table_name="tasks")
    op.drop_constraint("fk_tasks_test_run", "tasks", type_="foreignkey")
    op.drop_column("tasks", "test_run_id")
    op.execute(
        """
        CREATE TRIGGER trg_tasks_immutable
        BEFORE UPDATE OR DELETE ON tasks
        FOR EACH ROW EXECUTE FUNCTION protect_task_snapshot()
        """
    )
    op.drop_constraint(
        "fk_task_creation_drafts_test_run", "task_creation_drafts", type_="foreignkey"
    )
    op.drop_column("task_creation_drafts", "test_run_id")
    op.drop_index("uq_test_run_participants_active_member", table_name="test_run_participants")
    op.drop_table("test_run_participants")
    op.drop_table("test_runs")
