"""Create the immutable versioned task catalog and seed v1.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from jsonschema import Draft202012Validator
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
_SEED_SIZE = 8


def upgrade() -> None:
    """Create catalog tables, immutability barriers, and the v1 seed."""
    op.create_table(
        "task_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint("sort_order >= 0", name="ck_task_categories_sort_order"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("sort_order"),
    )
    op.create_table(
        "task_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("creator_instructions", sa.Text(), nullable=False),
        sa.Column("performer_instructions", sa.Text(), nullable=False),
        sa.Column("completion_criteria", sa.Text(), nullable=False),
        sa.Column("input_schema_json", postgresql.JSONB(), nullable=False),
        sa.Column("result_schema_json", postgresql.JSONB(), nullable=False),
        sa.Column("credit_reward", sa.Integer(), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("minimum_level", sa.Integer(), nullable=False),
        sa.Column("maximum_performers", sa.Integer(), server_default="1", nullable=False),
        sa.Column("moderation_required", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version > 0", name="ck_task_templates_version"),
        sa.CheckConstraint("credit_reward BETWEEN 1 AND 4", name="ck_task_templates_reward"),
        sa.CheckConstraint("estimated_minutes BETWEEN 1 AND 120", name="ck_task_templates_minutes"),
        sa.CheckConstraint(
            "format IN ('online', 'offline', 'any')", name="ck_task_templates_format"
        ),
        sa.CheckConstraint("minimum_level > 0", name="ck_task_templates_minimum_level"),
        sa.CheckConstraint(
            "maximum_performers BETWEEN 1 AND 10", name="ck_task_templates_performers"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(input_schema_json) = 'object'",
            name="ck_task_templates_input_schema_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result_schema_json) = 'object'",
            name="ck_task_templates_result_schema_object",
        ),
        sa.ForeignKeyConstraint(["category_id"], ["task_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version", name="uq_task_templates_code_version"),
    )
    op.create_index(
        "uq_task_templates_active_code",
        "task_templates",
        ["code"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "ix_task_templates_catalog",
        "task_templates",
        ["category_id", "is_active", "minimum_level", "code"],
    )
    _create_immutability_triggers()
    _seed_catalog()


def downgrade() -> None:
    """Remove the complete catalog schema and its seed."""
    op.drop_table("task_templates")
    op.drop_table("task_categories")
    op.execute("DROP FUNCTION IF EXISTS enforce_task_template_category_identity()")
    op.execute("DROP FUNCTION IF EXISTS protect_task_template_history()")
    op.execute("DROP FUNCTION IF EXISTS protect_task_category_identity()")


def _create_immutability_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_task_template_category_identity() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM task_templates
                WHERE code = NEW.code AND category_id IS DISTINCT FROM NEW.category_id
            ) THEN
                RAISE EXCEPTION 'task template category is immutable across versions';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_task_templates_category_identity
        BEFORE INSERT ON task_templates
        FOR EACH ROW EXECUTE FUNCTION enforce_task_template_category_identity()
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_task_category_identity() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'task category history is append-only';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.code IS DISTINCT FROM OLD.code
               OR NEW.name IS DISTINCT FROM OLD.name
               OR NEW.description IS DISTINCT FROM OLD.description
               OR NEW.icon IS DISTINCT FROM OLD.icon
               OR NEW.sort_order IS DISTINCT FROM OLD.sort_order THEN
                RAISE EXCEPTION 'task category identity is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_task_categories_immutable
        BEFORE UPDATE OR DELETE ON task_categories
        FOR EACH ROW EXECUTE FUNCTION protect_task_category_identity()
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_task_template_history() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'task template history is append-only';
            END IF;
            IF (to_jsonb(NEW) - 'is_active') IS DISTINCT FROM
               (to_jsonb(OLD) - 'is_active') THEN
                RAISE EXCEPTION 'task template version content is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_task_templates_immutable
        BEFORE UPDATE OR DELETE ON task_templates
        FOR EACH ROW EXECUTE FUNCTION protect_task_template_history()
        """
    )


def _seed_catalog() -> None:
    manifest_path = Path(__file__).parents[1] / "data" / "task_catalog_v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        message = "Unsupported task catalog seed schema version."
        raise ValueError(message)
    schemas = manifest["schemas"]
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    categories = manifest["categories"]
    templates = manifest["templates"]
    if len(categories) != _SEED_SIZE or len(templates) != _SEED_SIZE:
        message = "Task catalog seed v1 must contain eight categories and templates."
        raise ValueError(message)
    category_ids = {category["code"]: category["id"] for category in categories}
    category_table = sa.table(
        "task_categories",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("description", sa.Text()),
        sa.column("icon", sa.Text()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(category_table, [{**category, "is_active": True} for category in categories])
    template_table = sa.table(
        "task_templates",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("category_id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.Text()),
        sa.column("version", sa.Integer()),
        sa.column("name", sa.Text()),
        sa.column("description", sa.Text()),
        sa.column("creator_instructions", sa.Text()),
        sa.column("performer_instructions", sa.Text()),
        sa.column("completion_criteria", sa.Text()),
        sa.column("input_schema_json", postgresql.JSONB()),
        sa.column("result_schema_json", postgresql.JSONB()),
        sa.column("credit_reward", sa.Integer()),
        sa.column("estimated_minutes", sa.Integer()),
        sa.column("format", sa.Text()),
        sa.column("minimum_level", sa.Integer()),
        sa.column("maximum_performers", sa.Integer()),
        sa.column("moderation_required", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
    )
    rows = []
    for template in templates:
        row = dict(template)
        row["category_id"] = category_ids[row.pop("category_code")]
        row["version"] = 1
        row["is_active"] = True
        row["input_schema_json"] = schemas[row.pop("input_schema")]
        row["result_schema_json"] = schemas[row.pop("result_schema")]
        rows.append(row)
    op.bulk_insert(template_table, rows)
