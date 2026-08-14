"""Add superadministrator and community publication approval.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADMIN_PERMISSIONS = (
    '\'["karma_review","member_read","interaction_review","superadministrator"]\'::jsonb'
)
_LEGACY_ADMIN_PERMISSIONS = '\'["karma_review","member_read","interaction_review"]\'::jsonb'


def upgrade() -> None:
    """Persist the owner permission and require confirmation before community release."""
    op.drop_constraint("ck_members_permissions", "members", type_="check")
    op.create_check_constraint(
        "ck_members_permissions",
        "members",
        f"jsonb_typeof(permissions_json) = 'array' AND permissions_json <@ {_ADMIN_PERMISSIONS}",
    )
    op.execute(
        """
        UPDATE members
        SET permissions_json = permissions_json || '["superadministrator"]'::jsonb
        WHERE role = 'administrator'
          AND status = 'active'
          AND NOT permissions_json @> '["superadministrator"]'::jsonb
          AND (
              SELECT count(*)
              FROM members
              WHERE role = 'administrator'
                AND status = 'active'
          ) = 1
        """
    )

    op.add_column(
        "task_creation_drafts",
        sa.Column("community_approval_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "task_creation_drafts",
        sa.Column(
            "community_approved_by_admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "task_creation_drafts",
        sa.Column("community_approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_task_creation_drafts_community_approved_by_admin",
        "task_creation_drafts",
        "members",
        ["community_approved_by_admin_id"],
        ["id"],
    )

    op.execute("DROP TRIGGER trg_tasks_immutable ON tasks")
    op.add_column(
        "tasks",
        sa.Column(
            "community_approved_by_admin_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_tasks_community_approved_by_admin",
        "tasks",
        "members",
        ["community_approved_by_admin_id"],
        ["id"],
    )
    op.execute(
        """
        UPDATE tasks
        SET community_approved_by_admin_id = created_by_admin_id
        WHERE origin = 'community'
          AND created_by_admin_id IS NOT NULL
          AND community_approved_by_admin_id IS NULL
        """
    )
    op.drop_constraint("ck_tasks_community_provenance", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_community_provenance",
        "tasks",
        "(origin = 'member' AND created_by_admin_id IS NULL "
        "AND reviewer_admin_id IS NULL AND community_approved_by_admin_id IS NULL) "
        "OR (origin = 'community' AND ((created_by_admin_id IS NULL "
        "AND reviewer_admin_id IS NULL AND community_approved_by_admin_id IS NULL) "
        "OR (created_by_admin_id IS NOT NULL AND reviewer_admin_id IS NOT NULL "
        "AND community_approved_by_admin_id IS NOT NULL "
        "AND created_by_admin_id <> reviewer_admin_id)))",
    )
    op.execute(
        """
        CREATE TRIGGER trg_tasks_immutable
        BEFORE UPDATE OR DELETE ON tasks
        FOR EACH ROW EXECUTE FUNCTION protect_task_snapshot()
        """
    )


def downgrade() -> None:
    """Remove the approval fields and owner permission without reactivating privileges."""
    op.execute("DROP TRIGGER trg_tasks_immutable ON tasks")
    op.drop_constraint("ck_tasks_community_provenance", "tasks", type_="check")
    op.drop_constraint("fk_tasks_community_approved_by_admin", "tasks", type_="foreignkey")
    op.drop_column("tasks", "community_approved_by_admin_id")
    op.create_check_constraint(
        "ck_tasks_community_provenance",
        "tasks",
        "(origin = 'member' AND created_by_admin_id IS NULL AND reviewer_admin_id IS NULL) "
        "OR (origin = 'community' AND ((created_by_admin_id IS NULL "
        "AND reviewer_admin_id IS NULL) OR (created_by_admin_id IS NOT NULL "
        "AND reviewer_admin_id IS NOT NULL AND created_by_admin_id <> reviewer_admin_id)))",
    )
    op.execute(
        """
        CREATE TRIGGER trg_tasks_immutable
        BEFORE UPDATE OR DELETE ON tasks
        FOR EACH ROW EXECUTE FUNCTION protect_task_snapshot()
        """
    )

    op.drop_constraint(
        "fk_task_creation_drafts_community_approved_by_admin",
        "task_creation_drafts",
        type_="foreignkey",
    )
    op.drop_column("task_creation_drafts", "community_approved_at")
    op.drop_column("task_creation_drafts", "community_approved_by_admin_id")
    op.drop_column("task_creation_drafts", "community_approval_requested_at")

    op.drop_constraint("ck_members_permissions", "members", type_="check")
    op.execute("UPDATE members SET permissions_json = permissions_json - 'superadministrator'")
    op.create_check_constraint(
        "ck_members_permissions",
        "members",
        "jsonb_typeof(permissions_json) = 'array' AND "
        f"permissions_json <@ {_LEGACY_ADMIN_PERMISSIONS}",
    )
