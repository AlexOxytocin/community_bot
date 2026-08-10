"""Create persistent task drafts, published tasks, and transactional outbox.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the complete member task publication persistence boundary."""
    op.create_table(
        "task_creation_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("format", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("materials_json", postgresql.JSONB(), nullable=True),
        sa.Column("performer_slots", sa.Integer(), nullable=True),
        sa.Column("current_step", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("publish_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "current_step IN "
            "('input','deadline','format','materials','slots','preview','published')",
            name="ck_task_creation_drafts_step",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_task_creation_drafts_revision"),
        sa.CheckConstraint(
            "format IS NULL OR format IN ('online','offline')",
            name="ck_task_creation_drafts_format",
        ),
        sa.CheckConstraint(
            "performer_slots IS NULL OR performer_slots BETWEEN 1 AND 10",
            name="ck_task_creation_drafts_slots",
        ),
        sa.ForeignKeyConstraint(["creator_id"], ["members.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["task_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publish_command_id"),
    )
    op.create_index(
        "uq_task_creation_drafts_current_creator",
        "task_creation_drafts",
        ["creator_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("author_display_name", sa.Text(), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("completion_criteria", sa.Text(), nullable=False),
        sa.Column("materials_json", postgresql.JSONB(), nullable=False),
        sa.Column("input_payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("credit_reward_per_performer", sa.Integer(), nullable=False),
        sa.Column("performer_slots", sa.Integer(), nullable=False),
        sa.Column("reserved_credit_total", sa.BigInteger(), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("minimum_level", sa.Integer(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("safety_snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("publish_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("origin IN ('member','community')", name="ck_tasks_origin"),
        sa.CheckConstraint("status IN ('published','cancelled')", name="ck_tasks_status"),
        sa.CheckConstraint("credit_reward_per_performer > 0", name="ck_tasks_reward"),
        sa.CheckConstraint("performer_slots BETWEEN 1 AND 10", name="ck_tasks_slots"),
        sa.CheckConstraint("reserved_credit_total >= 0", name="ck_tasks_reserved_nonnegative"),
        sa.CheckConstraint("minimum_level > 0", name="ck_tasks_minimum_level"),
        sa.CheckConstraint("format IN ('online','offline')", name="ck_tasks_format"),
        sa.CheckConstraint("deadline_at > published_at", name="ck_tasks_future_deadline"),
        sa.CheckConstraint(
            "(origin='member' AND creator_id IS NOT NULL AND "
            "reserved_credit_total=credit_reward_per_performer*performer_slots) OR "
            "(origin='community' AND creator_id IS NULL AND reserved_credit_total=0)",
            name="ck_tasks_origin_reserve",
        ),
        sa.ForeignKeyConstraint(["template_id"], ["task_templates.id"]),
        sa.ForeignKeyConstraint(["creator_id"], ["members.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["task_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publish_command_id"),
    )
    op.create_index("ix_tasks_creator_created", "tasks", ["creator_id", "created_at", "id"])
    op.create_index("ix_tasks_status_deadline", "tasks", ["status", "deadline_at"])
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("business_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_key"),
    )
    _create_task_history_trigger()


def downgrade() -> None:
    """Remove task creation persistence while retaining the catalog."""
    op.drop_table("outbox_events")
    op.drop_table("tasks")
    op.drop_table("task_creation_drafts")
    op.execute("DROP FUNCTION IF EXISTS protect_task_snapshot()")


def _create_task_history_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION protect_task_snapshot() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'published task history is append-only';
            END IF;
            IF (to_jsonb(NEW) - ARRAY['status','cancelled_at','updated_at']) IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status','cancelled_at','updated_at']) THEN
                RAISE EXCEPTION 'published task snapshot is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_tasks_immutable
        BEFORE UPDATE OR DELETE ON tasks
        FOR EACH ROW EXECUTE FUNCTION protect_task_snapshot()
        """
    )
