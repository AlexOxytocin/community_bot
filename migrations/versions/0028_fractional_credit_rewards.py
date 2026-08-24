# ruff: noqa: E501, EM101, S608, TRY003
"""Store credits and experience as exact tenths instead of whole integers.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op
from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NUMERIC_COLUMNS = (
    ("members", "credit_balance_cached"),
    ("members", "experience_total_cached"),
    ("task_creation_drafts", "credit_reward_per_performer"),
    ("tasks", "credit_reward_per_performer"),
    ("tasks", "reserved_credit_total"),
    ("account_transactions", "credit_delta"),
    ("account_transactions", "experience_delta"),
)


def upgrade() -> None:
    """Make all ledger-affecting values exact decimal tenths."""
    for table, column in _NUMERIC_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE numeric(18, 1) "
            f"USING {column}::numeric(18, 1)"
        )
    _replace_reversal_trigger_types("numeric(18, 1)")


def downgrade() -> None:
    """Only permit a downgrade when no fractional history exists."""
    for table, column in _NUMERIC_COLUMNS:
        fractional = (
            op.get_bind()
            .execute(
                text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {column} <> trunc({column}))")
            )
            .scalar()
        )
        if fractional:
            raise RuntimeError("Cannot downgrade an economy database containing fractional values.")
    for table, column in reversed(_NUMERIC_COLUMNS):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE bigint USING {column}::bigint")
    _replace_reversal_trigger_types("bigint")


def _replace_reversal_trigger_types(amount_type: str) -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION validate_account_transaction_reversal() RETURNS trigger AS $$
        DECLARE
            source_member_id uuid;
            source_credit_delta {amount_type};
            source_experience_delta {amount_type};
            source_transaction_type text;
        BEGIN
            IF NEW.transaction_type NOT IN ('fraud_reversal', 'resolution_reversal') THEN
                IF NEW.reversed_transaction_id IS NOT NULL THEN
                    RAISE EXCEPTION 'only reversal transactions may reference a source transaction';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.reversed_transaction_id IS NULL THEN
                RAISE EXCEPTION 'reversal requires a source transaction';
            END IF;
            SELECT member_id, credit_delta, experience_delta, transaction_type
              INTO source_member_id, source_credit_delta, source_experience_delta, source_transaction_type
              FROM account_transactions WHERE id = NEW.reversed_transaction_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'reversal source transaction does not exist'; END IF;
            IF source_transaction_type IN ('fraud_reversal', 'resolution_reversal') THEN
                RAISE EXCEPTION 'a reversal cannot reverse another reversal';
            END IF;
            IF NEW.member_id <> source_member_id THEN
                RAISE EXCEPTION 'reversal member must match its source';
            END IF;
            IF NEW.credit_delta <> -source_credit_delta OR NEW.experience_delta <> -source_experience_delta THEN
                RAISE EXCEPTION 'reversal deltas must be exact source inverses';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
