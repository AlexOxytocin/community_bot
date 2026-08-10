"""Application services for the level-aware versioned task catalog."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from community_bot.domain.catalog import (
    CatalogCursor,
    CatalogError,
    TaskFormat,
    TemplateDraft,
    require_catalog_admin,
    require_catalog_member,
    validate_payload,
    validate_template_draft,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from contextlib import AbstractAsyncContextManager

    from community_bot.domain.economy import ResolvedLevel
    from community_bot.domain.members import Member

_MAX_PAGE_SIZE = 20


@dataclass(frozen=True, slots=True)
class CatalogTemplate:
    """One persisted immutable template version."""

    id: UUID
    category_id: UUID
    category_code: str
    category_name: str
    category_sort_order: int
    code: str
    version: int
    name: str
    description: str
    creator_instructions: str
    performer_instructions: str
    completion_criteria: str
    input_schema: dict[str, object]
    result_schema: dict[str, object]
    credit_reward: int
    estimated_minutes: int
    format: TaskFormat
    minimum_level: int
    maximum_performers: int
    moderation_required: bool
    is_active: bool
    category_is_active: bool

    def draft(self, **changes: object) -> TemplateDraft:
        """Copy immutable content into a candidate for the next version."""
        draft = TemplateDraft(
            category_code=self.category_code,
            code=self.code,
            name=self.name,
            description=self.description,
            creator_instructions=self.creator_instructions,
            performer_instructions=self.performer_instructions,
            completion_criteria=self.completion_criteria,
            input_schema=self.input_schema,
            result_schema=self.result_schema,
            credit_reward=self.credit_reward,
            estimated_minutes=self.estimated_minutes,
            format=self.format,
            minimum_level=self.minimum_level,
            maximum_performers=self.maximum_performers,
            moderation_required=self.moderation_required,
        )
        return replace(draft, **changes)


@dataclass(frozen=True, slots=True)
class CatalogQuery:
    """Untrusted catalog filters and keyset position."""

    actor_telegram_user_id: int
    category_code: str | None = None
    format: TaskFormat | None = None
    cursor: CatalogCursor | None = None
    limit: int = 6


@dataclass(frozen=True, slots=True)
class CatalogPage:
    """One deterministic catalog page."""

    items: tuple[CatalogTemplate, ...]
    next_cursor: CatalogCursor | None


@dataclass(frozen=True, slots=True)
class PublishTemplateVersionCommand:
    """Publish a fully validated immutable template version."""

    update_id: int
    actor_telegram_user_id: int
    draft: TemplateDraft


class CatalogUnitOfWork(Protocol):
    """Caller-owned transaction required by catalog workflows."""

    async def acquire_update_gate(self, update_id: int) -> None:
        """Serialize one exact Telegram update."""
        ...

    async def get_receipt_outcome(self, update_id: int) -> str | None:
        """Read a committed exact-update outcome."""
        ...

    async def acquire_catalog_mutation_gate(self) -> None:
        """Serialize catalog mutations after the update gate."""
        ...

    async def get_member_by_telegram_user_id(self, telegram_user_id: int) -> Member | None:
        """Resolve a member by Telegram identity."""
        ...

    async def lock_members(self, member_ids: Sequence[UUID]) -> dict[UUID, Member]:
        """Lock members in canonical UUID order."""
        ...

    async def resolve_member_level(self, member_id: UUID) -> ResolvedLevel:
        """Resolve a member against the active product configuration."""
        ...

    async def catalog_page(self, *, query: CatalogQuery, level: int) -> CatalogPage:
        """Return one keyset catalog page."""
        ...

    async def catalog_template(self, template_id: UUID) -> CatalogTemplate | None:
        """Read one historical template version."""
        ...

    async def template_for_creation(
        self, *, template_id: UUID, level: int
    ) -> CatalogTemplate | None:
        """Read an active version available to a resolved level."""
        ...

    async def lock_template_versions(self, code: str) -> tuple[CatalogTemplate, ...]:
        """Lock all versions of one logical code."""
        ...

    async def insert_template_version(
        self, *, draft: TemplateDraft, version: int
    ) -> CatalogTemplate:
        """Insert one active immutable version."""
        ...

    async def set_catalog_category_active(self, *, code: str, enabled: bool) -> UUID:
        """Toggle one category."""
        ...

    async def set_catalog_template_active(self, *, code: str, enabled: bool) -> CatalogTemplate:
        """Toggle the latest template version."""
        ...

    async def append_audit_event(
        self,
        *,
        actor_member_id: UUID | None,
        action: str,
        entity_type: str,
        entity_id: str,
        reason: str | None,
    ) -> None:
        """Append one administrative audit event."""
        ...

    async def add_receipt(
        self,
        *,
        update_id: int,
        update_type: str,
        actor_id: UUID | None,
        outcome_code: str,
    ) -> None:
        """Stage one complete Telegram update receipt."""
        ...

    async def commit(self) -> None:
        """Commit all staged effects once."""
        ...


class CatalogUnitOfWorkFactory(Protocol):
    """Create isolated catalog transactions."""

    def __call__(self) -> AbstractAsyncContextManager[CatalogUnitOfWork]:
        """Return a fresh isolated unit of work."""
        ...


class CatalogService:
    """Browse and administer the immutable task catalog."""

    def __init__(self, unit_of_work_factory: CatalogUnitOfWorkFactory) -> None:
        """Configure the shared unit-of-work factory."""
        self._unit_of_work_factory = unit_of_work_factory

    async def browse(self, query: CatalogQuery) -> CatalogPage:
        """Return active templates available to the actor's resolved level."""
        if not 1 <= query.limit <= _MAX_PAGE_SIZE:
            message = "Catalog page size must be between 1 and 20."
            raise CatalogError(message)
        async with self._unit_of_work_factory() as unit_of_work:
            actor = await _active_actor(unit_of_work, query.actor_telegram_user_id)
            level = await unit_of_work.resolve_member_level(actor.id)
            return await unit_of_work.catalog_page(query=query, level=level.level_number)

    async def for_creation(
        self,
        *,
        actor_telegram_user_id: int,
        template_id: UUID,
        input_payload: Mapping[str, object],
    ) -> tuple[CatalogTemplate, dict[str, object]]:
        """Return an eligible exact version and validated input for CB-10."""
        async with self._unit_of_work_factory() as unit_of_work:
            actor = await _active_actor(unit_of_work, actor_telegram_user_id)
            level = await unit_of_work.resolve_member_level(actor.id)
            template = await unit_of_work.template_for_creation(
                template_id=template_id,
                level=level.level_number,
            )
            if template is None:
                message = "Task template is inactive or unavailable to this member."
                raise PermissionError(message)
            return template, validate_payload(template.input_schema, input_payload)

    async def validate_result(
        self, *, template_id: UUID, payload: Mapping[str, object]
    ) -> dict[str, object]:
        """Validate a result against the exact historical template version."""
        async with self._unit_of_work_factory() as unit_of_work:
            template = await unit_of_work.catalog_template(template_id)
            if template is None:
                message = "Task template version does not exist."
                raise LookupError(message)
            return validate_payload(template.result_schema, payload)

    async def set_category_active(
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        code: str,
        enabled: bool,
    ) -> str:
        """Toggle one immutable category idempotently."""
        async with self._unit_of_work_factory() as unit_of_work:
            stored = await _begin_mutation(
                unit_of_work, update_id=update_id, actor_telegram_user_id=actor_telegram_user_id
            )
            if stored is not None:
                return _expected_outcome(stored, "catalog_category:")
            actor = await _locked_admin(unit_of_work, actor_telegram_user_id)
            category_id = await unit_of_work.set_catalog_category_active(code=code, enabled=enabled)
            outcome = f"catalog_category:{code}:{int(enabled)}"
            await _finish_mutation(
                unit_of_work,
                update_id=update_id,
                actor=actor,
                outcome=outcome,
                entity_type="task_category",
                entity_id=str(category_id),
            )
            return outcome

    async def set_template_active(
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        code: str,
        enabled: bool,
    ) -> str:
        """Toggle the latest version of one logical template."""
        async with self._unit_of_work_factory() as unit_of_work:
            stored = await _begin_mutation(
                unit_of_work, update_id=update_id, actor_telegram_user_id=actor_telegram_user_id
            )
            if stored is not None:
                return _expected_outcome(stored, "catalog_template:")
            actor = await _locked_admin(unit_of_work, actor_telegram_user_id)
            template = await unit_of_work.set_catalog_template_active(code=code, enabled=enabled)
            outcome = f"catalog_template:{code}:{int(enabled)}:{template.id}"
            await _finish_mutation(
                unit_of_work,
                update_id=update_id,
                actor=actor,
                outcome=outcome,
                entity_type="task_template",
                entity_id=str(template.id),
            )
            return outcome

    async def publish_version(self, command: PublishTemplateVersionCommand) -> CatalogTemplate:
        """Publish one immutable version after full validation."""
        draft = validate_template_draft(command.draft)
        async with self._unit_of_work_factory() as unit_of_work:
            stored = await _begin_mutation(
                unit_of_work,
                update_id=command.update_id,
                actor_telegram_user_id=command.actor_telegram_user_id,
            )
            if stored is not None:
                template_id = UUID(_expected_outcome(stored, "catalog_version:").split(":")[1])
                template = await unit_of_work.catalog_template(template_id)
                if template is None:
                    message = "Stored catalog version no longer exists."
                    raise CatalogError(message)
                return template
            actor = await _locked_admin(unit_of_work, command.actor_telegram_user_id)
            versions = await unit_of_work.lock_template_versions(draft.code)
            if versions and any(item.category_code != draft.category_code for item in versions):
                message = "Task template category is immutable across versions."
                raise CatalogError(message)
            version = 1 if not versions else max(item.version for item in versions) + 1
            template = await unit_of_work.insert_template_version(
                draft=draft,
                version=version,
            )
            outcome = f"catalog_version:{template.id}:{template.version}"
            await _finish_mutation(
                unit_of_work,
                update_id=command.update_id,
                actor=actor,
                outcome=outcome,
                entity_type="task_template",
                entity_id=str(template.id),
            )
            return template

    async def change_reward(
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        code: str,
        credit_reward: int,
    ) -> CatalogTemplate:
        """Clone the latest version with a new reward."""
        async with self._unit_of_work_factory() as unit_of_work:
            stored = await _begin_mutation(
                unit_of_work, update_id=update_id, actor_telegram_user_id=actor_telegram_user_id
            )
            if stored is not None:
                template_id = UUID(_expected_outcome(stored, "catalog_version:").split(":")[1])
                template = await unit_of_work.catalog_template(template_id)
                if template is None:
                    message = "Stored catalog version no longer exists."
                    raise CatalogError(message)
                return template
            actor = await _locked_admin(unit_of_work, actor_telegram_user_id)
            versions = await unit_of_work.lock_template_versions(code)
            if not versions:
                message = "Task template code does not exist."
                raise LookupError(message)
            latest = max(versions, key=lambda item: item.version)
            draft = validate_template_draft(latest.draft(credit_reward=credit_reward))
            template = await unit_of_work.insert_template_version(
                draft=draft,
                version=latest.version + 1,
            )
            outcome = f"catalog_version:{template.id}:{template.version}"
            await _finish_mutation(
                unit_of_work,
                update_id=update_id,
                actor=actor,
                outcome=outcome,
                entity_type="task_template",
                entity_id=str(template.id),
            )
            return template


