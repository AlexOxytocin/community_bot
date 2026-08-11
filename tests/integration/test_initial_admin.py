from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar, cast, override
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.types import Chat, Message, Update, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.initial_admin import (
    InitialAdministratorCommand,
    InitialAdministratorConflictError,
    InitialAdministratorReason,
    InitialAdministratorService,
)
from community_bot.bootstrap.bot import _dispatcher
from community_bot.bootstrap.initial_admin import main as bootstrap_main
from community_bot.bootstrap.settings import get_settings
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AuditEventModel,
    InvitationModel,
    MemberModel,
    ProcessedTelegramUpdateModel,
    RegistrationApplicationModel,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from aiogram.methods import TelegramMethod

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

TelegramType = TypeVar("TelegramType")
_TOKEN_SECRET = "x" * 32


class CapturingSession(BaseSession):
    """Fake Bot API that captures only outgoing text."""

    def __init__(self) -> None:
        """Initialize an empty response list."""
        super().__init__()
        self.texts: list[str] = []

    async def close(self) -> None:
        """Close no external resources."""

    @override
    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,
    ) -> TelegramType:
        del bot, timeout
        text_value = getattr(method, "text", None)
        if isinstance(text_value, str):
            self.texts.append(text_value)
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
        del url, headers, timeout, chunk_size, raise_for_status
        if False:
            yield b""


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


async def test_real_cli_then_production_dispatcher_creates_invitation_and_registration(  # noqa: PLR0915
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        exit_code = await asyncio.to_thread(
            bootstrap_main,
            ["--telegram-user-id", "5001", "--reason", "initial_install"],
        )
    finally:
        get_settings.cache_clear()
    assert exit_code == 0

    database = Database(database_url)
    dispatcher = _dispatcher(database, invite_token_secret=_TOKEN_SECRET)
    session = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=session)
    administrator = User(id=5_001, is_bot=False, first_name="Admin")
    newcomer = User(id=5_002, is_bot=False, first_name="Newcomer")

    def update(update_id: int, actor: User, text_value: str) -> Update:
        return Update(
            update_id=update_id,
            message=Message(
                message_id=update_id,
                date=datetime.now(UTC),
                chat=Chat(id=actor.id, type="private"),
                from_user=actor,
                text=text_value,
            ),
        )

    await dispatcher.feed_update(bot, update(50_001, administrator, "/invite_create 1 7 5002"))
    response = next(text_value for text_value in session.texts if "/start " in text_value)
    match = re.search(r"/start ([A-Za-z0-9_-]+)", response)
    assert match is not None
    token = match.group(1)
    await dispatcher.feed_update(bot, update(50_002, newcomer, f"/start {token}"))

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as db_session:
        members = (
            await db_session.scalars(select(MemberModel).order_by(MemberModel.telegram_user_id))
        ).all()
        invitation = await db_session.scalar(select(InvitationModel))
        application = await db_session.scalar(select(RegistrationApplicationModel))
        receipts = (
            await db_session.scalars(
                select(ProcessedTelegramUpdateModel).order_by(
                    ProcessedTelegramUpdateModel.update_id
                )
            )
        ).all()
        bootstrap_audit = await db_session.scalar(
            select(AuditEventModel).where(
                AuditEventModel.action == "initial_administrator_bootstrapped"
            )
        )
        ledger_count = await db_session.scalar(
            select(func.count()).select_from(AccountTransactionModel)
        )

    assert [(member.telegram_user_id, member.role, member.status) for member in members] == [
        (5_001, "administrator", "active"),
        (5_002, "member", "pending"),
    ]
    admin = members[0]
    assert admin.display_name == "Administrator"
    assert admin.timezone == "UTC"
    assert admin.approved_at is not None
    assert admin.permissions_json == ["interaction_review", "karma_review", "member_read"]
    assert admin.credit_balance_cached == 0
    assert admin.experience_total_cached == 0
    assert invitation is not None
    assert invitation.code_hash != token
    assert token not in invitation.code_hash
    assert invitation.max_uses == 1
    assert invitation.uses_count == 1
    assert application is not None
    assert application.status == "draft"
    assert [receipt.update_id for receipt in receipts] == [50_001, 50_002]
    assert bootstrap_audit is not None
    assert bootstrap_audit.actor_member_id is None
    assert bootstrap_audit.reason == "initial_install"
    assert bootstrap_audit.before_json is None
    assert bootstrap_audit.after_json == {
        "permissions": ["interaction_review", "karma_review", "member_read"],
        "role": "administrator",
        "status": "active",
    }
    serialized_audit = str(
        {
            "entity_id": bootstrap_audit.entity_id,
            "after": bootstrap_audit.after_json,
            "reason": bootstrap_audit.reason,
        }
    )
    assert "5001" not in serialized_audit
    assert token not in serialized_audit
    assert ledger_count == 0
    await bot.session.close()
    await database.dispose()
