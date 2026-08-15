# ruff: noqa: S608
"""Add free-form task creation.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow member-created tasks without immutable templates."""
    op.execute("DROP TRIGGER trg_tasks_immutable ON tasks")

    op.add_column(
        "task_categories",
        sa.Column("visibility", sa.Text(), server_default="public", nullable=False),
    )
    op.add_column(
        "task_categories",
        sa.Column("creation_mode", sa.Text(), server_default="template", nullable=False),
    )
    op.create_check_constraint(
        "ck_task_categories_visibility",
        "task_categories",
        "visibility IN ('public', 'admin_only')",
    )
    op.create_check_constraint(
        "ck_task_categories_creation_mode",
        "task_categories",
        "creation_mode IN ('template', 'freeform', 'both')",
    )

    op.add_column(
        "task_creation_drafts",
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("task_creation_drafts", sa.Column("task_kind", sa.Text(), nullable=True))
    op.add_column("task_creation_drafts", sa.Column("time_size", sa.Text(), nullable=True))
    op.add_column("task_creation_drafts", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("task_creation_drafts", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "task_creation_drafts",
        sa.Column("completion_criteria", sa.Text(), nullable=True),
    )
    op.add_column(
        "task_creation_drafts",
        sa.Column("credit_reward_per_performer", sa.Integer(), nullable=True),
    )
    op.add_column(
        "task_creation_drafts",
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_task_creation_drafts_category",
        "task_creation_drafts",
        "task_categories",
        ["category_id"],
        ["id"],
    )
    op.alter_column(
        "task_creation_drafts",
        "template_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.drop_constraint("ck_task_creation_drafts_step", "task_creation_drafts", type_="check")
    op.create_check_constraint(
        "ck_task_creation_drafts_step",
        "task_creation_drafts",
        "current_step IN ('task_kind','category','time_size','reward','title',"
        "'description','completion_criteria','input','deadline','format','materials',"
        "'slots','preview','published')",
    )
    op.drop_constraint("ck_task_creation_drafts_slots", "task_creation_drafts", type_="check")
    op.create_check_constraint(
        "ck_task_creation_drafts_slots",
        "task_creation_drafts",
        "performer_slots IS NULL OR performer_slots > 0",
    )
    op.create_check_constraint(
        "ck_task_creation_drafts_kind",
        "task_creation_drafts",
        "task_kind IS NULL OR task_kind IN ('solo', 'group')",
    )
    op.create_check_constraint(
        "ck_task_creation_drafts_time_size",
        "task_creation_drafts",
        "time_size IS NULL OR time_size IN ('xs', 's', 'm', 'l', 'xl')",
    )

    op.add_column("tasks", sa.Column("time_size", sa.Text(), nullable=True))
    op.add_column(
        "tasks",
        sa.Column("closed_for_new_performers_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column(
        "tasks",
        "template_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.alter_column("tasks", "template_version", existing_type=sa.Integer(), nullable=True)
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN ('published', 'settling', 'expired', 'partially_completed', "
        "'completed', 'cancelled', 'closed_for_new_performers')",
    )
    op.drop_constraint("ck_tasks_slots", "tasks", type_="check")
    op.create_check_constraint("ck_tasks_slots", "tasks", "performer_slots > 0")
    op.create_check_constraint(
        "ck_tasks_time_size",
        "tasks",
        "time_size IS NULL OR time_size IN ('xs', 's', 'm', 'l', 'xl')",
    )

    _seed_freeform_categories()
    _replace_task_history_trigger()


def downgrade() -> None:
    """Remove free-form task creation after verifying no free-form rows exist."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM tasks WHERE template_id IS NULL) OR
               EXISTS (SELECT 1 FROM task_creation_drafts WHERE template_id IS NULL) THEN
                RAISE EXCEPTION 'cannot downgrade while free-form tasks or drafts exist';
            END IF;
        END;
        $$;
        """
    )
    op.execute("DROP TRIGGER trg_tasks_immutable ON tasks")

    op.drop_constraint("ck_tasks_time_size", "tasks", type_="check")
    op.drop_constraint("ck_tasks_slots", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_slots",
        "tasks",
        "performer_slots BETWEEN 1 AND 10",
    )
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN ('published', 'settling', 'expired', 'partially_completed', "
        "'completed', 'cancelled')",
    )
    op.alter_column("tasks", "template_version", existing_type=sa.Integer(), nullable=False)
    op.alter_column(
        "tasks",
        "template_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.drop_column("tasks", "closed_for_new_performers_at")
    op.drop_column("tasks", "time_size")

    op.drop_constraint("ck_task_creation_drafts_time_size", "task_creation_drafts", type_="check")
    op.drop_constraint("ck_task_creation_drafts_kind", "task_creation_drafts", type_="check")
    op.drop_constraint("ck_task_creation_drafts_slots", "task_creation_drafts", type_="check")
    op.create_check_constraint(
        "ck_task_creation_drafts_slots",
        "task_creation_drafts",
        "performer_slots IS NULL OR performer_slots BETWEEN 1 AND 10",
    )
    op.drop_constraint("ck_task_creation_drafts_step", "task_creation_drafts", type_="check")
    op.create_check_constraint(
        "ck_task_creation_drafts_step",
        "task_creation_drafts",
        "current_step IN ('input','deadline','format','materials','slots','preview','published')",
    )
    op.alter_column(
        "task_creation_drafts",
        "template_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.drop_constraint(
        "fk_task_creation_drafts_category",
        "task_creation_drafts",
        type_="foreignkey",
    )
    op.drop_column("task_creation_drafts", "estimated_minutes")
    op.drop_column("task_creation_drafts", "credit_reward_per_performer")
    op.drop_column("task_creation_drafts", "completion_criteria")
    op.drop_column("task_creation_drafts", "description")
    op.drop_column("task_creation_drafts", "title")
    op.drop_column("task_creation_drafts", "time_size")
    op.drop_column("task_creation_drafts", "task_kind")
    op.drop_column("task_creation_drafts", "category_id")

    op.execute("DROP TRIGGER trg_task_categories_immutable ON task_categories")
    op.execute(
        """
        DELETE FROM task_categories
        WHERE code IN (
            'promotion', 'evaluation_testing', 'communication', 'learning_review',
            'practical_help', 'other', 'community_development'
        )
        """
    )
    op.drop_constraint("ck_task_categories_creation_mode", "task_categories", type_="check")
    op.drop_constraint("ck_task_categories_visibility", "task_categories", type_="check")
    op.drop_column("task_categories", "creation_mode")
    op.drop_column("task_categories", "visibility")
    op.execute(
        """
        CREATE TRIGGER trg_task_categories_immutable
        BEFORE UPDATE OR DELETE ON task_categories
        FOR EACH ROW EXECUTE FUNCTION protect_task_category_identity()
        """
    )

    _replace_task_history_trigger(allow_closed=False)


def _seed_freeform_categories() -> None:
    op.execute(
        """
        INSERT INTO task_categories (
            id, code, name, description, icon, sort_order, visibility, creation_mode, is_active
        )
        VALUES
            ('30000000-0000-4000-8000-000000000001', 'promotion',
             'Продвижение',
             'Репосты, отзывы, реакции и помощь распространению без накруток.',
             '📣', 110, 'public', 'freeform', true),
            ('30000000-0000-4000-8000-000000000002', 'evaluation_testing',
             'Оценка и тестирование',
             'Проверка продукта, сценария, текста, профиля или гипотезы.',
             '🔍', 120, 'public', 'freeform', true),
            ('30000000-0000-4000-8000-000000000003', 'communication',
             'Коммуникация',
             'Созвоны, интервью, сообщения, обратная связь и живые контакты.',
             '💬', 130, 'public', 'freeform', true),
            ('30000000-0000-4000-8000-000000000004', 'learning_review',
             'Обучение и разбор',
             'Объяснить, разобрать, проверить понимание или дать учебную обратную связь.',
             '🎓', 140, 'public', 'freeform', true),
            ('30000000-0000-4000-8000-000000000005', 'practical_help',
             'Практическая помощь',
             'Помочь руками в конкретном бытовом, операционном или рабочем действии.',
             '🤝', 150, 'public', 'freeform', true),
            ('30000000-0000-4000-8000-000000000006', 'other',
             'Другое',
             'Fallback, если задача не ложится в основные категории.',
             '🧩', 160, 'public', 'freeform', true),
            ('30000000-0000-4000-8000-000000000007', 'community_development',
             'Развитие комьюнити',
             'Административные задачи роста, правил, процессов и инфраструктуры сообщества.',
             '🌱', 170, 'admin_only', 'freeform', true)
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            icon = EXCLUDED.icon,
            sort_order = EXCLUDED.sort_order,
            visibility = EXCLUDED.visibility,
            creation_mode = EXCLUDED.creation_mode,
            is_active = EXCLUDED.is_active
        """
    )


def _replace_task_history_trigger(*, allow_closed: bool = True) -> None:
    allowed = "'status','cancelled_at','updated_at','reviewer_admin_id'"
    if allow_closed:
        allowed = (
            "'status','cancelled_at','updated_at','reviewer_admin_id',"
            "'closed_for_new_performers_at'"
        )
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
            IF (to_jsonb(NEW) - ARRAY[{allowed}]) IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY[{allowed}]) THEN
                RAISE EXCEPTION 'published task snapshot is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_tasks_immutable
        BEFORE UPDATE OR DELETE ON tasks
        FOR EACH ROW EXECUTE FUNCTION protect_task_snapshot()
        """
    )
