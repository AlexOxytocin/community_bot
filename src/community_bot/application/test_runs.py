# ruff: noqa: D102, D107, EM101, EM102, PT028, TRY003
"""Application contract for isolated live Telegram test runs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from community_bot.domain.members import is_superadministrator

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager
    from uuid import UUID

    from community_bot.domain.members import Member

_MARKER = re.compile(r"^TEST-[A-Z0-9][A-Z0-9_.-]{7,63}$")
_MIN_PARTICIPANTS = 2


class TestRunError(RuntimeError):
    """Raised when an isolated test run cannot change state safely."""


@dataclass(frozen=True, slots=True)
class TestRunScope:
    """Active test context attached to live actions of one participant."""

    id: UUID
    marker: str


@dataclass(frozen=True, slots=True)
class TestRunBlockers:
    """Nonterminal data that must be closed before a test run ends."""

    drafts: int
    tasks: int
    assignments: int

    @property
    def total(self) -> int:
        """Return the total number of unresolved test objects."""
        return self.drafts + self.tasks + self.assignments


@dataclass(frozen=True, slots=True)
class TestRunSnapshot:
    """Privacy-safe operational state of one test run."""

    scope: TestRunScope
    status: str
    participant_count: int
    blockers: TestRunBlockers


class TestRunUnitOfWork(Protocol):  # pragma: no cover - structural contract.
    """Persistence contract for test-run lifecycle operations."""

    async def members_by_telegram_ids(
        self, telegram_user_ids: Sequence[int]
    ) -> tuple[Member, ...]: ...
    async def create_test_run(
        self, *, marker: str, started_by_member_id: UUID, participant_ids: Sequence[UUID]
    ) -> TestRunSnapshot: ...
    async def test_run_snapshot(
        self, marker: str, *, for_update: bool = False
    ) -> TestRunSnapshot | None: ...
    async def finish_test_run(self, marker: str, *, failed: bool) -> TestRunSnapshot: ...
    async def cleanup_test_run(self, marker: str) -> int: ...
    async def append_audit_event(
        self,
        *,
        actor_member_id: UUID | None,
        action: str,
        entity_type: str,
        entity_id: str,
        reason: str | None,
    ) -> None: ...
    async def commit(self) -> None: ...


class TestRunUnitOfWorkFactory(Protocol):  # pragma: no cover - structural contract.
    """Create isolated test-run transactions."""

    def __call__(self) -> AbstractAsyncContextManager[TestRunUnitOfWork]: ...


class TestRunService:
    """Start and finish marked live smoke scopes without exposing identities."""

    def __init__(self, unit_of_work_factory: TestRunUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def begin(
        self, *, marker: str, participant_telegram_user_ids: Sequence[int]
    ) -> TestRunSnapshot:
        """Activate one scope for an allowlisted set of live Telegram users."""
        normalized = marker.strip().upper()
        if _MARKER.fullmatch(normalized) is None:
            raise TestRunError("Test marker must match TEST-[A-Z0-9_.-] and be 13-69 chars.")
        identities = tuple(dict.fromkeys(participant_telegram_user_ids))
        if len(identities) < _MIN_PARTICIPANTS:
            raise TestRunError("A live test run requires at least two distinct participants.")
        async with self._unit_of_work_factory() as uow:
            members = await uow.members_by_telegram_ids(identities)
            if len(members) != len(identities):
                raise TestRunError("Every test participant must be a registered active member.")
            by_identity = {item.telegram_user_id: item for item in members}
            ordered = tuple(by_identity[value] for value in identities)
            starter = ordered[0]
            if not is_superadministrator(starter):
                raise TestRunError("The first test participant must be the superadministrator.")
            snapshot = await uow.create_test_run(
                marker=normalized,
                started_by_member_id=starter.id,
                participant_ids=tuple(item.id for item in ordered),
            )
            await uow.append_audit_event(
                actor_member_id=starter.id,
                action="test_run_started",
                entity_type="test_run",
                entity_id=str(snapshot.scope.id),
                reason=normalized,
            )
            await uow.commit()
            return snapshot

    async def status(self, marker: str) -> TestRunSnapshot:
        """Return a privacy-safe snapshot without changing the run."""
        async with self._unit_of_work_factory() as uow:
            snapshot = await uow.test_run_snapshot(marker.strip().upper())
            if snapshot is None:
                raise TestRunError("Test run does not exist.")
            return snapshot

    async def cleanup(self, marker: str) -> TestRunSnapshot:
        """Cancel disposable community cards while retaining their audit history."""
        normalized = marker.strip().upper()
        async with self._unit_of_work_factory() as uow:
            current = await uow.test_run_snapshot(normalized, for_update=True)
            if current is None:
                raise TestRunError("Test run does not exist.")
            if current.status != "active":
                return current
            cancelled = await uow.cleanup_test_run(normalized)
            snapshot = await uow.test_run_snapshot(normalized)
            if snapshot is None:  # pragma: no cover - row is locked in this transaction.
                raise TestRunError("Test run disappeared during cleanup.")
            await uow.append_audit_event(
                actor_member_id=None,
                action="test_run_cleaned",
                entity_type="test_run",
                entity_id=str(snapshot.scope.id),
                reason=f"{normalized}; cancelled_community_tasks={cancelled}",
            )
            await uow.commit()
            return snapshot

    async def finish(self, *, marker: str, failed: bool = False) -> TestRunSnapshot:
        """Deactivate participants only after every test object is terminal."""
        normalized = marker.strip().upper()
        async with self._unit_of_work_factory() as uow:
            current = await uow.test_run_snapshot(normalized, for_update=True)
            if current is None:
                raise TestRunError("Test run does not exist.")
            if current.status != "active":
                return current
            if current.blockers.total:
                raise TestRunError(
                    "Test run still has nonterminal objects: "
                    f"drafts={current.blockers.drafts}, tasks={current.blockers.tasks}, "
                    f"assignments={current.blockers.assignments}."
                )
            snapshot = await uow.finish_test_run(normalized, failed=failed)
            await uow.append_audit_event(
                actor_member_id=None,
                action="test_run_failed" if failed else "test_run_completed",
                entity_type="test_run",
                entity_id=str(snapshot.scope.id),
                reason=normalized,
            )
            await uow.commit()
            return snapshot
