# ruff: noqa: D102, D105, D107
"""Tests for isolated live test-run lifecycle rules."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Self
from uuid import uuid4

import pytest

from community_bot.application import test_runs as test_run_app
from community_bot.domain.members import Member, MemberRole, MemberStatus

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID


class FakeTestRunUnitOfWork:
    """Minimal transaction fake for lifecycle authorization tests."""

    def __init__(
        self,
        members: tuple[Member, ...],
        snapshot: test_run_app.TestRunSnapshot | None = None,
    ) -> None:
        self.members = members
        self.snapshot = snapshot
        self.committed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def members_by_telegram_ids(self, telegram_user_ids: Sequence[int]) -> tuple[Member, ...]:
        return tuple(item for item in self.members if item.telegram_user_id in telegram_user_ids)

    async def create_test_run(
        self,
        *,
        marker: str,
        started_by_member_id: UUID,
        participant_ids: Sequence[UUID],
    ) -> test_run_app.TestRunSnapshot:
        del started_by_member_id
        self.snapshot = test_run_app.TestRunSnapshot(
            test_run_app.TestRunScope(uuid4(), marker),
            "active",
            len(participant_ids),
            test_run_app.TestRunBlockers(0, 0, 0),
        )
        return self.snapshot

    async def test_run_snapshot(
        self, marker: str, *, for_update: bool = False
    ) -> test_run_app.TestRunSnapshot | None:
        del marker, for_update
        return self.snapshot

    async def finish_test_run(self, marker: str, *, failed: bool) -> test_run_app.TestRunSnapshot:
        del marker
        assert self.snapshot is not None
        self.snapshot = replace(self.snapshot, status="failed" if failed else "completed")
        return self.snapshot

    async def cleanup_test_run(self, marker: str) -> int:
        del marker
        assert self.snapshot is not None
        self.snapshot = replace(
            self.snapshot,
            blockers=test_run_app.TestRunBlockers(0, 0, 0),
        )
        return 2

    async def append_audit_event(
        self,
        *,
        actor_member_id: UUID | None,
        action: str,
        entity_type: str,
        entity_id: str,
        reason: str | None,
    ) -> None:
        del actor_member_id, action, entity_type, entity_id, reason

    async def commit(self) -> None:
        self.committed = True


def _member(identity: int, *, superadministrator: bool = False) -> Member:
    return Member(
        id=uuid4(),
        telegram_user_id=identity,
        role=MemberRole.ADMINISTRATOR if superadministrator else MemberRole.MEMBER,
        status=MemberStatus.ACTIVE,
        permissions=frozenset({"superadministrator"}) if superadministrator else frozenset(),
    )


@pytest.mark.asyncio
async def test_begin_requires_superadministrator_first_and_marks_run() -> None:
    owner = _member(100, superadministrator=True)
    participant = _member(200)
    uow = FakeTestRunUnitOfWork((owner, participant))

    snapshot = await test_run_app.TestRunService(lambda: uow).begin(
        marker="test-release-01",
        participant_telegram_user_ids=(100, 200),
    )

    assert snapshot.scope.marker == "TEST-RELEASE-01"
    assert snapshot.participant_count == 2
    assert uow.committed


@pytest.mark.asyncio
async def test_begin_rejects_non_owner_first() -> None:
    participant = _member(200)
    owner = _member(100, superadministrator=True)
    uow = FakeTestRunUnitOfWork((participant, owner))

    with pytest.raises(test_run_app.TestRunError, match="first test participant"):
        await test_run_app.TestRunService(lambda: uow).begin(
            marker="TEST-RELEASE-02",
            participant_telegram_user_ids=(200, 100),
        )


@pytest.mark.asyncio
async def test_finish_fails_closed_until_test_objects_are_terminal() -> None:
    snapshot = test_run_app.TestRunSnapshot(
        test_run_app.TestRunScope(uuid4(), "TEST-RELEASE-03"),
        "active",
        2,
        test_run_app.TestRunBlockers(1, 2, 3),
    )
    uow = FakeTestRunUnitOfWork((), snapshot)

    with pytest.raises(test_run_app.TestRunError, match="drafts=1, tasks=2, assignments=3"):
        await test_run_app.TestRunService(lambda: uow).finish(marker=snapshot.scope.marker)

    assert not uow.committed


@pytest.mark.asyncio
async def test_finish_releases_clean_run() -> None:
    snapshot = test_run_app.TestRunSnapshot(
        test_run_app.TestRunScope(uuid4(), "TEST-RELEASE-04"),
        "active",
        2,
        test_run_app.TestRunBlockers(0, 0, 0),
    )
    uow = FakeTestRunUnitOfWork((), snapshot)

    result = await test_run_app.TestRunService(lambda: uow).finish(marker=snapshot.scope.marker)

    assert result.status == "completed"
    assert uow.committed


@pytest.mark.asyncio
async def test_cleanup_refreshes_blockers_and_commits() -> None:
    snapshot = test_run_app.TestRunSnapshot(
        test_run_app.TestRunScope(uuid4(), "TEST-RELEASE-05"),
        "active",
        2,
        test_run_app.TestRunBlockers(0, 2, 0),
    )
    uow = FakeTestRunUnitOfWork((), snapshot)

    result = await test_run_app.TestRunService(lambda: uow).cleanup(snapshot.scope.marker)

    assert result.blockers.total == 0
    assert uow.committed
