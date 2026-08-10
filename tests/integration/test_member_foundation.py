from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar, cast, override
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.types import Chat, Message, Update, User
from alembic import command
from alembic.config import Config
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from community_bot.application.member_foundation import (
    AdministrativeChange,
    MemberFoundationService,
    ReadMemberQuery,
)
from community_bot.domain.members import (
    AuthorizationError,
    ChangeKind,
    MemberRole,
    MemberStatus,
    StartOutcome,
)
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AuditEventModel,
    MemberModel,
    ProcessedTelegramUpdateModel,
)
from community_bot.transport.telegram.member_foundation import (
    REFRESH_MENU_TEXT,
    build_member_foundation_router,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

TelegramType = TypeVar("TelegramType")

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from aiogram.methods import TelegramMethod


def fake_bot_token() -> str:
    """Return a structurally valid synthetic token that cannot authenticate."""
    return f"{123456}:{'T' * 35}"


async def add_member(
    database: Database,
    *,
    telegram_user_id: int,
    role: MemberRole = MemberRole.MEMBER,
    status: MemberStatus = MemberStatus.ACTIVE,
) -> MemberModel:
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        model = MemberModel(
            telegram_user_id=telegram_user_id,
            display_name=f"Member {telegram_user_id}",
            timezone="UTC",
            role=role.value,
            status=status.value,
            level_number=1,
        )
        session.add(model)
    return model


async def scalar_count(database: Database, model: type[Any]) -> int:
    async with database.engine.connect() as connection:
        return int(await connection.scalar(select(func.count()).select_from(model)) or 0)


async def test_start_outcome_is_persistent_and_duplicate_safe(database_url: str) -> None:
    database = Database(database_url)
    service = MemberFoundationService(database.unit_of_work)
    member = await add_member(database, telegram_user_id=10)

    first = await service.process_start(update_id=100, telegram_user_id=member.telegram_user_id)
    await database.dispose()

    restarted = Database(database_url)
    repeated = await MemberFoundationService(restarted.unit_of_work).process_start(
        update_id=100,
        telegram_user_id=member.telegram_user_id,
    )

    assert first is StartOutcome.MAIN_MENU
    assert repeated is first
    assert await scalar_count(restarted, ProcessedTelegramUpdateModel) == 1
    await restarted.dispose()


async def test_unknown_and_all_member_status_routes_use_persistent_receipts(
    database_url: str,
) -> None:
    database = Database(database_url)
    service = MemberFoundationService(database.unit_of_work)

    unknown = await service.process_start(update_id=90, telegram_user_id=9_000)
    assert unknown is StartOutcome.REGISTRATION_REQUIRED
    assert await scalar_count(database, MemberModel) == 0

    expected = {
        MemberStatus.PENDING: StartOutcome.REGISTRATION_PENDING,
        MemberStatus.ACTIVE: StartOutcome.MAIN_MENU,
        MemberStatus.PAUSED: StartOutcome.ACCOUNT_UNAVAILABLE,
        MemberStatus.RESTRICTED: StartOutcome.ACCOUNT_UNAVAILABLE,
        MemberStatus.SUSPENDED: StartOutcome.ACCOUNT_UNAVAILABLE,
        MemberStatus.LEFT: StartOutcome.ACCOUNT_UNAVAILABLE,
        MemberStatus.BANNED: StartOutcome.ACCOUNT_UNAVAILABLE,
    }
    for offset, (status, expected_outcome) in enumerate(expected.items(), start=1):
        seeded = await add_member(database, telegram_user_id=9_000 + offset, status=status)
        outcome = await service.process_start(
            update_id=90 + offset,
            telegram_user_id=seeded.telegram_user_id,
        )
        assert outcome is expected_outcome

    assert await scalar_count(database, ProcessedTelegramUpdateModel) == 8
    await database.dispose()


async def test_concurrent_duplicate_admin_update_commits_one_effect(database_url: str) -> None:
    database = Database(database_url)
    actor = await add_member(
        database,
        telegram_user_id=20,
        role=MemberRole.ADMINISTRATOR,
    )
    target = await add_member(database, telegram_user_id=21)
    command_input = AdministrativeChange(
        update_id=200,
        telegram_user_id=actor.telegram_user_id,
        target_member_id=target.id,
        kind=ChangeKind.ROLE,
        requested_value=MemberRole.MODERATOR.value,
        reason="Access review",
    )
    service = MemberFoundationService(database.unit_of_work)

    results = await asyncio.gather(
        service.change_member(command_input),
        service.change_member(command_input),
    )
    changed_payload_result = await service.change_member(
        AdministrativeChange(
            update_id=command_input.update_id,
            telegram_user_id=-1,
            target_member_id=uuid4(),
            kind=ChangeKind.STATUS,
            requested_value=MemberStatus.BANNED.value,
        )
    )

    assert {result.outcome_code for result in results} == {"member_changed"}
    assert changed_payload_result.outcome_code == "member_changed"
    assert await scalar_count(database, AuditEventModel) == 1
    assert await scalar_count(database, ProcessedTelegramUpdateModel) == 1
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        audit = await session.scalar(select(AuditEventModel))
    assert audit is not None
    assert audit.actor_member_id == actor.id
    assert audit.reason == "Access review"
    assert audit.before_json is not None
    assert audit.before_json["role"] == MemberRole.MEMBER.value
    assert audit.after_json is not None
    assert audit.after_json["role"] == MemberRole.MODERATOR.value
    await database.dispose()


async def test_fault_between_member_save_and_audit_rolls_back_then_retries(
    database_url: str,
) -> None:
    database = Database(database_url)
    actor = await add_member(
        database,
        telegram_user_id=30,
        role=MemberRole.ADMINISTRATOR,
    )
    target = await add_member(database, telegram_user_id=31)
    command_input = AdministrativeChange(
        update_id=300,
        telegram_user_id=actor.telegram_user_id,
        target_member_id=target.id,
        kind=ChangeKind.STATUS,
        requested_value=MemberStatus.PAUSED.value,
    )
    executed_member_updates: list[str] = []

    def record_member_update(*args: object) -> None:
        statement = str(args[2])
        if statement.lstrip().upper().startswith("UPDATE MEMBERS"):
            executed_member_updates.append(statement)

    event.listen(database.engine.sync_engine, "after_cursor_execute", record_member_update)

    def fail_after_save() -> None:
        assert executed_member_updates
        msg = "Injected failure"
        raise RuntimeError(msg)

    try:
        with pytest.raises(RuntimeError, match="Injected failure"):
            await MemberFoundationService(
                database.unit_of_work,
                after_member_saved=fail_after_save,
            ).change_member(command_input)
    finally:
        event.remove(database.engine.sync_engine, "after_cursor_execute", record_member_update)

    assert await scalar_count(database, AuditEventModel) == 0
    assert await scalar_count(database, ProcessedTelegramUpdateModel) == 0
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        after_rollback = await session.get(MemberModel, target.id)
    assert after_rollback is not None
    assert after_rollback.status == MemberStatus.ACTIVE.value

    result = await MemberFoundationService(database.unit_of_work).change_member(command_input)

    assert result.outcome_code == "member_changed"
    async with sessions() as session:
        changed = await session.get(MemberModel, target.id)
    assert changed is not None
    assert changed.status == MemberStatus.PAUSED.value
    assert await scalar_count(database, AuditEventModel) == 1
    assert await scalar_count(database, ProcessedTelegramUpdateModel) == 1
    await database.dispose()


async def test_persisted_read_authorization_and_ownership_matrix(database_url: str) -> None:
    database = Database(database_url)
    service = MemberFoundationService(database.unit_of_work)
    active_member = await add_member(database, telegram_user_id=3_500)
    active_moderator = await add_member(
        database,
        telegram_user_id=3_501,
        role=MemberRole.MODERATOR,
    )
    active_admin = await add_member(
        database,
        telegram_user_id=3_502,
        role=MemberRole.ADMINISTRATOR,
    )
    second_admin = await add_member(
        database,
        telegram_user_id=3_503,
        role=MemberRole.ADMINISTRATOR,
    )
    inactive_admin = await add_member(
        database,
        telegram_user_id=3_504,
        role=MemberRole.ADMINISTRATOR,
        status=MemberStatus.PAUSED,
    )

    for actor in (active_member, active_moderator):
        own = await service.read_member(
            ReadMemberQuery(
                telegram_user_id=actor.telegram_user_id,
                target_member_id=actor.id,
            )
        )
        assert own.id == actor.id
        with pytest.raises(AuthorizationError):
            await service.read_member(
                ReadMemberQuery(
                    telegram_user_id=actor.telegram_user_id,
                    target_member_id=active_member.id
                    if actor.id != active_member.id
                    else active_moderator.id,
                )
            )

    for target in (active_member, active_moderator, second_admin):
        readable = await service.read_member(
            ReadMemberQuery(
                telegram_user_id=active_admin.telegram_user_id,
                target_member_id=target.id,
            )
        )
        assert readable.id == target.id

    with pytest.raises(AuthorizationError):
        await service.read_member(
            ReadMemberQuery(
                telegram_user_id=inactive_admin.telegram_user_id,
                target_member_id=inactive_admin.id,
            )
        )
    with pytest.raises(AuthorizationError):
        await service.read_member(
            ReadMemberQuery(telegram_user_id=-1, target_member_id=active_member.id)
        )
    await database.dispose()


@pytest.mark.parametrize("update_id", [2_147_483_648, 9_223_372_036_854_775_807])
async def test_bigint_update_id_boundary_is_duplicate_safe(
    database_url: str,
    update_id: int,
) -> None:
    database = Database(database_url)
    service = MemberFoundationService(database.unit_of_work)

    first = await service.process_start(update_id=update_id, telegram_user_id=8_000)
    repeated = await service.process_start(update_id=update_id, telegram_user_id=8_001)

    assert first is StartOutcome.REGISTRATION_REQUIRED
    assert repeated is first
    assert await scalar_count(database, ProcessedTelegramUpdateModel) == 1
    await database.dispose()


async def test_persistent_actor_authorization_matrix_denies_every_unlisted_actor(
    database_url: str,
) -> None:
    database = Database(database_url)
    target = await add_member(database, telegram_user_id=399)
    service = MemberFoundationService(database.unit_of_work)
    update_id = 310
    for role in MemberRole:
        for status in MemberStatus:
            if role is MemberRole.ADMINISTRATOR and status is MemberStatus.ACTIVE:
                continue
            actor = await add_member(
                database,
                telegram_user_id=1_000 + update_id,
                role=role,
                status=status,
            )
            with pytest.raises(AuthorizationError):
                await service.change_member(
                    AdministrativeChange(
                        update_id=update_id,
                        telegram_user_id=actor.telegram_user_id,
                        target_member_id=target.id,
                        kind=ChangeKind.STATUS,
                        requested_value=MemberStatus.PAUSED.value,
                    )
                )
            update_id += 1

    assert await scalar_count(database, AuditEventModel) == 0
    assert await scalar_count(database, ProcessedTelegramUpdateModel) == 0
    await database.dispose()


async def test_concurrent_different_changes_are_serialized_with_audit_chain(
    database_url: str,
) -> None:
    database = Database(database_url)
    actor = await add_member(
        database,
        telegram_user_id=40,
        role=MemberRole.ADMINISTRATOR,
    )
    second_actor = await add_member(
        database,
        telegram_user_id=42,
        role=MemberRole.ADMINISTRATOR,
    )
    target = await add_member(database, telegram_user_id=41)
    service = MemberFoundationService(database.unit_of_work)
    role_change = AdministrativeChange(
        update_id=401,
        telegram_user_id=actor.telegram_user_id,
        target_member_id=target.id,
        kind=ChangeKind.ROLE,
        requested_value=MemberRole.MODERATOR.value,
    )
    status_change = AdministrativeChange(
        update_id=402,
        telegram_user_id=second_actor.telegram_user_id,
        target_member_id=target.id,
        kind=ChangeKind.STATUS,
        requested_value=MemberStatus.PAUSED.value,
    )

    await asyncio.gather(service.change_member(role_change), service.change_member(status_change))

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        events = (
            await session.scalars(
                select(AuditEventModel).order_by(AuditEventModel.created_at, AuditEventModel.id)
            )
        ).all()
        persisted = await session.get(MemberModel, target.id)
    assert len(events) == 2
    assert persisted is not None
    assert persisted.role == MemberRole.MODERATOR.value
    assert persisted.status == MemberStatus.PAUSED.value
    states = [event.before_json for event in events] + [event.after_json for event in events]
    assert {state["role"] for state in states if state is not None} == {
        MemberRole.MEMBER.value,
        MemberRole.MODERATOR.value,
    }
    assert {state["status"] for state in states if state is not None} == {
        MemberStatus.ACTIVE.value,
        MemberStatus.PAUSED.value,
    }
    first, second = events
    assert first.after_json == second.before_json or second.after_json == first.before_json
    await database.dispose()


async def test_member_audit_and_receipt_survive_database_object_restart(
    database_url: str,
) -> None:
    database = Database(database_url)
    actor = await add_member(
        database,
        telegram_user_id=45,
        role=MemberRole.ADMINISTRATOR,
    )
    target = await add_member(database, telegram_user_id=46)
    change = AdministrativeChange(
        update_id=450,
        telegram_user_id=actor.telegram_user_id,
        target_member_id=target.id,
        kind=ChangeKind.STATUS,
        requested_value=MemberStatus.PAUSED.value,
    )
    await MemberFoundationService(database.unit_of_work).change_member(change)
    await database.dispose()

    restarted = Database(database_url)
    repeated = await MemberFoundationService(restarted.unit_of_work).change_member(change)

    assert repeated.outcome_code == "member_changed"
    assert await scalar_count(restarted, MemberModel) == 2
    assert await scalar_count(restarted, AuditEventModel) == 1
    assert await scalar_count(restarted, ProcessedTelegramUpdateModel) == 1
    await restarted.dispose()


async def test_database_constraints_reject_incomplete_receipt_and_audit_mutation(
    database_url: str,
) -> None:
    database = Database(database_url)
    async with AsyncSession(database.engine) as session:

        async def insert_incomplete_receipt() -> None:
            await session.execute(
                text(
                    "INSERT INTO processed_telegram_updates "
                    "(update_id, update_type) VALUES (500, 'start')"
                )
            )
            await session.commit()

        with pytest.raises(IntegrityError):
            await insert_incomplete_receipt()
        await session.rollback()
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO processed_telegram_updates "
                    "(update_id, update_type, outcome_code, processed_at) "
                    "VALUES (500, 'start', 'main_menu', NULL)"
                )
            )
        await session.rollback()

    actor = await add_member(
        database,
        telegram_user_id=50,
        role=MemberRole.ADMINISTRATOR,
    )
    target = await add_member(database, telegram_user_id=51)
    await MemberFoundationService(database.unit_of_work).change_member(
        AdministrativeChange(
            update_id=501,
            telegram_user_id=actor.telegram_user_id,
            target_member_id=target.id,
            kind=ChangeKind.STATUS,
            requested_value=MemberStatus.PAUSED.value,
        )
    )
    async with AsyncSession(database.engine) as session:
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text("UPDATE audit_events SET reason = 'tamper'"))
        await session.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text("DELETE FROM audit_events"))
        await session.rollback()
    await database.dispose()


