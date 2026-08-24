from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.economy import EconomyService, ProductConfigBootstrapCoordinator
from community_bot.application.identity import ActorContext
from community_bot.application.registration import (
    InvitationCreateCommand,
    InviteTokenCodec,
    ModerationCommand,
    RegistrationAnswerCommand,
    RegistrationService,
    RegistrationStartCommand,
)
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.domain.economy import starting_grant
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
    AuditEventModel,
    ConversationStateModel,
    InvitationModel,
    InvitationRedemptionModel,
    MemberModel,
    ProcessedTelegramUpdateModel,
    RegistrationApplicationModel,
)

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


def actor(member_id: UUID) -> ActorContext:
    return ActorContext(member_id, "telegram", datetime.now(UTC))


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
        await registration.own_profile(actor(pending.context.member_id))
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
    active_config = await ProductConfigBootstrapCoordinator(
        database.unit_of_work,
        load_product_config_candidate,
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
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
        conversation = await session.get(ConversationStateModel, target_id)
    assert target is not None
    assert target.status == MemberStatus.ACTIVE.value
    assert target.credit_balance_cached == 5
    assert target.experience_total_cached == 0
    assert target.level_config_version_id == active_config.id
    assert application is not None
    assert application.status == RegistrationApplicationStatus.APPROVED.value
    assert conversation is None
    assert len(transactions) == 1
    assert transactions[0].credit_delta == 5
    assert transactions[0].experience_delta == 0
    await database.dispose()

    restarted = Database(database_url)
    restarted_sessions = async_sessionmaker(restarted.engine, expire_on_commit=False)
    async with restarted_sessions.begin() as session:
        paused_target = await session.get(MemberModel, target_id)
        assert paused_target is not None
        paused_target.status = MemberStatus.PAUSED.value
    replay = await service(restarted).moderate(admin_approval)
    assert replay.outcome_code == "registration_approved"
    assert replay.context is not None
    assert replay.context.member_status is MemberStatus.PAUSED
    assert await count(restarted, AccountTransactionModel) == 1
    assert await count(restarted, ConversationStateModel) == 0
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
        begin_outcome = await registration.begin_profile_field_edit(
            update_id=6_204 + index * 2,
            telegram_user_id=601,
            field=field,
        )
        assert begin_outcome == f"profile_edit:{field.value}"
        assert await registration.expected_input(601) == ("profile_edit", field.value)
        save_outcome = await registration.save_profile_field(
            update_id=6_205 + index * 2,
            telegram_user_id=601,
            expected_field=field,
            raw_value=raw_value,
        )
        assert save_outcome == "profile_updated"
        assert await registration.expected_input(601) is None
    profile = await registration.own_profile(actor(target_id))

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
    assert (await registration.own_profile(actor(target_id))).display_name == "Анна Петрова"

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


async def test_migration_closes_only_stale_approved_registration_state(
    database_url: str,
) -> None:
    """Upgrade removes the old terminal row without touching evidence or profile edits."""
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=8_100,
        role=MemberRole.ADMINISTRATOR,
    )
    target = await add_member(
        database,
        telegram_user_id=8_101,
        role=MemberRole.MEMBER,
    )
    now = datetime.now(UTC)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add_all(
            (
                RegistrationApplicationModel(
                    member_id=target.id,
                    status=RegistrationApplicationStatus.APPROVED.value,
                    consented_at=now,
                    submitted_at=now,
                    reviewed_at=now,
                    reviewed_by_member_id=admin.id,
                ),
                ConversationStateModel(
                    member_id=target.id,
                    flow_type="registration_paused",
                    current_step=RegistrationStep.SUBMITTED.value,
                    payload_json={},
                ),
                ConversationStateModel(
                    member_id=admin.id,
                    flow_type="profile_edit",
                    current_step=ProfileField.CITY.value,
                    payload_json={},
                ),
            )
        )
    audit_count = await count(database, AuditEventModel)
    receipt_count = await count(database, ProcessedTelegramUpdateModel)
    await database.dispose()

    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    configuration = Config("alembic.ini")
    try:
        await asyncio.to_thread(command.downgrade, configuration, "0010")
        await asyncio.to_thread(command.upgrade, configuration, "head")
        await asyncio.to_thread(command.upgrade, configuration, "head")
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url

    repaired = Database(database_url)
    repaired_sessions = async_sessionmaker(repaired.engine, expire_on_commit=False)
    async with repaired_sessions() as session:
        stale_state = await session.get(ConversationStateModel, target.id)
        profile_edit = await session.get(ConversationStateModel, admin.id)
    assert stale_state is None
    assert profile_edit is not None
    assert profile_edit.flow_type == "profile_edit"
    assert await count(repaired, AuditEventModel) == audit_count
    assert await count(repaired, ProcessedTelegramUpdateModel) == receipt_count
    await repaired.dispose()


