from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast, override
from uuid import UUID, uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.economy import ProductConfigBootstrapCoordinator
from community_bot.application.registration import (
    InvitationCreateCommand,
    InviteTokenCodec,
    ModerationCommand,
    RegistrationAnswerCommand,
    RegistrationService,
    RegistrationStartCommand,
)
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.domain.members import MemberRole, MemberStatus
from community_bot.domain.registration import (
    InvitationError,
    ModerationDecision,
    ProfileField,
    RegistrationApplicationStatus,
    RegistrationStep,
)
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    InvitationModel,
    InvitationRedemptionModel,
    MemberModel,
    ProcessedTelegramUpdateModel,
    RegistrationApplicationModel,
)
from community_bot.transport.telegram.registration import build_registration_router

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from aiogram.methods import TelegramMethod

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

CONFIG_PATH = Path(__file__).parents[2] / "config" / "product-config.v1.json"
TEST_TOKEN_KEY = "x" * 32
TelegramType = TypeVar("TelegramType")


async def add_member(
    database: Database,
    *,
    telegram_user_id: int,
    role: MemberRole,
    status: MemberStatus = MemberStatus.ACTIVE,
) -> MemberModel:
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        model = MemberModel(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            display_name=f"Member {telegram_user_id}",
            timezone="UTC",
            role=role.value,
            status=status.value,
            level_number=1,
        )
        session.add(model)
    return model


async def count(database: Database, model: type[object]) -> int:
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        value = await session.scalar(select(func.count()).select_from(model))
    assert value is not None
    return value


def service(database: Database) -> RegistrationService:
    return RegistrationService(database.unit_of_work, InviteTokenCodec(TEST_TOKEN_KEY))


async def create_invite(
    registration: RegistrationService,
    admin: MemberModel,
    *,
    update_id: int,
    max_uses: int = 1,
) -> str:
    result = await registration.create_invitation(
        InvitationCreateCommand(
            update_id=update_id,
            actor_telegram_user_id=admin.telegram_user_id,
            max_uses=max_uses,
        )
    )
    return result.token


async def complete_registration(
    registration: RegistrationService,
    *,
    token: str,
    telegram_user_id: int,
    first_update_id: int,
) -> UUID:
    view = await registration.start(
        RegistrationStartCommand(
            update_id=first_update_id,
            telegram_user_id=telegram_user_id,
            telegram_username="first_name",
            telegram_display_name="First Name",
            invitation_token=token,
        )
    )
    assert view.context is not None
    answers = [
        (RegistrationStep.CONSENT, "да"),
        (RegistrationStep.DISPLAY_NAME, "Анна"),
        (RegistrationStep.CITY, "Москва"),
        (RegistrationStep.SHORT_BIO, "Помогаю тестировать цифровые продукты"),
        (RegistrationStep.CURRENT_GOAL, "Найти полезные задачи"),
        (RegistrationStep.HELP_CATEGORIES, "Тестирование, Продукт"),
        (RegistrationStep.SKILL_TAGS, "Python, Исследования"),
        (RegistrationStep.AVAILABILITY, "Два часа в неделю"),
    ]
    for offset, (step, raw_value) in enumerate(answers, start=1):
        view = await registration.answer(
            RegistrationAnswerCommand(
                update_id=first_update_id + offset,
                telegram_user_id=telegram_user_id,
                expected_step=step,
                raw_value=raw_value,
            )
        )
    assert view.context is not None
    assert view.context.current_step is RegistrationStep.PREVIEW
    submitted = await registration.submit(
        update_id=first_update_id + 20,
        telegram_user_id=telegram_user_id,
    )
    assert submitted.context is not None
    assert submitted.context.application_status is RegistrationApplicationStatus.SUBMITTED
    return submitted.context.member_id


async def test_invitation_is_hashed_and_concurrent_last_use_is_atomic(
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=100,
        role=MemberRole.ADMINISTRATOR,
    )
    registration = service(database)
    token = await create_invite(registration, admin, update_id=1_000)

    async def start(user_id: int, update_id: int) -> object:
        return await registration.start(
            RegistrationStartCommand(
                update_id=update_id,
                telegram_user_id=user_id,
                telegram_username=f"user_{user_id}",
                telegram_display_name=f"User {user_id}",
                invitation_token=token,
            )
        )

    results = await asyncio.gather(
        start(101, 1_001),
        start(102, 1_002),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, InvitationError) for result in results) == 1
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        invitation = await session.scalar(select(InvitationModel))
    assert invitation is not None
    assert invitation.code_hash != token
    assert token not in invitation.code_hash
    assert invitation.uses_count == 1
    assert await count(database, InvitationRedemptionModel) == 1
    await database.dispose()


