"""Application boundary for administrator appointments and individual rights."""

# ruff: noqa: D102, D107, EM101, PLR0913, PLR2004, TRY003

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from community_bot.domain.members import (
    AuthorizationError,
    Member,
    MemberRole,
    MemberStatus,
    assign_administrator,
    can_edit_administrator,
    can_manage_administrators,
    demote_administrator,
    effective_administrator_permissions,
    is_superadministrator,
    update_administrator_permissions,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager
    from uuid import UUID

    from community_bot.application.identity import ActorContext
    from community_bot.application.member_foundation import UpdateReceipt


@dataclass(frozen=True, slots=True)
class AdministratorIdentity:
    """Administrator-management projection safe for the Mini App."""

    member: Member
    telegram_username: str | None
    display_name: str


@dataclass(frozen=True, slots=True)
class AdministratorCard:
    """One administrator with actor-relative edit capabilities."""

    identity: AdministratorIdentity
    appointed_by: AdministratorIdentity | None
    can_edit: bool
    can_demote: bool


@dataclass(frozen=True, slots=True)
class AdministratorOverview:
    """Complete team state and current actor capabilities."""

    items: tuple[AdministratorCard, ...]
    actor_permissions: frozenset[str]
    can_appoint: bool
    can_delegate_administrator_management: bool
    can_grant_credits: bool


@dataclass(frozen=True, slots=True)
class AdministratorChange:
    """Idempotent appointment or permission update command."""

    update_id: int
    actor_member_id: UUID
    target_member_id: UUID
    permissions: frozenset[str]
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AdministratorDemotion:
    """Idempotent demotion command with a mandatory audit reason."""

    update_id: int
    actor_member_id: UUID
    target_member_id: UUID
    reason: str


class AdministrationUnitOfWork(Protocol):
    """Transactional storage required by administrator management."""

    async def acquire_update_gate(self, update_id: int) -> None: ...

    async def get_receipt(self, update_id: int) -> UpdateReceipt | None: ...

    async def get_member(self, member_id: UUID) -> Member | None: ...

    async def lock_members(self, member_ids: Sequence[UUID]) -> dict[UUID, Member]: ...

    async def administrator_identities(
        self, *, administrators_only: bool, query: str | None, limit: int
    ) -> tuple[AdministratorIdentity, ...]: ...

    async def administrator_identity(self, member_id: UUID) -> AdministratorIdentity | None: ...

    async def save_member(self, member: Member) -> None: ...

    async def flush_member_changes(self) -> None: ...

    async def append_member_audit(
        self,
        *,
        actor_id: UUID,
        before: Member,
        after: Member,
        reason: str | None,
    ) -> None: ...

    async def add_receipt(
        self,
        *,
        update_id: int,
        update_type: str,
        actor_id: UUID | None,
        outcome_code: str,
    ) -> None: ...

    async def commit(self) -> None: ...


class AdministrationUnitOfWorkFactory(Protocol):
    """Create isolated administrator-management transactions."""

    def __call__(self) -> AbstractAsyncContextManager[AdministrationUnitOfWork]: ...


class AdministrationService:
    """Authorize administrator reads and mutations from fresh persisted state."""

    def __init__(self, unit_of_work_factory: AdministrationUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def overview(self, actor: ActorContext) -> AdministratorOverview:
        """Return the administrator team visible to an active administrator."""
        async with self._unit_of_work_factory() as uow:
            member = await self._active_administrator(uow, actor.member_id)
            identities = await uow.administrator_identities(
                administrators_only=True, query=None, limit=100
            )
            return await self._overview(uow, member, identities)

    async def candidates(
        self, actor: ActorContext, *, query: str | None, limit: int
    ) -> tuple[AdministratorIdentity, ...]:
        """Search active non-administrators only for an actor who may appoint them."""
        async with self._unit_of_work_factory() as uow:
            member = await self._active_administrator(uow, actor.member_id)
            if not can_manage_administrators(member):
                raise AuthorizationError("Administrator management permission is required.")
            return await uow.administrator_identities(
                administrators_only=False, query=query, limit=limit
            )

    async def detail(self, actor: ActorContext, member_id: UUID) -> AdministratorCard:
        """Return one administrator with actor-relative capabilities."""
        async with self._unit_of_work_factory() as uow:
            current = await self._active_administrator(uow, actor.member_id)
            identity = await uow.administrator_identity(member_id)
            if identity is None or identity.member.role is not MemberRole.ADMINISTRATOR:
                raise LookupError("Administrator does not exist.")
            return await self._card(uow, current, identity)

    async def appoint(self, command: AdministratorChange, actor: ActorContext) -> AdministratorCard:
        """Appoint one active participant and persist provenance atomically."""
        return await self._change(command, actor, operation="administrator_appointed")

    async def update_permissions(
        self, command: AdministratorChange, actor: ActorContext
    ) -> AdministratorCard:
        """Replace one editable administrator's four product permissions."""
        return await self._change(command, actor, operation="administrator_permissions_updated")

    async def demote(
        self, command: AdministratorDemotion, actor: ActorContext
    ) -> AdministratorIdentity:
        """Demote one editable administrator to member with mandatory audit reason."""
        if command.actor_member_id != actor.member_id:
            raise AuthorizationError("Administrator actor identity does not match the session.")
        reason = " ".join(command.reason.split())
        if not 3 <= len(reason) <= 500:
            raise ValueError("Demotion reason must contain between 3 and 500 characters.")
        async with self._unit_of_work_factory() as uow:
            await uow.acquire_update_gate(command.update_id)
            receipt = await uow.get_receipt(command.update_id)
            if receipt is not None:
                identity = await uow.administrator_identity(command.target_member_id)
                if identity is None:
                    raise LookupError("Member does not exist.")
                return identity
            locked = await uow.lock_members((actor.member_id, command.target_member_id))
            current = locked[actor.member_id]
            before = locked[command.target_member_id]
            after = demote_administrator(actor=current, target=before)
            await self._persist(
                uow,
                current,
                before,
                after,
                update_id=command.update_id,
                update_type="administrator_demoted",
                reason=reason,
            )
            identity = await uow.administrator_identity(after.id)
            if identity is None:
                raise LookupError("Member does not exist.")
            return identity

    async def _change(
        self, command: AdministratorChange, actor: ActorContext, *, operation: str
    ) -> AdministratorCard:
        if command.actor_member_id != actor.member_id:
            raise AuthorizationError("Administrator actor identity does not match the session.")
        async with self._unit_of_work_factory() as uow:
            await uow.acquire_update_gate(command.update_id)
            receipt = await uow.get_receipt(command.update_id)
            if receipt is not None:
                return await self._existing_card(uow, actor.member_id, command.target_member_id)
            locked = await uow.lock_members((actor.member_id, command.target_member_id))
            current = locked[actor.member_id]
            before = locked[command.target_member_id]
            if operation == "administrator_appointed":
                after = assign_administrator(
                    actor=current,
                    target=before,
                    permissions=command.permissions,
                    appointed_at=datetime.datetime.now(datetime.UTC),
                )
            else:
                after = update_administrator_permissions(
                    actor=current, target=before, permissions=command.permissions
                )
            await self._persist(
                uow,
                current,
                before,
                after,
                update_id=command.update_id,
                update_type=operation,
                reason=command.reason,
            )
            identity = await uow.administrator_identity(after.id)
            if identity is None:
                raise LookupError("Administrator does not exist.")
            return await self._card(uow, current, identity)

    async def _persist(
        self,
        uow: AdministrationUnitOfWork,
        actor: Member,
        before: Member,
        after: Member,
        *,
        update_id: int,
        update_type: str,
        reason: str | None,
    ) -> None:
        await uow.save_member(after)
        await uow.flush_member_changes()
        await uow.append_member_audit(actor_id=actor.id, before=before, after=after, reason=reason)
        await uow.add_receipt(
            update_id=update_id,
            update_type=update_type,
            actor_id=actor.id,
            outcome_code=update_type,
        )
        await uow.commit()

    async def _existing_card(
        self, uow: AdministrationUnitOfWork, actor_id: UUID, target_id: UUID
    ) -> AdministratorCard:
        current = await self._active_administrator(uow, actor_id)
        identity = await uow.administrator_identity(target_id)
        if identity is None or identity.member.role is not MemberRole.ADMINISTRATOR:
            raise LookupError("Administrator does not exist.")
        return await self._card(uow, current, identity)

    async def _overview(
        self,
        uow: AdministrationUnitOfWork,
        actor: Member,
        identities: tuple[AdministratorIdentity, ...],
    ) -> AdministratorOverview:
        cards = tuple([await self._card(uow, actor, item) for item in identities])
        return AdministratorOverview(
            items=cards,
            actor_permissions=effective_administrator_permissions(actor),
            can_appoint=can_manage_administrators(actor),
            can_delegate_administrator_management=is_superadministrator(actor),
            can_grant_credits=is_superadministrator(actor),
        )

    async def _card(
        self,
        uow: AdministrationUnitOfWork,
        actor: Member,
        identity: AdministratorIdentity,
    ) -> AdministratorCard:
        appointed_by = None
        appointed_by_id = identity.member.administrator_appointed_by_member_id
        if appointed_by_id is not None:
            appointed_by = await uow.administrator_identity(appointed_by_id)
        editable = can_edit_administrator(actor=actor, target=identity.member)
        return AdministratorCard(identity, appointed_by, editable, editable)

    @staticmethod
    async def _active_administrator(uow: AdministrationUnitOfWork, member_id: UUID) -> Member:
        member = await uow.get_member(member_id)
        if (
            member is None
            or member.status is not MemberStatus.ACTIVE
            or member.role is not MemberRole.ADMINISTRATOR
        ):
            raise AuthorizationError("Only an active administrator may view the team.")
        return member


def administrator_is_owner(identity: AdministratorIdentity) -> bool:
    """Expose the owner marker without leaking the internal permission name."""
    return is_superadministrator(identity.member)
