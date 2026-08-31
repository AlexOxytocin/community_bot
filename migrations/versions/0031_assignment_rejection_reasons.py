"""Persist structured assignment rejection reasons.

Revision ID: 0031
Revises: 0030
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable fields so historical rejections remain truthful."""
    op.add_column("assignments", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("assignments", sa.Column("rejection_comment", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_assignments_rejection_reason",
        "assignments",
        "rejection_reason IS NULL OR rejection_reason IN ("
        "'not_completed', 'requirements_not_met', 'insufficient_evidence', 'other'"
        ")",
    )


def downgrade() -> None:
    """Remove the optional rejection metadata."""
    op.drop_constraint("ck_assignments_rejection_reason", "assignments", type_="check")
    op.drop_column("assignments", "rejection_comment")
    op.drop_column("assignments", "rejection_reason")
