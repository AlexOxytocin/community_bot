"""Support permission-gated free-form community tasks.

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSIONS = (
    "permissions_json <@ "
    '\'["karma_review","member_read","interaction_review",'
    '"member_invitation","member_blocking","administrator_management",'
    '"community_task_create","community_task_review","superadministrator"]\'::jsonb'
)
_PREVIOUS_PERMISSIONS = (
    "permissions_json <@ "
    '\'["karma_review","member_read","interaction_review",'
    '"member_invitation","member_blocking","administrator_management",'
    '"superadministrator"]\'::jsonb'
)


def upgrade() -> None:
    """Allow audited free-form community publication without a fixed reviewer."""
    op.drop_constraint("ck_members_permissions", "members", type_="check")
    op.create_check_constraint(
        "ck_members_permissions",
        "members",
        f"jsonb_typeof(permissions_json) = 'array' AND {_PERMISSIONS}",
    )
    op.drop_constraint("ck_tasks_community_provenance", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_community_provenance",
        "tasks",
        "(origin = 'member' AND created_by_admin_id IS NULL "
        "AND reviewer_admin_id IS NULL AND community_approved_by_admin_id IS NULL) OR "
        "(origin = 'community' AND "
        "((created_by_admin_id IS NULL AND reviewer_admin_id IS NULL "
        "AND community_approved_by_admin_id IS NULL) OR "
        "(template_id IS NULL AND created_by_admin_id IS NOT NULL "
        "AND reviewer_admin_id IS NULL "
        "AND community_approved_by_admin_id = created_by_admin_id) OR "
        "(created_by_admin_id IS NOT NULL AND reviewer_admin_id IS NOT NULL "
        "AND community_approved_by_admin_id IS NOT NULL "
        "AND created_by_admin_id <> reviewer_admin_id)))",
    )
    op.create_check_constraint(
        "ck_tasks_freeform_community_reward",
        "tasks",
        "origin <> 'community' OR template_id IS NOT NULL OR credit_reward_per_performer <= 10",
    )


def downgrade() -> None:
    """Remove new writes while retaining already published community tasks."""
    op.execute(
        "UPDATE members SET permissions_json = permissions_json "
        "- 'community_task_create' - 'community_task_review'"
    )
    op.drop_constraint("ck_members_permissions", "members", type_="check")
    op.create_check_constraint(
        "ck_members_permissions",
        "members",
        f"jsonb_typeof(permissions_json) = 'array' AND {_PREVIOUS_PERMISSIONS}",
    )
    op.drop_constraint("ck_tasks_freeform_community_reward", "tasks", type_="check")
    op.drop_constraint("ck_tasks_community_provenance", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_community_provenance",
        "tasks",
        "(origin = 'member' AND created_by_admin_id IS NULL "
        "AND reviewer_admin_id IS NULL AND community_approved_by_admin_id IS NULL) OR "
        "(origin = 'community' AND "
        "((created_by_admin_id IS NULL AND reviewer_admin_id IS NULL "
        "AND community_approved_by_admin_id IS NULL) OR "
        "(template_id IS NULL AND created_by_admin_id IS NOT NULL "
        "AND reviewer_admin_id IS NULL "
        "AND community_approved_by_admin_id = created_by_admin_id) OR "
        "(created_by_admin_id IS NOT NULL AND reviewer_admin_id IS NOT NULL "
        "AND community_approved_by_admin_id IS NOT NULL "
        "AND created_by_admin_id <> reviewer_admin_id)))",
    )
