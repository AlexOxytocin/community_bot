"""Repair task aggregates left stale by moderation resolutions.

Revision ID: 0030
Revises: 0029
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Recompute tasks touched by an already resolved moderation case."""
    op.execute(
        """
        WITH latest_assignments AS (
            SELECT DISTINCT ON (assignment.task_id, assignment.slot_number)
                assignment.task_id,
                assignment.slot_number,
                assignment.status
            FROM assignments AS assignment
            ORDER BY
                assignment.task_id,
                assignment.slot_number,
                assignment.accepted_at DESC,
                assignment.id DESC
        ), affected AS (
            SELECT
                task.id,
                task.status AS current_status,
                task.performer_slots,
                task.deadline_at,
                count(latest.slot_number) AS latest_slots,
                count(*) FILTER (
                    WHERE latest.status IN ('approved', 'partially_approved')
                ) AS paid_slots,
                coalesce(bool_or(latest.status IN (
                    'accepted',
                    'submitted',
                    'rejected_pending_dispute',
                    'disputed',
                    'reviewer_required'
                )), false) AS has_active
            FROM tasks AS task
            LEFT JOIN latest_assignments AS latest ON latest.task_id = task.id
            WHERE task.status <> 'cancelled'
              AND EXISTS (
                  SELECT 1
                  FROM assignments AS case_assignment
                  JOIN moderation_cases AS moderation_case
                    ON moderation_case.assignment_id = case_assignment.id
                  WHERE case_assignment.task_id = task.id
                    AND moderation_case.status = 'resolved'
              )
            GROUP BY task.id
        ), derived AS (
            SELECT
                id,
                CASE
                    WHEN has_active OR (
                        current_status = 'published'
                        AND now() < deadline_at
                        AND latest_slots < performer_slots
                    ) THEN CASE
                        WHEN current_status = 'closed_for_new_performers'
                             AND now() < deadline_at
                        THEN 'closed_for_new_performers'
                        WHEN now() < deadline_at THEN 'published'
                        ELSE 'settling'
                    END
                    WHEN paid_slots = performer_slots THEN 'completed'
                    WHEN paid_slots > 0 THEN 'partially_completed'
                    ELSE 'expired'
                END AS status
            FROM affected
        )
        UPDATE tasks AS task
        SET status = derived.status,
            updated_at = now()
        FROM derived
        WHERE task.id = derived.id
          AND task.status IS DISTINCT FROM derived.status
        """
    )


def downgrade() -> None:
    """Keep the corrected aggregate state; previous stale values are not authoritative."""
