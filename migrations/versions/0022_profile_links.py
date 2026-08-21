"""Add ordered public profile links.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a bounded JSON array to existing member rows."""
    op.add_column(
        "members",
        sa.Column(
            "profile_links_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_members_profile_links_array", "members", "jsonb_typeof(profile_links_json) = 'array'"
    )
    op.create_check_constraint(
        "ck_members_profile_links_limit", "members", "jsonb_array_length(profile_links_json) <= 5"
    )


def downgrade() -> None:
    """Remove only public profile links."""
    op.drop_constraint("ck_members_profile_links_limit", "members", type_="check")
    op.drop_constraint("ck_members_profile_links_array", "members", type_="check")
    op.drop_column("members", "profile_links_json")