async def test_existing_timezone_step_accepts_human_city_name(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=150,
        role=MemberRole.ADMINISTRATOR,
    )
    registration = service(database)
    token = await create_invite(registration, admin, update_id=1_500)
    await registration.start(
        RegistrationStartCommand(
            update_id=1_501,
            telegram_user_id=151,
            telegram_username="existing_draft",
            telegram_display_name="Existing Draft",
            invitation_token=token,
        )
    )
    await registration.answer(
        RegistrationAnswerCommand(
            update_id=1_502,
            telegram_user_id=151,
            expected_step=RegistrationStep.CONSENT,
            raw_value="да",
        )
    )
    await registration.answer(
        RegistrationAnswerCommand(
            update_id=1_503,
            telegram_user_id=151,
            expected_step=RegistrationStep.DISPLAY_NAME,
            raw_value="Андрей",
        )
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(build_registration_router(registration))
    session = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=session)
    user = User(id=151, is_bot=False, first_name="Andrey", username="existing_draft")
    await dispatcher.feed_update(
        bot,
        Update(
            update_id=1_504,
            message=Message(
                message_id=1_504,
                date=datetime.now(UTC),
                chat=Chat(id=user.id, type="private"),
                from_user=user,
                text="Неизвестный небольшой город",
            ),
        ),
    )
    city_view = await registration.answer(
        RegistrationAnswerCommand(
            update_id=1_504,
            telegram_user_id=151,
            expected_step=RegistrationStep.CITY,
            raw_value="Неизвестный небольшой город",
        )
    )
    assert city_view.context is not None
    assert city_view.context.current_step is RegistrationStep.TIMEZONE
    assert any("ближайший крупный город" in text_value for text_value in session.texts)
    await dispatcher.feed_update(
        bot,
        Update(
            update_id=1_505,
            message=Message(
                message_id=1_505,
                date=datetime.now(UTC),
                chat=Chat(id=user.id, type="private"),
                from_user=user,
                text="Buenos Aires",
            ),
        ),
    )
    timezone_view = await registration.answer(
        RegistrationAnswerCommand(
            update_id=1_505,
            telegram_user_id=151,
            expected_step=RegistrationStep.TIMEZONE,
            raw_value="Buenos Aires",
        )
    )

    assert timezone_view.context is not None
    assert timezone_view.context.current_step is RegistrationStep.SHORT_BIO
    assert timezone_view.context.payload["timezone"] == "America/Argentina/Buenos_Aires"
    assert any("Коротко расскажите" in text_value for text_value in session.texts)
    assert not any(
        "Не удалось сохранить" in text_value  # noqa: RUF001 - exact Russian error text.
        for text_value in session.texts
    )
    await bot.session.close()
    await database.dispose()


