"""Allow ten-credit starting grants while preserving legacy rows.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TEN_CREDIT_DELTA_CONSTRAINT = (
    "(transaction_type = 'starting_grant' AND credit_delta IN (5, 10) "
    "AND experience_delta = 0) OR "
    "(transaction_type = 'task_reward_reserved' AND credit_delta < 0 "
    "AND experience_delta = 0) OR "
    "(transaction_type IN ('task_reward_earned', 'partial_task_reward', "
    "'community_task_reward') AND credit_delta > 0 "
    "AND experience_delta = credit_delta) OR "
    "(transaction_type = 'task_reward_refunded' AND credit_delta > 0 "
    "AND experience_delta = 0) OR "
    "(transaction_type = 'penalty' AND credit_delta < 0 "
    "AND experience_delta = 0) OR "
    "(transaction_type = 'admin_adjustment' "
    "AND (credit_delta <> 0 OR experience_delta <> 0)) OR "
    "(transaction_type IN ('fraud_reversal', 'resolution_reversal') "
    "AND (credit_delta <> 0 OR experience_delta <> 0))"
)

_FIVE_CREDIT_DELTA_CONSTRAINT = (
    "(transaction_type = 'starting_grant' AND credit_delta = 5 "
    "AND experience_delta = 0) OR "
    "(transaction_type = 'task_reward_reserved' AND credit_delta < 0 "
    "AND experience_delta = 0) OR "
    "(transaction_type IN ('task_reward_earned', 'partial_task_reward', "
    "'community_task_reward') AND credit_delta > 0 "
    "AND experience_delta = credit_delta) OR "
    "(transaction_type = 'task_reward_refunded' AND credit_delta > 0 "
    "AND experience_delta = 0) OR "
    "(transaction_type = 'penalty' AND credit_delta < 0 "
    "AND experience_delta = 0) OR "
    "(transaction_type = 'admin_adjustment' "
    "AND (credit_delta <> 0 OR experience_delta <> 0)) OR "
    "(transaction_type IN ('fraud_reversal', 'resolution_reversal') "
    "AND (credit_delta <> 0 OR experience_delta <> 0))"
)


def upgrade() -> None:
    """Accept the new grant amount without invalidating historical five-credit grants."""
    op.drop_constraint("ck_account_transactions_deltas", "account_transactions", type_="check")
    op.create_check_constraint(
        "ck_account_transactions_deltas",
        "account_transactions",
        _TEN_CREDIT_DELTA_CONSTRAINT,
    )


def downgrade() -> None:
    """Restore the old invariant only when no ten-credit grants have been persisted."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM account_transactions
                WHERE transaction_type = 'starting_grant'
                  AND credit_delta <> 5
            ) THEN
                RAISE EXCEPTION
                    'cannot restore five-credit starting grant constraint with non-legacy grants';
            END IF;
        END $$;
        """
    )
    op.drop_constraint("ck_account_transactions_deltas", "account_transactions", type_="check")
    op.create_check_constraint(
        "ck_account_transactions_deltas",
        "account_transactions",
        _FIVE_CREDIT_DELTA_CONSTRAINT,
    )
