# ruff: noqa: S608
"""Allow safe edits of unclaimed member tasks.

Revision ID: 0040
Revises: 0039
"""

from __future__ import annotations

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep published snapshots immutable except for an unclaimed member task."""
    _replace_task_snapshot_guard(allow_unclaimed_member_edit=True)


def downgrade() -> None:
    """Restore complete published-snapshot immutability."""
    _replace_task_snapshot_guard(allow_unclaimed_member_edit=False)


def _replace_task_snapshot_guard(*, allow_unclaimed_member_edit: bool) -> None:
    edit_guard = ""
    if allow_unclaimed_member_edit:
        edit_guard = """
            IF OLD.origin = 'member'
               AND OLD.template_id IS NULL
               AND OLD.status = 'published'
               AND NOT EXISTS (
                   SELECT 1 FROM assignments WHERE task_id = OLD.id
               )
               AND (to_jsonb(NEW) - ARRAY[
                   'category_id','time_size','title','description',
                   'completion_criteria','materials_json','input_payload_json',
                   'credit_reward_per_performer','performer_slots',
                   'reserved_credit_total','estimated_minutes','format','city',
                   'deadline_at','safety_snapshot_json','updated_at'
               ]) IS NOT DISTINCT FROM
               (to_jsonb(OLD) - ARRAY[
                   'category_id','time_size','title','description',
                   'completion_criteria','materials_json','input_payload_json',
                   'credit_reward_per_performer','performer_slots',
                   'reserved_credit_total','estimated_minutes','format','city',
                   'deadline_at','safety_snapshot_json','updated_at'
               ]) THEN
                RETURN NEW;
            END IF;
        """
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION protect_task_snapshot() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'published task history is append-only';
            END IF;
            IF NEW.reviewer_admin_id IS DISTINCT FROM OLD.reviewer_admin_id THEN
                IF NEW.origin <> 'community' OR NEW.reviewer_admin_id IS NULL
                   OR NEW.reviewer_admin_id = NEW.created_by_admin_id
                   OR NOT EXISTS (
                       SELECT 1 FROM members
                       WHERE id = NEW.reviewer_admin_id
                         AND role = 'administrator' AND status = 'active'
                   ) OR EXISTS (
                       SELECT 1 FROM assignments
                       WHERE task_id = NEW.id AND performer_id = NEW.reviewer_admin_id
                   ) THEN
                    RAISE EXCEPTION 'community task reviewer is invalid';
                END IF;
            END IF;
            {edit_guard}
            IF (to_jsonb(NEW) - ARRAY[
                'status','cancelled_at','updated_at','reviewer_admin_id',
                'closed_for_new_performers_at'
            ]) IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY[
                   'status','cancelled_at','updated_at','reviewer_admin_id',
                   'closed_for_new_performers_at'
               ]) THEN
                RAISE EXCEPTION 'published task snapshot is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
