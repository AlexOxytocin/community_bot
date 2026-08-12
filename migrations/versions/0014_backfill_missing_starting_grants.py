"""Backfill missing ten-credit starting grants for active members.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import TYPE_CHECKING, Any

from alembic import op
from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Append exactly one starting grant for active members that missed it."""
    connection = op.get_bind()
    rows = connection.execute(
        text(
            """
            SELECT m.id
            FROM members m
            WHERE m.status = 'active'
              AND NOT EXISTS (
                  SELECT 1
                  FROM account_transactions existing
                  WHERE existing.member_id = m.id
                    AND existing.transaction_type = 'starting_grant'
              )
            ORDER BY m.id
            """
        )
    ).fetchall()
    if not rows:
        return

    transactions = [
        {
            "id": uuid.uuid4(),
            "member_id": row.id,
            "idempotency_key": f"starting_grant:{row.id}",
            "payload_hash": _starting_grant_payload_hash(row.id),
        }
        for row in rows
    ]
    connection.execute(
        text(
            """
            INSERT INTO account_transactions (
                id,
                member_id,
                credit_delta,
                experience_delta,
                transaction_type,
                idempotency_key,
                payload_hash
            )
            VALUES (
                :id,
                :member_id,
                10,
                0,
                'starting_grant',
                :idempotency_key,
                :payload_hash
            )
            """
        ),
        transactions,
    )
    connection.execute(
        text(
            """
            UPDATE members
            SET credit_balance_cached = credit_balance_cached + 10
            WHERE id = :member_id
            """
        ),
        [{"member_id": row.id} for row in rows],
    )


def downgrade() -> None:
    """Do not delete append-only ledger history during downgrade."""


def _starting_grant_payload_hash(member_id: uuid.UUID) -> str:
    projection = {
        "schema_version": 1,
        "transaction_type": "starting_grant",
        "member_id": str(member_id),
        "credit_delta": 10,
        "experience_delta": 0,
        "actor_member_id": None,
        "reason": None,
        "comment": None,
        "reversed_transaction_id": None,
    }
    return _sha256_json(projection)


def _sha256_json(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