async def test_invitation_replay_revoke_and_pending_access_rules(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=150,
        role=MemberRole.ADMINISTRATOR,
    )
    moderator = await add_member(
        database,
        telegram_user_id=151,
        role=MemberRole.MODERATOR,
    )
    registration = service(database)
    create_command = InvitationCreateCommand(
        update_id=1_500,
        actor_telegram_user_id=admin.telegram_user_id,
        max_uses=2,
        intended_telegram_user_id=152,
    )
    first = await registration.create_invitation(create_command)
    replay = await registration.create_invitation(create_command)
    assert replay.replayed
    assert replay.invitation_id == first.invitation_id
    assert replay.token == first.token
    with pytest.raises(PermissionError):
        await registration.create_invitation(
            InvitationCreateCommand(
                update_id=1_501,
                actor_telegram_user_id=moderator.telegram_user_id,
            )
        )
    with pytest.raises(InvitationError):
        await registration.start(
            RegistrationStartCommand(
                update_id=1_502,
                telegram_user_id=999,
                telegram_username=None,
                telegram_display_name="Wrong User",
                invitation_token=first.token,
            )
        )
    pending = await registration.start(
        RegistrationStartCommand(
            update_id=1_503,
            telegram_user_id=152,
            telegram_username=None,
            telegram_display_name="Pending User",
            invitation_token=first.token,
        )
    )
    assert pending.context is not None
    with pytest.raises(PermissionError):
        await registration.own_profile(152)
    await registration.revoke_invitation(
        update_id=1_504,
        actor_telegram_user_id=admin.telegram_user_id,
        invitation_id=first.invitation_id,
    )
    with pytest.raises(InvitationError):
        await registration.start(
            RegistrationStartCommand(
                update_id=1_505,
                telegram_user_id=153,
                telegram_username=None,
                telegram_display_name="Revoked User",
                invitation_token=first.token,
            )
        )

    expiring = await registration.create_invitation(
        InvitationCreateCommand(
            update_id=1_506,
            actor_telegram_user_id=admin.telegram_user_id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        invitation = await session.get(InvitationModel, expiring.invitation_id)
        assert invitation is not None
        invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(InvitationError, match="expired"):
        await registration.start(
            RegistrationStartCommand(
                update_id=1_507,
                telegram_user_id=154,
                telegram_username=None,
                telegram_display_name="Expired User",
                invitation_token=expiring.token,
            )
        )
    await database.dispose()


async def test_different_concurrent_starts_for_same_identity_create_one_member(
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=200,
        role=MemberRole.ADMINISTRATOR,
    )
    registration = service(database)
    token = await create_invite(registration, admin, update_id=2_000)
    commands = [
        RegistrationStartCommand(
            update_id=2_001 + index,
            telegram_user_id=201,
            telegram_username=f"same_{index}",
            telegram_display_name="Same Person",
            invitation_token=token,
        )
        for index in range(2)
    ]

    views = await asyncio.gather(*(registration.start(command) for command in commands))

    assert len({view.context.member_id for view in views if view.context is not None}) == 1
    assert await count(database, InvitationRedemptionModel) == 1
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        members = (
            await session.scalars(select(MemberModel).where(MemberModel.telegram_user_id == 201))
        ).all()
    assert len(members) == 1
    await database.dispose()


async def test_restart_resumes_step_and_username_change_keeps_member_identity(
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=300,
        role=MemberRole.ADMINISTRATOR,
    )
    registration = service(database)
    token = await create_invite(registration, admin, update_id=3_000)
    start_command = RegistrationStartCommand(
        update_id=3_001,
        telegram_user_id=301,
        telegram_username="old_name",
        telegram_display_name="Restart Person",
        invitation_token=token,
    )
    started = await registration.start(start_command)
    exact_replay = await registration.start(start_command)
    assert exact_replay.outcome_code == started.outcome_code
    assert exact_replay.context == started.context
    consented = await registration.answer(
        RegistrationAnswerCommand(
            update_id=3_002,
            telegram_user_id=301,
            expected_step=RegistrationStep.CONSENT,
            raw_value="да",
        )
    )
    assert consented.context is not None
    member_id = consented.context.member_id
    assert await registration.cancel(update_id=3_004, telegram_user_id=301) == (
        "conversation_cancelled"
    )
    assert await registration.cancel(update_id=3_004, telegram_user_id=301) == (
        "conversation_cancelled"
    )
    assert await registration.expected_input(301) is None
    paused_answer = await registration.answer(
        RegistrationAnswerCommand(
            update_id=3_005,
            telegram_user_id=301,
            expected_step=RegistrationStep.DISPLAY_NAME,
            raw_value="Это значение не должно сохраниться",
        )
    )
    assert paused_answer.outcome_code == "conversation_paused"
    assert paused_answer.context is not None
    assert "display_name" not in paused_answer.context.payload
    await database.dispose()

    restarted = Database(database_url)
    resumed = await service(restarted).start(
        RegistrationStartCommand(
            update_id=3_003,
            telegram_user_id=301,
            telegram_username="new_name",
            telegram_display_name="Restart Person",
        )
    )

    assert resumed.context is not None
    assert resumed.context.member_id == member_id
    assert resumed.context.current_step is RegistrationStep.DISPLAY_NAME
    assert resumed.context.telegram_username == "new_name"
    assert await service(restarted).expected_input(301) == ("registration", "display_name")
    assert await count(restarted, InvitationRedemptionModel) == 1
    await restarted.dispose()


async def test_stale_expected_step_does_not_pollute_next_answer(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=400,
        role=MemberRole.ADMINISTRATOR,
    )
    registration = service(database)
    token = await create_invite(registration, admin, update_id=4_000)
    await registration.start(
        RegistrationStartCommand(
            update_id=4_001,
            telegram_user_id=401,
            telegram_username=None,
            telegram_display_name="Stale Person",
            invitation_token=token,
        )
    )
    commands = [
        RegistrationAnswerCommand(
            update_id=4_002 + index,
            telegram_user_id=401,
            expected_step=RegistrationStep.CONSENT,
            raw_value="да",
        )
        for index in range(2)
    ]

    results = await asyncio.gather(*(registration.answer(command) for command in commands))

    assert {result.outcome_code for result in results} == {
        "registration_step:display_name",
        "stale_step:display_name",
    }
    context = results[0].context
    assert context is not None
    assert context.current_step is RegistrationStep.DISPLAY_NAME
    assert "display_name" not in context.payload
    await database.dispose()


async def test_concurrent_moderation_creates_one_grant_and_active_profile(
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=500,
        role=MemberRole.ADMINISTRATOR,
    )
    moderator = await add_member(
        database,
        telegram_user_id=501,
        role=MemberRole.MODERATOR,
    )
    ordinary_member = await add_member(
        database,
        telegram_user_id=503,
        role=MemberRole.MEMBER,
    )
    registration = service(database)
    token = await create_invite(registration, admin, update_id=5_000)
    target_id = await complete_registration(
        registration,
        token=token,
        telegram_user_id=502,
        first_update_id=5_100,
    )

    transactions_before = await count(database, AccountTransactionModel)
    receipts_before = await count(database, ProcessedTelegramUpdateModel)
    with pytest.raises(PermissionError):
        await registration.moderate(
            ModerationCommand(
                update_id=5_190,
                actor_telegram_user_id=ordinary_member.telegram_user_id,
                target_member_id=target_id,
                decision=ModerationDecision.APPROVE,
            )
        )
    with pytest.raises(LookupError):
        await registration.moderate(
            ModerationCommand(
                update_id=5_191,
                actor_telegram_user_id=admin.telegram_user_id,
                target_member_id=uuid4(),
                decision=ModerationDecision.APPROVE,
            )
        )
    assert await count(database, AccountTransactionModel) == transactions_before
    assert await count(database, ProcessedTelegramUpdateModel) == receipts_before

    admin_approval = ModerationCommand(
        update_id=5_200,
        actor_telegram_user_id=admin.telegram_user_id,
        target_member_id=target_id,
        decision=ModerationDecision.APPROVE,
    )
    results = await asyncio.gather(
        registration.moderate(admin_approval),
        registration.moderate(
            ModerationCommand(
                update_id=5_201,
                actor_telegram_user_id=moderator.telegram_user_id,
                target_member_id=target_id,
                decision=ModerationDecision.APPROVE,
            )
        ),
    )

    assert {result.outcome_code for result in results} == {"registration_approved"}
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        target = await session.get(MemberModel, target_id)
        transactions = (
            await session.scalars(
                select(AccountTransactionModel).where(
                    AccountTransactionModel.member_id == target_id
                )
            )
        ).all()
        application = await session.get(RegistrationApplicationModel, target_id)
    assert target is not None
    assert target.status == MemberStatus.ACTIVE.value
    assert target.credit_balance_cached == 5
    assert target.experience_total_cached == 0
    assert application is not None
    assert application.status == RegistrationApplicationStatus.APPROVED.value
    assert len(transactions) == 1
    assert transactions[0].credit_delta == 5
    assert transactions[0].experience_delta == 0
    await database.dispose()

    restarted = Database(database_url)
    replay = await service(restarted).moderate(admin_approval)
    assert replay.outcome_code == "registration_approved"
    assert await count(restarted, AccountTransactionModel) == 1
    await restarted.dispose()


async def test_reject_resubmit_approve_and_edit_own_profile(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=600,
        role=MemberRole.ADMINISTRATOR,
    )
    registration = service(database)
    token = await create_invite(registration, admin, update_id=6_000)
    target_id = await complete_registration(
        registration,
        token=token,
        telegram_user_id=601,
        first_update_id=6_100,
    )
    rejected = await registration.moderate(
        ModerationCommand(
            update_id=6_200,
            actor_telegram_user_id=admin.telegram_user_id,
            target_member_id=target_id,
            decision=ModerationDecision.REJECT,
            comment="Уточните описание опыта.",
        )
    )
    assert rejected.context is not None
    assert rejected.context.application_status is RegistrationApplicationStatus.REJECTED
    assert await count(database, AccountTransactionModel) == 0

    await registration.reopen_rejected(update_id=6_201, telegram_user_id=601)
    await registration.submit(update_id=6_202, telegram_user_id=601)
    await registration.moderate(
        ModerationCommand(
            update_id=6_203,
            actor_telegram_user_id=admin.telegram_user_id,
            target_member_id=target_id,
            decision=ModerationDecision.APPROVE,
        )
    )
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work,
        load_product_config_candidate,
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    edits = {
        ProfileField.DISPLAY_NAME: "Анна Петрова",
        ProfileField.CITY: "Казань",
        ProfileField.TIMEZONE: "Asia/Yekaterinburg",
        ProfileField.SHORT_BIO: "Создаю полезные продукты для сообществ",
        ProfileField.CURRENT_GOAL: "Запустить совместный проект",
        ProfileField.HELP_CATEGORIES: "Продукт, Исследования",
        ProfileField.SKILL_TAGS: "Python, Интервью",
        ProfileField.AVAILABILITY: "Три часа в неделю",
    }
    for index, (field, raw_value) in enumerate(edits.items()):
        await registration.begin_profile_field_edit(
            update_id=6_204 + index * 2,
            telegram_user_id=601,
            field=field,
        )
        await registration.save_profile_field(
            update_id=6_205 + index * 2,
            telegram_user_id=601,
            expected_field=field,
            raw_value=raw_value,
        )
    profile = await registration.own_profile(601)

    assert profile.member_id == target_id
    assert profile.display_name == "Анна Петрова"
    assert profile.city == "Казань"
    assert profile.timezone == "Asia/Yekaterinburg"
    assert profile.short_bio == "Создаю полезные продукты для сообществ"
    assert profile.current_goal == "Запустить совместный проект"
    assert profile.help_categories == ("Продукт", "Исследования")
    assert profile.skill_tags == ("Python", "Интервью")
    assert profile.availability == "Три часа в неделю"
    assert profile.credit_balance == 5
    assert profile.experience_total == 0
    assert profile.level.level_number == 1
    assert await count(database, AccountTransactionModel) == 1

    other = await add_member(
        database,
        telegram_user_id=602,
        role=MemberRole.MEMBER,
    )
    await registration.begin_profile_field_edit(
        update_id=6_230,
        telegram_user_id=other.telegram_user_id,
        field=ProfileField.DISPLAY_NAME,
    )
    await registration.save_profile_field(
        update_id=6_231,
        telegram_user_id=other.telegram_user_id,
        expected_field=ProfileField.DISPLAY_NAME,
        raw_value="Другой участник",
    )
    assert (await registration.own_profile(601)).display_name == "Анна Петрова"

    inactive = await add_member(
        database,
        telegram_user_id=603,
        role=MemberRole.MEMBER,
        status=MemberStatus.PAUSED,
    )
    with pytest.raises(PermissionError):
        await registration.begin_profile_field_edit(
            update_id=6_232,
            telegram_user_id=inactive.telegram_user_id,
            field=ProfileField.DISPLAY_NAME,
        )
    await database.dispose()


async def test_fault_after_grant_flush_rolls_back_full_approval(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=700,
        role=MemberRole.ADMINISTRATOR,
    )
    normal_service = service(database)
    token = await create_invite(normal_service, admin, update_id=7_000)
    target_id = await complete_registration(
        normal_service,
        token=token,
        telegram_user_id=701,
        first_update_id=7_100,
    )

    def fail_after_ledger() -> None:
        message = "Injected registration approval failure"
        raise RuntimeError(message)

    failing_service = RegistrationService(
        lambda: database.unit_of_work(after_ledger_flushed=fail_after_ledger),
        InviteTokenCodec(TEST_TOKEN_KEY),
    )
    command = ModerationCommand(
        update_id=7_200,
        actor_telegram_user_id=admin.telegram_user_id,
        target_member_id=target_id,
        decision=ModerationDecision.APPROVE,
    )
    with pytest.raises(RuntimeError, match="Injected registration approval failure"):
        await failing_service.moderate(command)

    assert await count(database, AccountTransactionModel) == 0
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        target = await session.get(MemberModel, target_id)
        application = await session.get(RegistrationApplicationModel, target_id)
        receipt = await session.get(ProcessedTelegramUpdateModel, command.update_id)
    assert target is not None
    assert target.status == MemberStatus.PENDING.value
    assert application is not None
    assert application.status == RegistrationApplicationStatus.SUBMITTED.value
    assert receipt is None

    await normal_service.moderate(command)
    assert await count(database, AccountTransactionModel) == 1
    await database.dispose()


class CapturingSession(BaseSession):
    """Fake Bot API session used by the complete synthetic Telegram scenario."""

    def __init__(self) -> None:
        """Initialize an empty collection of outgoing user-facing texts."""
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
        if isinstance(method, AnswerCallbackQuery):
            return cast("TelegramType", True)  # noqa: FBT003 - Bot API success payload.
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


async def test_complete_synthetic_telegram_registration_and_profile_smoke(
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=800,
        role=MemberRole.ADMINISTRATOR,
    )
    registration = service(database)
    token = await create_invite(registration, admin, update_id=8_000)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_registration_router(registration))
    session = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=session)
    user = User(id=801, is_bot=False, first_name="Anna", username="anna")
    admin_user = User(id=admin.telegram_user_id, is_bot=False, first_name="Admin")

    def message_update(update_id: int, actor: User, text_value: str) -> Update:
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

    def callback_update(
        update_id: int,
        actor: User,
        data: str,
    ) -> Update:
        return Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=str(update_id),
                from_user=actor,
                chat_instance="test",
                data=data,
                message=Message(
                    message_id=update_id,
                    date=datetime.now(UTC),
                    chat=Chat(id=actor.id, type="private"),
                    from_user=actor,
                    text="button",
                ),
            ),
        )

    await dispatcher.feed_update(bot, message_update(8_001, user, f"/start {token}"))
    await dispatcher.feed_update(
        bot,
        callback_update(8_002, user, "registration:consent"),
    )
    await dispatcher.feed_update(bot, message_update(8_003, user, "/cancel"))
    assert await registration.expected_input(user.id) is None
    await dispatcher.feed_update(bot, message_update(8_004, user, "ignored value"))
    await dispatcher.feed_update(bot, message_update(8_005, user, "/start"))
    assert await registration.expected_input(user.id) == ("registration", "display_name")
    answers = [
        "Анна",
        "Buenos Aires",
        "Помогаю тестировать цифровые продукты",
        "Найти полезные задачи",
        "Тестирование, Продукт",
        "Python, Исследования",
        "Два часа в неделю",
    ]
    for offset, answer in enumerate(answers, start=10):
        await dispatcher.feed_update(bot, message_update(8_000 + offset, user, answer))
    await dispatcher.feed_update(
        bot,
        callback_update(8_020, user, "registration:submit"),
    )
    queue = await registration.submitted_registrations(
        actor_telegram_user_id=admin.telegram_user_id
    )
    assert len(queue) == 1
    assert queue[0].payload["city"] == "Buenos Aires"
    assert queue[0].payload["timezone"] == "America/Argentina/Buenos_Aires"
    target_id = queue[0].member_id
    await dispatcher.feed_update(
        bot,
        callback_update(8_021, admin_user, f"registration:approve:{target_id}"),
    )
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work,
        load_product_config_candidate,
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    await dispatcher.feed_update(bot, message_update(8_022, user, "/profile"))

    assert any("Проверьте анкету" in text_value for text_value in session.texts)
    assert any(
        "Коротко расскажите о себе" in text_value  # noqa: RUF001 - exact Russian prompt.
        for text_value in session.texts
    )
    assert not any("Europe/Moscow" in text_value for text_value in session.texts)
    assert any("Баланс: 5 кредитов" in text_value for text_value in session.texts)
    assert await count(database, AccountTransactionModel) == 1
    await bot.session.close()
    await database.dispose()


async def test_registration_migration_cycle_returns_to_head(database_url: str) -> None:
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    configuration = Config("alembic.ini")
    try:
        await asyncio.to_thread(command.downgrade, configuration, "0003")
        await asyncio.to_thread(command.upgrade, configuration, "head")
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
