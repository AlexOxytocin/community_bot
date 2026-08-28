"""Add individual administrator rights and appointment provenance.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSIONS = (
    "permissions_json <@ "
    '\'["karma_review","member_read","interaction_review",'
    '"member_invitation","member_blocking","administrator_management",'
    '"superadministrator"]\'::jsonb'
)
_LEGACY_PERMISSIONS = (
    "permissions_json <@ "
    '\'["karma_review","member_read","interaction_review",'
    '"superadministrator"]\'::jsonb'
)


def upgrade() -> None:
    """Persist appointment provenance and preserve existing administrator abilities."""
    op.drop_constraint("ck_members_permissions", "members", type_="check")
    op.create_check_constraint(
        "ck_members_permissions",
        "members",
        f"jsonb_typeof(permissions_json) = 'array' AND {_PERMISSIONS}",
    )
    op.add_column(
        "members",
        sa.Column(
            "administrator_appointed_by_member_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "members",
        sa.Column("administrator_appointed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_members_administrator_appointed_by",
        "members",
        "members",
        ["administrator_appointed_by_member_id"],
        ["id"],
    )
    op.execute(
        """
        UPDATE members
        SET permissions_json = permissions_json
            || '["member_invitation","member_blocking"]'::jsonb
        WHERE role = 'administrator'
          AND status = 'active'
          AND NOT permissions_json @> '["superadministrator"]'::jsonb
        """
    )
    op.execute(
        """
        UPDATE members AS administrator
        SET administrator_appointed_by_member_id = owner.id,
            administrator_appointed_at = administrator.created_at
        FROM members AS owner
        WHERE administrator.role = 'administrator'
          AND NOT administrator.permissions_json @> '["superadministrator"]'::jsonb
          AND owner.role = 'administrator'
          AND owner.permissions_json @> '["superadministrator"]'::jsonb
        """
    )


def downgrade() -> None:
    """Remove appointment provenance and the three newly persisted rights."""
    op.execute(
        "UPDATE members SET permissions_json = permissions_json "
        "- 'member_invitation' - 'member_blocking' - 'administrator_management'"
    )
    op.drop_constraint("fk_members_administrator_appointed_by", "members", type_="foreignkey")
    op.drop_column("members", "administrator_appointed_at")
    op.drop_column("members", "administrator_appointed_by_member_id")
    op.drop_constraint("ck_members_permissions", "members", type_="check")
    op.create_check_constraint(
        "ck_members_permissions",
        "members",
        f"jsonb_typeof(permissions_json) = 'array' AND {_LEGACY_PERMISSIONS}",
    )
