"""Allow explicitly unpaid member tasks to keep an auditable zero-credit ledger trail.

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ZERO_REWARD_CONSTRAINT = """(transaction_type = 'starting_grant' AND credit_delta IN (5, 10)
AND experience_delta = 0) OR (transaction_type = 'task_reward_reserved' AND credit_delta <= 0
AND experience_delta = 0) OR (transaction_type IN ('task_reward_earned', 'partial_task_reward',
'community_task_reward') AND credit_delta >= 0 AND experience_delta = credit_delta) OR
(transaction_type = 'task_reward_refunded' AND credit_delta >= 0 AND experience_delta = 0) OR
(transaction_type = 'penalty' AND credit_delta < 0 AND experience_delta = 0) OR
(transaction_type = 'admin_adjustment' AND (credit_delta <> 0 OR experience_delta <> 0)) OR
(transaction_type IN ('fraud_reversal', 'resolution_reversal')
AND (credit_delta <> 0 OR experience_delta <> 0))"""

_POSITIVE_REWARD_CONSTRAINT = _ZERO_REWARD_CONSTRAINT.replace(" <= 0", " < 0").replace(
    " >= 0", " > 0"
)


def upgrade() -> None:
    """Permit a deliberate zero reward and normalize older city display labels."""
    op.drop_constraint("ck_tasks_reward", "tasks", type_="check")
    op.create_check_constraint("ck_tasks_reward", "tasks", "credit_reward_per_performer >= 0")
    op.drop_constraint("ck_account_transactions_deltas", "account_transactions", type_="check")
    op.create_check_constraint(
        "ck_account_transactions_deltas", "account_transactions", _ZERO_REWARD_CONSTRAINT
    )
    # City picker labels used an em dash and a middle dot before this release.  Keep
    # stored profile and task values aligned with the picker, so an existing offline
    # task remains discoverable through the updated city filter.
    op.execute("UPDATE members SET city = replace(replace(city, ' — ', ', '), ' · ', ', ')")
    op.execute("UPDATE tasks SET city = replace(replace(city, ' — ', ', '), ' · ', ', ')")


def downgrade() -> None:
    """Restore the former positive-only reward ledger constraint."""
    op.drop_constraint("ck_tasks_reward", "tasks", type_="check")
    op.create_check_constraint("ck_tasks_reward", "tasks", "credit_reward_per_performer > 0")
    op.drop_constraint("ck_account_transactions_deltas", "account_transactions", type_="check")
    op.create_check_constraint(
        "ck_account_transactions_deltas", "account_transactions", _POSITIVE_REWARD_CONSTRAINT
    )
