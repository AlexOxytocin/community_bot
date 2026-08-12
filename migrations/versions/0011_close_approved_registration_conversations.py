"""Close stale conversations left by approved registrations.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove only terminal registration conversations already approved."""
    op.execute(
        """
        DELETE FROM conversation_states AS state
        USING registration_applications AS application
        WHERE application.member_id = state.member_id
          AND application.status = 'approved'
          AND state.flow_type IN ('registration', 'registration_paused')
        """
    )


def downgrade() -> None:
    """Keep the safe terminal-state cleanup when rolling code back."""
