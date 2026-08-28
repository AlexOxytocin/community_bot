"""Add the credit-only superadministrator grant transaction.

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

_OLD_TYPES = (
    "transaction_type IN ('starting_grant', 'task_reward_reserved', "
    "'task_reward_earned', 'task_reward_refunded', 'partial_task_reward', "
    "'community_task_reward', 'penalty', 'admin_adjustment', 'fraud_reversal', "
    "'resolution_reversal')"
)

_NEW_TYPES = _OLD_TYPES[:-1] + ", 'manual_credit_grant')"

_BASE_DELTAS = (
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

_NEW_DELTAS = (
    _BASE_DELTAS + " OR (transaction_type = 'manual_credit_grant' AND credit_delta > 0 "
    "AND experience_delta = 0)"
)


def upgrade() -> None:
    """Allow immutable positive credit-only manual grants."""
    op.drop_constraint("ck_account_transactions_type", "account_transactions", type_="check")
    op.drop_constraint("ck_account_transactions_deltas", "account_transactions", type_="check")
    op.create_check_constraint("ck_account_transactions_type", "account_transactions", _NEW_TYPES)
    op.create_check_constraint(
        "ck_account_transactions_deltas", "account_transactions", _NEW_DELTAS
    )


def downgrade() -> None:
    """Remove manual grants only when no such immutable history exists."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM account_transactions
                WHERE transaction_type = 'manual_credit_grant'
            ) THEN
                RAISE EXCEPTION
                    'cannot remove manual credit grants while their history exists';
            END IF;
        END $$;
        """
    )
    op.drop_constraint("ck_account_transactions_type", "account_transactions", type_="check")
    op.drop_constraint("ck_account_transactions_deltas", "account_transactions", type_="check")
    op.create_check_constraint("ck_account_transactions_type", "account_transactions", _OLD_TYPES)
    op.create_check_constraint(
        "ck_account_transactions_deltas", "account_transactions", _BASE_DELTAS
    )
