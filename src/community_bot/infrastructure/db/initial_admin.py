"""PostgreSQL unit of work for one-time administrator bootstrap."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

from sqlalchemy import select, text

from community_bot.application.initial_admin import InitialAdministratorMember
from community_bot.infrastructure.db.models import AuditEventModel, MemberModel

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from community_bot.application.initial_admin import InitialAdministratorReason

_BOOTSTRAP_NAMESPACE = "initial_administrator_bootstrap"
_BOOTSTRAP_ACTION = "initial_administrator_bootstrapped"
_PROFILE_REPAIR_ACTION = "initial_administrator_profile_repaired"
_ADMIN_PERMISSIONS = ["interaction_review", "karma_review", "member_read"]


class SqlAlchemyInitialAdministratorUnitOfWork:
    """Keep bootstrap member and provenance in one transaction."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        after_member_flushed: Callable[[], None] | None = None,
        after_audit_flushed: Callable[[], None] | None = None,
    ) -> None:
        """Configure a fresh session and optional deterministic fault hooks."""
        self._sessions = sessions
        self._after_member_flushed = after_member_flushed
        self._after_audit_flushed = after_audit_flushed
        self._session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        """Open one bootstrap transaction."""
        self._session = self._sessions()
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Rollback every unfinished bootstrap and close the session."""
        session = self._require_session()
        if not self._committed:
            await session.rollback()
        await session.close()

    async def acquire_gate(self) -> None:
        """Serialize all bootstrap attempts until transaction completion."""
        await self._require_session().execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:namespace, 0))"),
            {"namespace": _BOOTSTRAP_NAMESPACE},
        )

    async def active_administrators(self) -> tuple[InitialAdministratorMember, ...]:
        """Lock and return every active administrator in stable order."""
        models = (
            await self._require_session().scalars(
                select(MemberModel)
                .where(MemberModel.role == "administrator", MemberModel.status == "active")
                .order_by(MemberModel.id)
                .with_for_update()
            )
        ).all()
        return tuple(_member(model) for model in models)

    async def target_member(self, telegram_user_id: int) -> InitialAdministratorMember | None:
        """Lock an existing target identity of any role or status."""
        model = await self._require_session().scalar(
            select(MemberModel)
            .where(MemberModel.telegram_user_id == telegram_user_id)
            .with_for_update()
        )
        return None if model is None else _member(model)

    async def has_bootstrap_provenance(self, member_id: UUID) -> bool:
        """Check the append-only marker that distinguishes an exact retry."""
        marker = await self._require_session().scalar(
            select(AuditEventModel.id).where(
                AuditEventModel.actor_member_id.is_(None),
                AuditEventModel.action == _BOOTSTRAP_ACTION,
                AuditEventModel.entity_type == "member",
                AuditEventModel.entity_id == str(member_id),
            )
        )
        return marker is not None

    async def create_administrator(self, telegram_user_id: int) -> InitialAdministratorMember:
        """Insert the deterministic first-administrator security state."""
        now = datetime.now(UTC)
        model = MemberModel(
            id=uuid.uuid4(),
            telegram_user_id=telegram_user_id,
            telegram_username=None,
            display_name="Administrator",
            city=None,
            timezone="UTC",
            short_bio=None,
            current_goal=None,
            availability=None,
            help_categories_json=[],
            skill_tags_json=[],
            permissions_json=list(_ADMIN_PERMISSIONS),
            role="administrator",
            status="active",
            level_number=1,
            credit_balance_cached=0,
            experience_total_cached=0,
            approved_at=now,
        )
        self._require_session().add(model)
        await self._require_session().flush()
        if self._after_member_flushed is not None:
            self._after_member_flushed()
        return _member(model)

    async def append_bootstrap_audit(
        self,
        member_id: UUID,
        reason: InitialAdministratorReason,
    ) -> None:
        """Persist only allowlisted, non-private bootstrap provenance."""
        self._require_session().add(
            AuditEventModel(
                actor_member_id=None,
                action=_BOOTSTRAP_ACTION,
                entity_type="member",
                entity_id=str(member_id),
                before_json=None,
                after_json={
                    "permissions": list(_ADMIN_PERMISSIONS),
                    "role": "administrator",
                    "status": "active",
                },
                reason=reason.value,
            )
        )
        await self._require_session().flush()
        if self._after_audit_flushed is not None:
            self._after_audit_flushed()

    async def repair_display_name(self, member_id: UUID, display_name: str) -> bool:
        """Replace only the locked bootstrap administrator display name."""
        model = await self._require_session().get(MemberModel, member_id)
        if model is None:
            message = "Bootstrap administrator disappeared during profile repair."
            raise LookupError(message)
        if model.display_name == display_name:
            return False
        model.display_name = display_name
        await self._require_session().flush()
        if self._after_member_flushed is not None:
            self._after_member_flushed()
        return True

    async def append_profile_repair_audit(self, member_id: UUID) -> None:
        """Record a repair without persisting the private profile value."""
        self._require_session().add(
            AuditEventModel(
                actor_member_id=None,
                action=_PROFILE_REPAIR_ACTION,
                entity_type="member",
                entity_id=str(member_id),
                before_json=None,
                after_json={"display_name_repaired": True},
                reason="operator_request",
            )
        )
        await self._require_session().flush()
        if self._after_audit_flushed is not None:
            self._after_audit_flushed()

    async def commit(self) -> None:
        """Commit the complete member and audit result."""
        await self._require_session().commit()
        self._committed = True

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            message = "Initial-administrator unit of work has not been entered."
            raise RuntimeError(message)
        return self._session


def _member(model: MemberModel) -> InitialAdministratorMember:
    return InitialAdministratorMember(id=model.id, telegram_user_id=model.telegram_user_id)