async def test_member_constraints_uniqueness_and_utc_timestamps(database_url: str) -> None:
    database = Database(database_url)
    original = await add_member(database, telegram_user_id=55)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)

    for invalid_role, invalid_status in [
        ("owner", MemberStatus.ACTIVE.value),
        (MemberRole.MEMBER.value, "unknown"),
    ]:
        async with sessions() as session:
            session.add(
                MemberModel(
                    telegram_user_id=56,
                    display_name="Invalid member",
                    timezone="UTC",
                    role=invalid_role,
                    status=invalid_status,
                    level_number=1,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()

    async with sessions() as session:
        session.add(
            MemberModel(
                telegram_user_id=original.telegram_user_id,
                display_name="Duplicate member",
                timezone="UTC",
                role=MemberRole.MEMBER.value,
                status=MemberStatus.ACTIVE.value,
                level_number=1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    await MemberFoundationService(database.unit_of_work).process_start(
        update_id=550,
        telegram_user_id=original.telegram_user_id,
    )
    async with sessions() as session:
        persisted_member = await session.get(MemberModel, original.id)
        receipt = await session.get(ProcessedTelegramUpdateModel, 550)
    assert persisted_member is not None
    assert receipt is not None
    assert persisted_member.created_at.tzinfo is not None
    assert receipt.received_at.tzinfo is not None
    assert receipt.processed_at.tzinfo is not None
    await database.dispose()


class RecordingSession(BaseSession):
    """Fake Bot API session that verifies the receipt is already committed."""

    def __init__(self, database: Database, expected_update_id: int) -> None:
        """Record the database used to prove post-commit visibility."""
        super().__init__()
        self.database = database
        self.expected_update_id = expected_update_id
        self.calls = 0

    async def close(self) -> None:
        """Close no external resources."""

    @override
    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,
    ) -> TelegramType:
        """Record a fake call only after a committed receipt is visible."""
        del bot, method, timeout
        async with self.database.engine.connect() as connection:
            receipt = await connection.scalar(
                select(ProcessedTelegramUpdateModel.update_id).where(
                    ProcessedTelegramUpdateModel.update_id == self.expected_update_id
                )
            )
        assert receipt == self.expected_update_id
        self.calls += 1
        return cast(
            "TelegramType",
            Message(
                message_id=999,
                date=datetime.now(UTC),
                chat=Chat(id=1, type="private"),
                text="ok",
            ),
        )

    @override
    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes]:
        """Yield no content because tests perform no downloads."""
        del url, headers, timeout, chunk_size, raise_for_status
        if False:
            yield b""


async def test_synthetic_update_calls_fake_bot_only_after_commit(database_url: str) -> None:
    database = Database(database_url)
    await add_member(database, telegram_user_id=60)
    service = MemberFoundationService(database.unit_of_work)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_member_foundation_router(service))
    session = RecordingSession(database, expected_update_id=600)
    bot = Bot(token=fake_bot_token(), session=session)
    update = Update(
        update_id=600,
        message=Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=60, type="private"),
            from_user=User(id=60, is_bot=False, first_name="Test"),
            text="/start",
        ),
    )

    await dispatcher.feed_update(bot, update)
    await dispatcher.feed_update(bot, update)

    session.expected_update_id = 602
    assert update.message is not None
    refresh_update = update.model_copy(
        update={
            "update_id": 602,
            "message": update.message.model_copy(
                update={"message_id": 3, "text": REFRESH_MENU_TEXT}
            ),
        }
    )
    await dispatcher.feed_update(bot, refresh_update)

    assert session.calls == 3
    assert await scalar_count(database, ProcessedTelegramUpdateModel) == 2
    await bot.session.close()
    await database.dispose()


async def test_update_without_from_user_has_no_receipt_or_reply(database_url: str) -> None:
    database = Database(database_url)
    service = MemberFoundationService(database.unit_of_work)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_member_foundation_router(service))
    session = RecordingSession(database, expected_update_id=601)
    bot = Bot(token=fake_bot_token(), session=session)
    update = Update(
        update_id=601,
        message=Message(
            message_id=2,
            date=datetime.now(UTC),
            chat=Chat(id=60, type="private"),
            text="/start",
        ),
    )

    await dispatcher.feed_update(bot, update)

    assert session.calls == 0
    assert await scalar_count(database, ProcessedTelegramUpdateModel) == 0
    await bot.session.close()
    await database.dispose()


async def test_migration_cycle_returns_to_head(database_url: str) -> None:
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    configuration = Config("alembic.ini")
    try:
        await asyncio.to_thread(command.downgrade, configuration, "0001")
        await asyncio.to_thread(command.upgrade, configuration, "head")
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