async def _active_actor(unit_of_work: CatalogUnitOfWork, telegram_user_id: int) -> Member:
    actor = await unit_of_work.get_member_by_telegram_user_id(telegram_user_id)
    if actor is None:
        message = "Catalog actor is not a registered member."
        raise PermissionError(message)
    require_catalog_member(actor)
    return actor


async def _begin_mutation(
    unit_of_work: CatalogUnitOfWork,
    *,
    update_id: int,
    actor_telegram_user_id: int,
) -> str | None:
    del actor_telegram_user_id
    await unit_of_work.acquire_update_gate(update_id)
    stored = await unit_of_work.get_receipt_outcome(update_id)
    if stored is not None:
        return stored
    await unit_of_work.acquire_catalog_mutation_gate()
    return None


async def _locked_admin(unit_of_work: CatalogUnitOfWork, telegram_user_id: int) -> Member:
    actor = await unit_of_work.get_member_by_telegram_user_id(telegram_user_id)
    if actor is None:
        message = "Catalog administrator is not a registered member."
        raise PermissionError(message)
    actor = (await unit_of_work.lock_members((actor.id,)))[actor.id]
    require_catalog_admin(actor)
    return actor


async def _finish_mutation(  # noqa: PLR0913 - audit fields stay explicit.
    unit_of_work: CatalogUnitOfWork,
    *,
    update_id: int,
    actor: Member,
    outcome: str,
    entity_type: str,
    entity_id: str,
) -> None:
    await unit_of_work.append_audit_event(
        actor_member_id=actor.id,
        action=outcome.split(":", 1)[0],
        entity_type=entity_type,
        entity_id=entity_id,
        reason=outcome,
    )
    await unit_of_work.add_receipt(
        update_id=update_id,
        update_type="catalog_mutation",
        actor_id=actor.id,
        outcome_code=outcome,
    )
    await unit_of_work.commit()


def _expected_outcome(outcome: str, prefix: str) -> str:
    if not outcome.startswith(prefix):
        message = "Telegram update was already used by another operation."
        raise CatalogError(message)
    return outcome
