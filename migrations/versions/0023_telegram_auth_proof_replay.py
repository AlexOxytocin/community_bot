"""Reject replayed Telegram Mini App authentication proofs.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store only digests of short-lived consumed proofs."""
    op.create_table(
        "telegram_auth_proofs",
        sa.Column("proof_digest", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "consumed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "octet_length(proof_digest) = 32", name="ck_telegram_auth_proofs_digest"
        ),
        sa.PrimaryKeyConstraint("proof_digest"),
    )


def downgrade() -> None:
    """Remove the consumed-proof receipt table."""
    op.drop_table("telegram_auth_proofs")
