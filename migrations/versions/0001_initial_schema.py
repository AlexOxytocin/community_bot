"""Create the empty infrastructure baseline.

Revision ID: 0001
Revises: None
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the empty baseline migration."""


def downgrade() -> None:
    """Revert the empty baseline migration."""
