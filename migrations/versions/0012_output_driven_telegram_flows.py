"""Add community task provenance required by output-driven creation.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist community draft origin and independent administrator provenance."""
    op.execute("DROP TRIGGER trg_tasks_immutable ON tasks")
    op.add_column(
        "task_creation_drafts",
        sa.Column("origin", sa.Text(), nullable=False, server_default="member"),
    )
    op.add_column(
        "task_creation_drafts",
        sa.Column("reviewer_admin_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_task_creation_drafts_origin",
        "task_creation_drafts",
        "origin IN ('member', 'community')",
    )
    op.create_foreign_key(
        "fk_task_creation_drafts_reviewer_admin",
        "task_creation_drafts",
        "members",
        ["reviewer_admin_id"],
        ["id"],
    )
    op.add_column(
        "tasks", sa.Column("created_by_admin_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "tasks", sa.Column("reviewer_admin_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.execute(
        """
        UPDATE tasks
        SET created_by_admin_id = NULLIF(
                safety_snapshot_json ->> '_community_created_by_admin_id', ''
            )::uuid,
            reviewer_admin_id = NULLIF(
                safety_snapshot_json ->> '_community_reviewer_admin_id', ''
            )::uuid,
            safety_snapshot_json = safety_snapshot_json
                - '_community_created_by_admin_id'
                - '_community_reviewer_admin_id'
        WHERE origin = 'community'
          AND safety_snapshot_json ? '_community_created_by_admin_id'
          AND safety_snapshot_json ? '_community_reviewer_admin_id'
        """
    )
    op.create_foreign_key(
        "fk_tasks_created_by_admin",
        "tasks",
        "members",
        ["created_by_admin_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_tasks_reviewer_admin",
        "tasks",
        "members",
        ["reviewer_admin_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_tasks_community_provenance",
        "tasks",
        "(origin = 'member' AND created_by_admin_id IS NULL AND reviewer_admin_id IS NULL) "
        "OR (origin = 'community' AND ((created_by_admin_id IS NULL AND reviewer_admin_id IS NULL) "
        "OR (created_by_admin_id IS NOT NULL AND reviewer_admin_id IS NOT NULL "
        "AND created_by_admin_id <> reviewer_admin_id)))",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_task_snapshot() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'published task history is append-only';
            END IF;
            IF NEW.reviewer_admin_id IS DISTINCT FROM OLD.reviewer_admin_id THEN
                IF NEW.origin <> 'community' OR NEW.reviewer_admin_id IS NULL
                   OR NEW.reviewer_admin_id = NEW.created_by_admin_id
                   OR NOT EXISTS (
                       SELECT 1 FROM members
                       WHERE id = NEW.reviewer_admin_id
                         AND role = 'administrator' AND status = 'active'
                   ) OR EXISTS (
                       SELECT 1 FROM assignments
                       WHERE task_id = NEW.id AND performer_id = NEW.reviewer_admin_id
                   ) THEN
                    RAISE EXCEPTION 'community task reviewer is invalid';
                END IF;
            END IF;
            IF (to_jsonb(NEW) - ARRAY[
                    'status','cancelled_at','updated_at','reviewer_admin_id'
                ]) IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY[
                    'status','cancelled_at','updated_at','reviewer_admin_id'
                ]) THEN
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


def downgrade() -> None:
    """Remove only the community creation provenance introduced here."""
    op.execute("DROP TRIGGER trg_tasks_immutable ON tasks")
    op.execute(
        """
        UPDATE tasks
        SET safety_snapshot_json = safety_snapshot_json || jsonb_build_object(
            '_community_created_by_admin_id', created_by_admin_id::text,
            '_community_reviewer_admin_id', reviewer_admin_id::text
        )
        WHERE origin = 'community'
          AND created_by_admin_id IS NOT NULL
          AND reviewer_admin_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_task_snapshot() RETURNS trigger AS $$
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
    op.drop_constraint("ck_tasks_community_provenance", "tasks", type_="check")
    op.drop_constraint("fk_tasks_reviewer_admin", "tasks", type_="foreignkey")
    op.drop_constraint("fk_tasks_created_by_admin", "tasks", type_="foreignkey")
    op.drop_column("tasks", "reviewer_admin_id")
    op.drop_column("tasks", "created_by_admin_id")
    op.drop_constraint(
        "fk_task_creation_drafts_reviewer_admin", "task_creation_drafts", type_="foreignkey"
    )
    op.drop_constraint("ck_task_creation_drafts_origin", "task_creation_drafts", type_="check")
    op.drop_column("task_creation_drafts", "reviewer_admin_id")
    op.drop_column("task_creation_drafts", "origin")
    op.execute(
        """
        CREATE TRIGGER trg_tasks_immutable
        BEFORE UPDATE OR DELETE ON tasks
        FOR EACH ROW EXECUTE FUNCTION protect_task_snapshot()
        """
    )
