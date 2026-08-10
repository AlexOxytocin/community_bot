"""PostgreSQL persistence for the immutable versioned task catalog."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import and_, or_, select, text, update

from community_bot.application.catalog import CatalogPage, CatalogTemplate
from community_bot.domain.catalog import CatalogCursor, TaskFormat
from community_bot.infrastructure.db.models import TaskCategoryModel, TaskTemplateModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from community_bot.application.catalog import CatalogQuery
    from community_bot.domain.catalog import TemplateDraft

_CATALOG_GATE = "task_catalog_mutation"


async def acquire_catalog_mutation_gate(session: AsyncSession) -> None:
    """Serialize every catalog mutation after the exact update gate."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:gate, 0))"),
        {"gate": _CATALOG_GATE},
    )


async def catalog_page(
    session: AsyncSession,
    *,
    query: CatalogQuery,
    level: int,
) -> CatalogPage:
    """Return one active level-aware keyset page."""
    statement = (
        select(TaskTemplateModel, TaskCategoryModel)
        .join(TaskCategoryModel, TaskCategoryModel.id == TaskTemplateModel.category_id)
        .where(TaskTemplateModel.is_active.is_(True))
        .where(TaskCategoryModel.is_active.is_(True))
        .where(TaskTemplateModel.minimum_level <= level)
    )
    if query.category_code is not None:
        statement = statement.where(TaskCategoryModel.code == query.category_code)
    if query.format is not None and query.format is not TaskFormat.ANY:
        statement = statement.where(
            TaskTemplateModel.format.in_((query.format.value, TaskFormat.ANY.value))
        )
    if query.cursor is not None:
        statement = statement.where(
            or_(
                TaskCategoryModel.sort_order > query.cursor.category_sort_order,
                and_(
                    TaskCategoryModel.sort_order == query.cursor.category_sort_order,
                    TaskTemplateModel.code > query.cursor.template_code,
                ),
            )
        )
    rows = (
        await session.execute(
            statement.order_by(TaskCategoryModel.sort_order, TaskTemplateModel.code).limit(
                query.limit + 1
            )
        )
    ).all()
    items = tuple(_snapshot(template, category) for template, category in rows[: query.limit])
    next_cursor = None
    if len(rows) > query.limit and items:
        last = items[-1]
        next_cursor = CatalogCursor(last.category_sort_order, last.code)
    return CatalogPage(items=items, next_cursor=next_cursor)


async def catalog_template(session: AsyncSession, template_id: uuid.UUID) -> CatalogTemplate | None:
    """Read one exact historical version regardless of active switches."""
    row = (
        await session.execute(
            select(TaskTemplateModel, TaskCategoryModel)
            .join(TaskCategoryModel, TaskCategoryModel.id == TaskTemplateModel.category_id)
            .where(TaskTemplateModel.id == template_id)
        )
    ).one_or_none()
    return None if row is None else _snapshot(row[0], row[1])


async def template_for_creation(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    level: int,
) -> CatalogTemplate | None:
    """Read one exact version only when it is currently publishable."""
    row = (
        await session.execute(
            select(TaskTemplateModel, TaskCategoryModel)
            .join(TaskCategoryModel, TaskCategoryModel.id == TaskTemplateModel.category_id)
            .where(TaskTemplateModel.id == template_id)
            .where(TaskTemplateModel.is_active.is_(True))
            .where(TaskCategoryModel.is_active.is_(True))
            .where(TaskTemplateModel.minimum_level <= level)
        )
    ).one_or_none()
    return None if row is None else _snapshot(row[0], row[1])


async def lock_template_versions(session: AsyncSession, code: str) -> tuple[CatalogTemplate, ...]:
    """Lock all versions of one logical template in version order."""
    rows = (
        await session.execute(
            select(TaskTemplateModel, TaskCategoryModel)
            .join(TaskCategoryModel, TaskCategoryModel.id == TaskTemplateModel.category_id)
            .where(TaskTemplateModel.code == code)
            .order_by(TaskTemplateModel.version)
            .with_for_update(of=TaskTemplateModel)
        )
    ).all()
    return tuple(_snapshot(template, category) for template, category in rows)


async def insert_template_version(
    session: AsyncSession,
    *,
    draft: TemplateDraft,
    version: int,
) -> CatalogTemplate:
    """Deactivate the old head and insert one immutable active version."""
    category = await session.scalar(
        select(TaskCategoryModel).where(TaskCategoryModel.code == draft.category_code)
    )
    if category is None:
        message = "Task category code does not exist."
        raise LookupError(message)
    await session.execute(
        update(TaskTemplateModel)
        .where(TaskTemplateModel.code == draft.code)
        .where(TaskTemplateModel.is_active.is_(True))
        .values(is_active=False)
    )
    model = TaskTemplateModel(
        id=uuid.uuid4(),
        category_id=category.id,
        code=draft.code,
        version=version,
        name=draft.name,
        description=draft.description,
        creator_instructions=draft.creator_instructions,
        performer_instructions=draft.performer_instructions,
        completion_criteria=draft.completion_criteria,
        input_schema_json=draft.input_schema,
        result_schema_json=draft.result_schema,
        credit_reward=draft.credit_reward,
        estimated_minutes=draft.estimated_minutes,
        format=draft.format.value,
        minimum_level=draft.minimum_level,
        maximum_performers=draft.maximum_performers,
        moderation_required=draft.moderation_required,
        is_active=True,
    )
    session.add(model)
    await session.flush()
    return _snapshot(model, category)


async def set_catalog_category_active(
    session: AsyncSession, *, code: str, enabled: bool
) -> uuid.UUID:
    """Toggle one category while retaining its immutable identity."""
    category = await session.scalar(
        select(TaskCategoryModel).where(TaskCategoryModel.code == code).with_for_update()
    )
    if category is None:
        message = "Task category code does not exist."
        raise LookupError(message)
    category.is_active = enabled
    await session.flush()
    return category.id


async def set_catalog_template_active(
    session: AsyncSession, *, code: str, enabled: bool
) -> CatalogTemplate:
    """Enable only the latest version or disable the current head."""
    rows = (
        await session.execute(
            select(TaskTemplateModel, TaskCategoryModel)
            .join(TaskCategoryModel, TaskCategoryModel.id == TaskTemplateModel.category_id)
            .where(TaskTemplateModel.code == code)
            .order_by(TaskTemplateModel.version)
            .with_for_update(of=TaskTemplateModel)
        )
    ).all()
    if not rows:
        message = "Task template code does not exist."
        raise LookupError(message)
    for model, _category in rows:
        model.is_active = False
    latest, category = rows[-1]
    latest.is_active = enabled
    await session.flush()
    return _snapshot(latest, category)


def _snapshot(model: TaskTemplateModel, category: TaskCategoryModel) -> CatalogTemplate:
    return CatalogTemplate(
        id=model.id,
        category_id=category.id,
        category_code=category.code,
        category_name=category.name,
        category_sort_order=category.sort_order,
        code=model.code,
        version=model.version,
        name=model.name,
        description=model.description,
        creator_instructions=model.creator_instructions,
        performer_instructions=model.performer_instructions,
        completion_criteria=model.completion_criteria,
        input_schema=dict(model.input_schema_json),
        result_schema=dict(model.result_schema_json),
        credit_reward=model.credit_reward,
        estimated_minutes=model.estimated_minutes,
        format=TaskFormat(model.format),
        minimum_level=model.minimum_level,
        maximum_performers=model.maximum_performers,
        moderation_required=model.moderation_required,
        is_active=model.is_active,
        category_is_active=category.is_active,
    )