async def test_migration_backfills_missing_active_starting_grants(
    database_url: str,
) -> None:
    database = Database(database_url)
    active_missing = await add_member(
        database,
        telegram_user_id=8_200,
        role=MemberRole.MEMBER,
    )
    active_existing = await add_member(
        database,
        telegram_user_id=8_201,
        role=MemberRole.MEMBER,
    )
    pending_missing = await add_member(
        database,
        telegram_user_id=8_202,
        role=MemberRole.MEMBER,
        status=MemberStatus.PENDING,
    )
    await EconomyService(database.unit_of_work).apply_one(starting_grant(active_existing.id))
    await database.dispose()

    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    configuration = Config("alembic.ini")
    try:
        await asyncio.to_thread(command.downgrade, configuration, "0013")
        await asyncio.to_thread(command.upgrade, configuration, "head")
        await asyncio.to_thread(command.upgrade, configuration, "head")
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url

    repaired = Database(database_url)
    sessions = async_sessionmaker(repaired.engine, expire_on_commit=False)
    async with sessions() as session:
        active_missing_model = await session.get(MemberModel, active_missing.id)
        active_existing_model = await session.get(MemberModel, active_existing.id)
        pending_missing_model = await session.get(MemberModel, pending_missing.id)
        grant_result = await session.execute(
            select(AccountTransactionModel).where(
                AccountTransactionModel.member_id.in_(
                    (active_missing.id, active_existing.id, pending_missing.id)
                ),
                AccountTransactionModel.transaction_type == "starting_grant",
            )
        )
        grant_rows = list(grant_result.scalars().all())
    assert len(grant_rows) == 2
    grants_by_member = {item.member_id: item for item in grant_rows}
    assert active_missing_model is not None
    assert active_missing_model.credit_balance_cached == 10
    assert active_existing_model is not None
    assert active_existing_model.credit_balance_cached == 5
    assert pending_missing_model is not None
    assert pending_missing_model.credit_balance_cached == 0
    assert set(grants_by_member) == {active_missing.id, active_existing.id}
    assert grants_by_member[active_missing.id].credit_delta == 10
    assert grants_by_member[active_missing.id].idempotency_key == (
        f"starting_grant:{active_missing.id}"
    )
    legacy_payload = {
        "schema_version": 1,
        "transaction_type": "starting_grant",
        "member_id": str(active_missing.id),
        "credit_delta": 10,
        "experience_delta": 0,
        "actor_member_id": None,
        "reason": None,
        "comment": None,
        "reversed_transaction_id": None,
    }
    assert (
        grants_by_member[active_missing.id].payload_hash
        == hashlib.sha256(
            json.dumps(
                legacy_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )
    await repaired.dispose()


async def test_migration_backfills_stale_active_member_level_config(
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=8_300,
        role=MemberRole.ADMINISTRATOR,
    )
    active_config = await ProductConfigBootstrapCoordinator(
        database.unit_of_work,
        load_product_config_candidate,
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    stale_active = await add_member(
        database,
        telegram_user_id=8_301,
        role=MemberRole.MEMBER,
    )
    pending = await add_member(
        database,
        telegram_user_id=8_302,
        role=MemberRole.MEMBER,
        status=MemberStatus.PENDING,
    )
    await database.dispose()

    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    configuration = Config("alembic.ini")
    try:
        await asyncio.to_thread(command.downgrade, configuration, "0014")
        await asyncio.to_thread(command.upgrade, configuration, "head")
        await asyncio.to_thread(command.upgrade, configuration, "head")
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url

    repaired = Database(database_url)
    sessions = async_sessionmaker(repaired.engine, expire_on_commit=False)
    async with sessions() as session:
        stale_active_model = await session.get(MemberModel, stale_active.id)
        pending_model = await session.get(MemberModel, pending.id)
    assert stale_active_model is not None
    assert stale_active_model.level_number == 1
    assert stale_active_model.level_config_version_id == active_config.id
    assert pending_model is not None
    assert pending_model.level_config_version_id is None
    await repaired.dispose()
