from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.initial_admin import (
    InitialAdministratorCommand,
    InitialAdministratorConflictError,
    InitialAdministratorProfileRepairCommand,
    InitialAdministratorReason,
    InitialAdministratorService,
)
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.db.models import (
    AuditEventModel,
    MemberModel,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

TelegramType = TypeVar("TelegramType")
_TOKEN_SECRET = "x" * 32
_CONFIG_PATH = Path(__file__).parents[2] / "config" / "product-config.v2.json"


def _command(telegram_user_id: int) -> InitialAdministratorCommand:
    return InitialAdministratorCommand(
        telegram_user_id=telegram_user_id,
        reason=InitialAdministratorReason.INITIAL_INSTALL,
    )


async def _counts(database: Database) -> tuple[int, int]:
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        members = await session.scalar(select(func.count()).select_from(MemberModel))
        audit = await session.scalar(select(func.count()).select_from(AuditEventModel))
    assert members is not None
    assert audit is not None
    return members, audit


async def test_bootstrap_is_idempotent_and_conflicts_fail_closed(database_url: str) -> None:
    database = Database(database_url)
    service = InitialAdministratorService(database.initial_administrator_unit_of_work)

    created = await service.bootstrap(_command(1_001))
    replayed = await service.bootstrap(_command(1_001))
    assert created.created is True
    assert replayed.created is False
    assert replayed.member_id == created.member_id
    assert await _counts(database) == (1, 1)

    with pytest.raises(InitialAdministratorConflictError):
        await service.bootstrap(_command(1_002))
    assert await _counts(database) == (1, 1)
    await database.dispose()


@pytest.mark.parametrize(
    ("role", "status"),
    [("member", "pending"), ("administrator", "active")],
)
async def test_existing_target_without_provenance_is_rejected(
    database_url: str,
    role: str,
    status: str,
) -> None:
    database = Database(database_url)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add(
            MemberModel(
                id=uuid4(),
                telegram_user_id=2_001,
                display_name="Existing",
                timezone="UTC",
                role=role,
                status=status,
                level_number=1,
            )
        )

    service = InitialAdministratorService(database.initial_administrator_unit_of_work)
    with pytest.raises(InitialAdministratorConflictError):
        await service.bootstrap(_command(2_001))
    assert await _counts(database) == (1, 0)
    await database.dispose()


async def test_exact_retry_conflicts_when_another_active_administrator_exists(
    database_url: str,
) -> None:
    database = Database(database_url)
    service = InitialAdministratorService(database.initial_administrator_unit_of_work)
    await service.bootstrap(_command(2_101))
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add(
            MemberModel(
                id=uuid4(),
                telegram_user_id=2_102,
                display_name="Second administrator",
                timezone="UTC",
                role="administrator",
                status="active",
                level_number=1,
            )
        )

    with pytest.raises(InitialAdministratorConflictError):
        await service.bootstrap(_command(2_101))
    with pytest.raises(InitialAdministratorConflictError):
        await service.repair_profile(
            InitialAdministratorProfileRepairCommand(
                telegram_user_id=2_101,
                display_name="Should not be saved",
            )
        )
    assert await _counts(database) == (2, 1)
    await database.dispose()


async def test_bootstrap_fault_rolls_back_and_retry_wins(database_url: str) -> None:
    database = Database(database_url)

    def fail_after_audit() -> None:
        message = "synthetic audit fault"
        raise RuntimeError(message)

    failing = InitialAdministratorService(
        lambda: database.initial_administrator_unit_of_work(after_audit_flushed=fail_after_audit)
    )
    with pytest.raises(RuntimeError, match="synthetic audit fault"):
        await failing.bootstrap(_command(3_001))
    assert await _counts(database) == (0, 0)

    result = await InitialAdministratorService(
        database.initial_administrator_unit_of_work
    ).bootstrap(_command(3_001))
    assert result.created is True
    assert await _counts(database) == (1, 1)
    await database.dispose()


async def test_profile_repair_is_utf8_safe_idempotent_and_fail_closed(
    database_url: str,
) -> None:
    database = Database(database_url)
    service = InitialAdministratorService(database.initial_administrator_unit_of_work)
    created = await service.bootstrap(_command(3_101))
    command = InitialAdministratorProfileRepairCommand(
        telegram_user_id=3_101,
        display_name="  Алексей Тестовый  ",
    )

    repaired = await service.repair_profile(command)
    replayed = await service.repair_profile(command)
    assert repaired.changed is True
    assert replayed.changed is False
    assert replayed.member_id == created.member_id

    with pytest.raises(InitialAdministratorConflictError):
        await service.repair_profile(
            InitialAdministratorProfileRepairCommand(
                telegram_user_id=3_102,
                display_name="Другой администратор",
            )
        )

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        member = await session.get(MemberModel, created.member_id)
        repair_events = (
            await session.scalars(
                select(AuditEventModel).where(
                    AuditEventModel.action == "initial_administrator_profile_repaired"
                )
            )
        ).all()
    assert member is not None
    assert member.display_name == "Алексей Тестовый"
    assert member.timezone == "UTC"
    assert member.city is None
    assert member.role == "administrator"
    assert member.status == "active"
    assert member.permissions_json == [
        "interaction_review",
        "karma_review",
        "member_read",
        "superadministrator",
    ]
    assert member.credit_balance_cached == 0
    assert member.experience_total_cached == 0
    assert len(repair_events) == 1
    assert repair_events[0].before_json is None
    assert repair_events[0].after_json == {"display_name_repaired": True}
    assert repair_events[0].reason == "operator_request"
    assert "Алексей" not in str(repair_events[0].after_json)
    assert "3101" not in str(repair_events[0].after_json)
    await database.dispose()


async def test_profile_repair_fault_rolls_back_and_retry_succeeds(database_url: str) -> None:
    database = Database(database_url)
    regular = InitialAdministratorService(database.initial_administrator_unit_of_work)
    created = await regular.bootstrap(_command(3_201))

    def fail_after_audit() -> None:
        message = "synthetic profile repair audit fault"
        raise RuntimeError(message)

    failing = InitialAdministratorService(
        lambda: database.initial_administrator_unit_of_work(after_audit_flushed=fail_after_audit)
    )
    command = InitialAdministratorProfileRepairCommand(
        telegram_user_id=3_201,
        display_name="Исправленное имя",
    )
    with pytest.raises(RuntimeError, match="synthetic profile repair audit fault"):
        await failing.repair_profile(command)

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        unchanged = await session.get(MemberModel, created.member_id)
        repair_count = await session.scalar(
            select(func.count())
            .select_from(AuditEventModel)
            .where(AuditEventModel.action == "initial_administrator_profile_repaired")
        )
    assert unchanged is not None
    assert unchanged.display_name == "Administrator"
    assert repair_count == 0

    retry = await regular.repair_profile(command)
    assert retry.changed is True
    await database.dispose()


async def test_profile_repair_requires_exact_bootstrap_provenance(database_url: str) -> None:
    database = Database(database_url)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add(
            MemberModel(
                id=uuid4(),
                telegram_user_id=3_301,
                display_name="Existing administrator",
                timezone="UTC",
                role="administrator",
                status="active",
                level_number=1,
            )
        )
    service = InitialAdministratorService(database.initial_administrator_unit_of_work)
    with pytest.raises(InitialAdministratorConflictError):
        await service.repair_profile(
            InitialAdministratorProfileRepairCommand(
                telegram_user_id=3_301,
                display_name="Нельзя изменить",
            )
        )
    with pytest.raises(ValueError, match="display name length"):
        InitialAdministratorProfileRepairCommand(
            telegram_user_id=3_301,
            display_name="?",
        )
    async with sessions() as session:
        unchanged = await session.scalar(
            select(MemberModel).where(MemberModel.telegram_user_id == 3_301)
        )
    assert unchanged is not None
    assert unchanged.display_name == "Existing administrator"
    assert await _counts(database) == (1, 0)
    await database.dispose()


@pytest.mark.parametrize("same_identity", [True, False])
async def test_concurrent_bootstrap_has_one_persisted_winner(
    database_url: str,
    *,
    same_identity: bool,
) -> None:
    database = Database(database_url)
    service = InitialAdministratorService(database.initial_administrator_unit_of_work)
    second_id = 4_001 if same_identity else 4_002
    results = await asyncio.wait_for(
        asyncio.gather(
            service.bootstrap(_command(4_001)),
            service.bootstrap(_command(second_id)),
            return_exceptions=True,
        ),
        timeout=10,
    )

    assert await _counts(database) == (1, 1)
    if same_identity:
        assert {result.created for result in results if not isinstance(result, BaseException)} == {
            False,
            True,
        }
        assert not any(isinstance(result, BaseException) for result in results)
    else:
        assert sum(not isinstance(result, BaseException) for result in results) == 1
        assert sum(isinstance(result, InitialAdministratorConflictError) for result in results) == 1
    await database.dispose()
