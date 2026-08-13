"""Long output-driven Telegram journeys for the complete assignment exchange."""

from __future__ import annotations

import asyncio
import datetime
import os
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.assignments import (
    AcceptAssignmentCommand,
    AssignmentDeadlineWorker,
    AssignmentService,
    DecideAssignmentCommand,
    SubmitResultCommand,
)
from community_bot.application.economy import EconomyService, ProductConfigBootstrapCoordinator
from community_bot.application.tasks import AdvanceDraftCommand, PublishTaskCommand, TaskService
from community_bot.bootstrap.bot import _dispatcher
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.domain.assignments import AssignmentDecision
from community_bot.domain.catalog import TaskFormat
from community_bot.domain.economy import starting_grant
from community_bot.domain.members import MemberRole
from community_bot.domain.tasks import TaskDraftStep
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.db.assignment_deadlines import PostgresAssignmentDeadlineSource
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AssignmentModel,
    AuditEventModel,
    InteractionAlertModel,
    KarmaVoteModel,
    KarmaVoteModerationModel,
    MemberModel,
    MemberSanctionModel,
    ModerationCaseModel,
    OutboxEventModel,
    ProcessedTelegramUpdateModel,
    TaskModel,
    TaskTemplateModel,
)
from community_bot.transport.telegram.navigation import (
    ADMIN_TEXT,
    CREATE_TASK_TEXT,
    FIND_TASK_TEXT,
    MEMBERS_TEXT,
    MY_TASKS_TEXT,
)
from tests.integration.test_navigation import (
    CONFIG_PATH,
    CapturingSession,
    _member,
    _published_task,
)
from tests.integration.test_reputation import add_paid_interaction

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
MessageSender = Callable[[int, int, str], Awaitable[None]]
CallbackSender = Callable[[int, int, str], Awaitable[None]]


async def test_member_journey_uses_only_visible_outputs(database_url: str) -> None:  # noqa: PLR0915
    """Accept, submit, review, and create without a user-supplied technical value."""
    database = Database(database_url)
    admin = await _member(database, 81_001, MemberRole.ADMINISTRATOR)
    author = await _member(database, 81_002)
    performer = await _member(database, 81_003)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    economy = EconomyService(database.unit_of_work)
    await economy.apply_one(starting_grant(author.id))
    await economy.apply_one(starting_grant(performer.id))
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        template_id = await session.scalar(
            select(TaskTemplateModel.id).where(
                TaskTemplateModel.code == "repository_first_impression"
            )
        )
    assert template_id is not None
    published = await _published_task(database, author, template_id)
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    actors = _actors(author.telegram_user_id, performer.telegram_user_id)
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    send_message, send_callback = _transport(dispatcher, bot, actors)

    capture.callbacks.clear()
    await send_message(81_100, performer.telegram_user_id, FIND_TASK_TEXT)
    accept = _visible(capture, lambda value: value.startswith("task:accept:"))
    capture.callbacks.clear()
    await send_callback(81_101, performer.telegram_user_id, accept)
    submit = _visible(capture, lambda value: value.startswith("as:a:s:"))

    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    send_message, send_callback = _transport(dispatcher, bot, actors)
    capture.callbacks.clear()
    await send_message(81_102, performer.telegram_user_id, MY_TASKS_TEXT)
    resumed_submit = _visible(capture, lambda value: value.startswith("as:a:s:"))
    assert resumed_submit == submit
    capture.callbacks.clear()
    await send_callback(81_103, performer.telegram_user_id, resumed_submit)
    assert not capture.callbacks
    await send_message(
        81_104,
        performer.telegram_user_id,
        "Проверил репозиторий и подготовил подробный полезный результат.",
    )
    confirm = _visible(capture, lambda value: value.startswith("assign:submit:"))
    capture.callbacks.clear()
    await send_callback(81_105, performer.telegram_user_id, confirm)

    capture.callbacks.clear()
    await send_message(81_106, author.telegram_user_id, MY_TASKS_TEXT)
    review = _visible(capture, lambda value: value.endswith(":partial"))
    capture.callbacks.clear()
    await send_callback(81_107, author.telegram_user_id, review)

    capture.callbacks.clear()
    await send_message(81_108, performer.telegram_user_id, CREATE_TASK_TEXT)
    template = _visible(capture, lambda value: value.startswith("nav:create:"))
    capture.callbacks.clear()
    await send_callback(81_109, performer.telegram_user_id, template)
    await send_message(
        81_110,
        performer.telegram_user_id,
        "Нужно внимательно посмотреть материал и дать практичную обратную связь.",
    )
    await _click(capture, send_callback, 81_111, performer.telegram_user_id, "task:step:days:")
    await _click(capture, send_callback, 81_112, performer.telegram_user_id, "task:step:online")
    capture.callbacks.clear()
    await send_message(81_113, performer.telegram_user_id, "Ссылка будет в описании задания.")
    await _click(capture, send_callback, 81_114, performer.telegram_user_id, "task:step:slots:")
    await _click(capture, send_callback, 81_115, performer.telegram_user_id, "task:step:preview")
    publish = _visible(capture, lambda value: value.startswith("task:pub:"))
    await send_callback(81_116, performer.telegram_user_id, publish)

    async with sessions() as session:
        assignment = await session.scalar(
            select(AssignmentModel).where(AssignmentModel.task_id == published.id)
        )
        assert assignment is not None
        reward_count = await session.scalar(
            select(func.count())
            .select_from(AccountTransactionModel)
            .where(
                AccountTransactionModel.assignment_id == assignment.id,
                AccountTransactionModel.transaction_type == "partial_task_reward",
            )
        )
        created_count = await session.scalar(
            select(func.count())
            .select_from(TaskModel)
            .where(TaskModel.creator_id == performer.id, TaskModel.status == "published")
        )
    assert assignment is not None
    assert assignment.status == "partially_approved"
    assert reward_count == 1
    assert created_count == 1
    assert all(len(value.encode()) <= 64 for value in capture.callbacks)
    await bot.session.close()
    await database.dispose()


async def test_task_details_are_visible_in_preview_catalog_and_acceptance(  # noqa: PLR0915
    database_url: str,
) -> None:
    """Keep author input and materials visible across the Telegram task journey."""
    database = Database(database_url)
    admin = await _member(database, 81_201, MemberRole.ADMINISTRATOR)
    author = await _member(database, 81_202)
    performer = await _member(database, 81_203)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    await EconomyService(database.unit_of_work).apply_one(starting_grant(author.id))
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    actors = _actors(author.telegram_user_id, performer.telegram_user_id)
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    send_message, send_callback = _transport(dispatcher, bot, actors)
    details = "Проверьте ясность первого экрана и предложите три улучшения."
    materials = "https://example.com/landing-review"

    await send_message(81_210, author.telegram_user_id, CREATE_TASK_TEXT)
    template = _visible(capture, lambda value: value.startswith("nav:create:"))
    capture.callbacks.clear()
    await send_callback(81_211, author.telegram_user_id, template)
    await send_message(81_212, author.telegram_user_id, details)
    await _click(capture, send_callback, 81_213, author.telegram_user_id, "task:step:days:")
    await _click(capture, send_callback, 81_214, author.telegram_user_id, "task:step:online")
    await send_message(81_215, author.telegram_user_id, materials)
    await _click(capture, send_callback, 81_216, author.telegram_user_id, "task:step:slots:1")
    capture.texts.clear()
    capture.callbacks.clear()
    await dispatcher.feed_update(
        bot,
        Update(
            update_id=81_216_1,
            message=Message(
                message_id=81_216_1,
                date=datetime.datetime.now(datetime.UTC),
                chat=Chat(id=-10081202, type="supergroup"),
                from_user=actors[author.telegram_user_id],
                text="/task_preview",
            ),
        ),
    )
    assert capture.texts == ["Работа с заданиями доступна только в личном чате с ботом."]  # noqa: RUF001
    capture.texts.clear()
    await send_callback(81_217, author.telegram_user_id, "task:step:preview")

    preview_text = next(
        text for text, callback in capture.button_payloads if callback.startswith("task:pub:")
    )
    _assert_task_card(capture, preview_text, details, materials)
    assert "Автор: Member 81202" in preview_text
    assert "Как выполнить:" in preview_text

    publish = _visible(capture, lambda value: value.startswith("task:pub:"))
    await send_callback(81_218, author.telegram_user_id, publish)
    capture.texts.clear()
    await send_message(81_218_1, author.telegram_user_id, MY_TASKS_TEXT)
    owned_card = next(text for text in capture.texts if details in text)
    _assert_task_card(capture, owned_card, details, materials)
    _visible_on_text(
        capture,
        lambda text: details in text,
        lambda value: value.startswith("task:cancel:ask:"),
    )
    capture.texts.clear()
    capture.callbacks.clear()
    capture.button_payloads.clear()
    await send_message(81_219, performer.telegram_user_id, FIND_TASK_TEXT)
    card_text, accept = next(
        (text, callback)
        for text, callback in capture.button_payloads
        if callback.startswith("task:accept:")
    )
    _assert_task_card(capture, card_text, details, materials)

    capture.texts.clear()
    await send_callback(81_220, performer.telegram_user_id, accept)
    accepted_text = capture.texts[-1]
    _assert_task_card(capture, accepted_text, details, materials)
    assert "Задание принято." in accepted_text
    capture.texts.clear()
    await send_message(81_221, performer.telegram_user_id, MY_TASKS_TEXT)
    recovered_text = next(text for text in capture.texts if details in text)
    _assert_task_card(capture, recovered_text, details, materials)
    capture.callbacks.clear()
    capture.button_payloads.clear()
    await send_message(81_222, author.telegram_user_id, MY_TASKS_TEXT)
    cancel_request = _visible_on_text(
        capture,
        lambda text: details in text,
        lambda value: value.startswith("task:cancel:ask:"),
    )
    capture.callbacks.clear()
    await send_callback(81_223, author.telegram_user_id, cancel_request)
    cancel_confirm = _visible_on_text(
        capture,
        lambda text: "Если задание уже взяли" in text,
        lambda value: value.startswith("task:cancel:do:"),
    )
    await send_callback(81_224, author.telegram_user_id, cancel_confirm)
    assert capture.callback_answers[-1] == (
        "Задание уже взял исполнитель, поэтому отменить его нельзя."  # noqa: RUF001
    )
    await bot.session.close()
    await database.dispose()


async def test_author_cancels_published_task_through_visible_confirmation(  # noqa: PLR0915
    database_url: str,
) -> None:
    """The visible two-step action refunds exactly once without exposing a UUID."""
    database = Database(database_url)
    admin = await _member(database, 81_301, MemberRole.ADMINISTRATOR)
    author = await _member(database, 81_302)
    outsider = await _member(database, 81_303)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    await EconomyService(database.unit_of_work).apply_one(starting_grant(author.id))
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        template_id = await session.scalar(
            select(TaskTemplateModel.id).where(
                TaskTemplateModel.code == "repository_first_impression"
            )
        )
    assert template_id is not None
    published = await _published_task(
        database,
        author,
        template_id,
        update_id_base=81_310,
    )

    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    actors = _actors(author.telegram_user_id, outsider.telegram_user_id)
    send_message, send_callback = _transport(dispatcher, bot, actors)

    await send_message(81_320, author.telegram_user_id, MY_TASKS_TEXT)
    request = _visible_on_text(
        capture,
        lambda text: published.title in text,
        lambda value: value.startswith("task:cancel:ask:"),
    )
    assert len(request.encode()) <= 64
    async with sessions() as session:
        author_before_request = await session.get(MemberModel, author.id)
        assert author_before_request is not None
        immutable_before_request = (
            author_before_request.credit_balance_cached,
            await session.scalar(select(func.count()).select_from(AccountTransactionModel)),
            await session.scalar(select(func.count()).select_from(AuditEventModel)),
            await session.scalar(select(func.count()).select_from(OutboxEventModel)),
            await session.scalar(select(func.count()).select_from(ProcessedTelegramUpdateModel)),
        )

    await send_callback(81_320_1, outsider.telegram_user_id, request)
    assert capture.callback_answers[-1] == (
        "Отменить задание может только его автор."  # noqa: RUF001
    )
    capture.callbacks.clear()
    await send_callback(81_321, author.telegram_user_id, request)
    confirm = _visible_on_text(
        capture,
        lambda text: f"Отменить «{published.title}»?" in text,
        lambda value: value.startswith("task:cancel:do:"),
    )
    assert len(confirm.encode()) <= 64

    async with sessions() as session:
        stored_before = await session.get(TaskModel, published.id)
        refunds_before = await session.scalar(
            select(func.count())
            .select_from(AccountTransactionModel)
            .where(AccountTransactionModel.transaction_type == "task_reward_refunded")
        )
        author_after_request = await session.get(MemberModel, author.id)
        assert author_after_request is not None
        immutable_after_request = (
            author_after_request.credit_balance_cached,
            await session.scalar(select(func.count()).select_from(AccountTransactionModel)),
            await session.scalar(select(func.count()).select_from(AuditEventModel)),
            await session.scalar(select(func.count()).select_from(OutboxEventModel)),
            await session.scalar(select(func.count()).select_from(ProcessedTelegramUpdateModel)),
        )
    assert stored_before is not None
    assert stored_before.status == "published"
    assert refunds_before == 0
    assert immutable_after_request == immutable_before_request

    capture.callbacks.clear()
    await send_callback(81_322, author.telegram_user_id, confirm)
    await send_callback(81_322, author.telegram_user_id, confirm)
    assert any("возвращены в доступный баланс" in text for text in capture.texts)
    async with sessions() as session:
        stored_after = await session.get(TaskModel, published.id)
        refunds_after = await session.scalar(
            select(func.count())
            .select_from(AccountTransactionModel)
            .where(AccountTransactionModel.transaction_type == "task_reward_refunded")
        )
        persisted_author = await session.get(MemberModel, author.id)
    assert stored_after is not None
    assert stored_after.status == "cancelled"
    assert refunds_after == 1
    assert persisted_author is not None
    assert persisted_author.credit_balance_cached == 10

    await send_callback(81_322_1, author.telegram_user_id, confirm)
    assert capture.callback_answers[-1] == "Это задание уже отменено."
    async with sessions() as session:
        refunds_after_stale_callback = await session.scalar(
            select(func.count())
            .select_from(AccountTransactionModel)
            .where(AccountTransactionModel.transaction_type == "task_reward_refunded")
        )
    assert refunds_after_stale_callback == 1

    capture.callbacks.clear()
    capture.button_payloads.clear()
    await send_message(81_323, author.telegram_user_id, MY_TASKS_TEXT)
    assert not any(value.startswith("task:cancel:ask:") for value in capture.callbacks)
    await bot.session.close()
    await database.dispose()


def _assert_task_card(
    capture: CapturingSession,
    text: str,
    details: str,
    materials: str,
) -> None:
    assert details in text
    assert materials in text
    assert "Результат:" in text
    assert (text, None) in capture.text_payloads


async def test_community_journey_and_admin_surfaces_are_reachable(database_url: str) -> None:  # noqa: PLR0915
    """Publish and pay a community task through captured administrator and member buttons."""
    database = Database(database_url)
    creator = await _member(database, 82_001, MemberRole.ADMINISTRATOR)
    reviewer = await _member(database, 82_002, MemberRole.ADMINISTRATOR)
    performer = await _member(database, 82_003)
    resolver = await _member(database, 82_004, MemberRole.ADMINISTRATOR)
    appeal_resolver = await _member(database, 82_005, MemberRole.ADMINISTRATOR)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=creator.id,
        activation_command_id=uuid4(),
    )
    await EconomyService(database.unit_of_work).apply_one(starting_grant(performer.id))
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    actors = _actors(
        creator.telegram_user_id,
        reviewer.telegram_user_id,
        performer.telegram_user_id,
        resolver.telegram_user_id,
        appeal_resolver.telegram_user_id,
    )
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    send_message, send_callback = _transport(dispatcher, bot, actors)

    await dispatcher.feed_update(
        bot,
        Update(
            update_id=82_099,
            message=Message(
                message_id=82_099,
                date=datetime.datetime.now(datetime.UTC),
                chat=Chat(id=-10082101, type="supergroup"),
                from_user=actors[creator.telegram_user_id],
                text=ADMIN_TEXT,
            ),
        ),
    )
    assert "nav:admin:community" not in capture.callbacks
    await dispatcher.feed_update(
        bot,
        Update(
            update_id=82_099_1,
            callback_query=CallbackQuery(
                id="group-community-task",
                from_user=actors[creator.telegram_user_id],
                chat_instance="group-community-task",
                data="nav:admin:community",
                message=Message(
                    message_id=82_099_1,
                    date=datetime.datetime.now(datetime.UTC),
                    chat=Chat(id=-10082101, type="supergroup"),
                    text="Администрирование",
                ),
            ),
        ),
    )
    assert capture.callback_answers[-1] == (
        "Создавайте задания сообщества в личном чате с ботом."  # noqa: RUF001
    )
    capture.reply_buttons.clear()
    await send_message(82_100, creator.telegram_user_id, "/start")
    admin_button = next(value for value in capture.reply_buttons if value == ADMIN_TEXT)
    capture.callbacks.clear()
    await send_message(82_101, creator.telegram_user_id, admin_button)
    community = _visible(capture, lambda value: value == "nav:admin:community")
    capture.callbacks.clear()
    await send_callback(82_102, creator.telegram_user_id, community)
    template = _visible(capture, lambda value: value.startswith("nav:community:"))
    capture.callbacks.clear()
    await send_callback(82_103, creator.telegram_user_id, template)
    reviewer_choice = _visible(capture, lambda value: value.startswith("task:reviewer:"))
    capture.callbacks.clear()
    await send_callback(82_104, creator.telegram_user_id, reviewer_choice)
    await send_message(
        82_105,
        creator.telegram_user_id,
        "Помогите сообществу подготовить полезный разбор нового материала.",
    )
    await _click(capture, send_callback, 82_106, creator.telegram_user_id, "task:step:days:")
    await _click(capture, send_callback, 82_107, creator.telegram_user_id, "task:step:online")
    capture.callbacks.clear()
    await send_message(82_108, creator.telegram_user_id, "Материал приложен к карточке.")
    await _click(capture, send_callback, 82_109, creator.telegram_user_id, "task:step:slots:")
    await _click(capture, send_callback, 82_110, creator.telegram_user_id, "task:step:preview")
    await send_callback(
        82_111,
        creator.telegram_user_id,
        _visible(capture, lambda value: value.startswith("task:pub:")),
    )

    capture.callbacks.clear()
    await send_message(82_112, performer.telegram_user_id, FIND_TASK_TEXT)
    await send_callback(
        82_113,
        performer.telegram_user_id,
        _visible(capture, lambda value: value.startswith("task:accept:")),
    )
    capture.callbacks.clear()
    await send_message(82_114, performer.telegram_user_id, MY_TASKS_TEXT)
    await send_callback(
        82_115,
        performer.telegram_user_id,
        _visible(capture, lambda value: value.startswith("as:a:s:")),
    )
    await send_message(
        82_116,
        performer.telegram_user_id,
        "Подготовил полный результат для задания сообщества и проверил детали.",
    )
    confirm = _visible(capture, lambda value: value.startswith("assign:submit:"))
    capture.callbacks.clear()
    await send_callback(82_117, performer.telegram_user_id, confirm)
    capture.callbacks.clear()
    await send_message(82_118, reviewer.telegram_user_id, MY_TASKS_TEXT)
    full = _visible(capture, lambda value: value.endswith(":full"))
    capture.callbacks.clear()
    await send_callback(82_119, reviewer.telegram_user_id, full)

    capture.callbacks.clear()
    await send_message(82_120, creator.telegram_user_id, admin_button)
    moderation = _visible(capture, lambda value: value == "nav:admin:moderation")
    capture.callbacks.clear()
    await send_callback(82_121, creator.telegram_user_id, moderation)
    assert {"mod:list:fraud", "mod:list:alerts", "mod:list:sanctions"} <= set(capture.callbacks)

    fraud_list = _visible(capture, lambda value: value == "mod:list:fraud")
    capture.callbacks.clear()
    await send_callback(82_122, creator.telegram_user_id, fraud_list)
    open_fraud = _visible(capture, lambda value: value.startswith("mod:fraud:"))
    capture.callbacks.clear()
    await send_callback(82_123, creator.telegram_user_id, open_fraud)

    capture.reply_buttons.clear()
    await send_message(82_124, resolver.telegram_user_id, "/start")
    resolver_admin = next(value for value in capture.reply_buttons if value == ADMIN_TEXT)
    capture.callbacks.clear()
    await send_message(82_125, resolver.telegram_user_id, resolver_admin)
    resolver_moderation = _visible(capture, lambda value: value == "nav:admin:moderation")
    capture.callbacks.clear()
    await send_callback(82_126, resolver.telegram_user_id, resolver_moderation)
    fraud_resolution = _visible(
        capture,
        lambda value: value.startswith("mod:case:") and value.endswith(":fraud"),
    )
    capture.callbacks.clear()
    await send_callback(82_127, resolver.telegram_user_id, fraud_resolution)
    confirm_refund = _visible(capture, lambda value: value.startswith("mod:res:"))
    capture.callbacks.clear()
    await send_callback(82_128, resolver.telegram_user_id, confirm_refund)

    capture.callbacks.clear()
    await send_message(82_129, performer.telegram_user_id, MY_TASKS_TEXT)
    appeal = _visible(capture, lambda value: value.startswith("mod:appeal:"))
    capture.callbacks.clear()
    await send_callback(82_130, performer.telegram_user_id, appeal)

    capture.reply_buttons.clear()
    await send_message(82_131, appeal_resolver.telegram_user_id, "/start")
    appeal_admin = next(value for value in capture.reply_buttons if value == ADMIN_TEXT)
    capture.callbacks.clear()
    await send_message(82_132, appeal_resolver.telegram_user_id, appeal_admin)
    appeal_moderation = _visible(capture, lambda value: value == "nav:admin:moderation")
    capture.callbacks.clear()
    await send_callback(82_133, appeal_resolver.telegram_user_id, appeal_moderation)
    full_payment = _visible(
        capture,
        lambda value: value.startswith("mod:case:") and value.endswith(":pay"),
    )
    capture.callbacks.clear()
    await send_callback(82_134, appeal_resolver.telegram_user_id, full_payment)
    confirm_appeal = _visible(capture, lambda value: value.startswith("mod:res:"))
    capture.callbacks.clear()
    await send_callback(82_135, appeal_resolver.telegram_user_id, confirm_appeal)

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        task = await session.scalar(
            select(TaskModel).where(TaskModel.created_by_admin_id == creator.id)
        )
        assert task is not None
        assignment = await session.scalar(
            select(AssignmentModel).where(AssignmentModel.task_id == task.id)
        )
        assert assignment is not None
        assignment_credit_total = await session.scalar(
            select(func.coalesce(func.sum(AccountTransactionModel.credit_delta), 0)).where(
                AccountTransactionModel.assignment_id == assignment.id,
                AccountTransactionModel.member_id == performer.id,
            )
        )
        personal_reserve = await session.scalar(
            select(func.count())
            .select_from(AccountTransactionModel)
            .where(
                AccountTransactionModel.task_id == task.id,
                AccountTransactionModel.transaction_type == "task_reward_reserved",
            )
        )
    assert task is not None
    assert task.creator_id is None
    assert task.reviewer_admin_id == reviewer.id
    assert assignment is not None
    assert assignment.status == "approved"
    assert assignment_credit_total == task.credit_reward_per_performer
    assert personal_reserve == 0
    await bot.session.close()
    await database.dispose()


async def test_unavailable_community_reviewer_is_replaced_from_visible_card(  # noqa: PLR0915
    database_url: str,
) -> None:
    """A stalled community result reopens with a new independent reviewer."""
    database = Database(database_url)
    creator = await _member(database, 83_001, MemberRole.ADMINISTRATOR)
    reviewer = await _member(database, 83_002, MemberRole.ADMINISTRATOR)
    replacement = await _member(database, 83_003, MemberRole.ADMINISTRATOR)
    performer = await _member(database, 83_004)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=creator.id,
        activation_command_id=uuid4(),
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        template_id = await session.scalar(
            select(TaskTemplateModel.id).where(
                TaskTemplateModel.code == "repository_first_impression"
            )
        )
    assert template_id is not None
    task_service = TaskService(database.unit_of_work)
    draft = await task_service.start(
        update_id=83_100,
        actor_telegram_user_id=creator.telegram_user_id,
        template_id=template_id,
        origin="community",
    )
    assert draft is not None
    draft = await task_service.select_community_reviewer(
        update_id=83_101,
        actor_telegram_user_id=creator.telegram_user_id,
        reviewer_id=reviewer.id,
    )
    values: list[object] = [
        {
            "context": "Community review context",
            "materials": "https://example.com/community",
            "constraints": "No private data",
        },
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=2),
        (TaskFormat.ONLINE, None),
        {"url": "https://example.com/community"},
        1,
    ]
    for offset, (step, value) in enumerate(
        zip(
            (
                TaskDraftStep.INPUT,
                TaskDraftStep.DEADLINE,
                TaskDraftStep.FORMAT,
                TaskDraftStep.MATERIALS,
                TaskDraftStep.SLOTS,
            ),
            values,
            strict=True,
        ),
        start=2,
    ):
        draft = await task_service.advance(
            AdvanceDraftCommand(
                83_100 + offset,
                creator.telegram_user_id,
                draft.id,
                step,
                draft.revision,
                value,
            )
        )
    preview = await task_service.preview(
        update_id=83_107,
        actor_telegram_user_id=creator.telegram_user_id,
        draft_id=draft.id,
        expected_revision=draft.revision,
    )
    task = await task_service.publish(
        PublishTaskCommand(
            83_108,
            creator.telegram_user_id,
            preview.draft.id,
            preview.draft.revision,
        )
    )
    assignment_service = AssignmentService(database.unit_of_work)
    assignment = await assignment_service.accept(
        AcceptAssignmentCommand(83_109, performer.telegram_user_id, task.id)
    )
    await assignment_service.submit(
        SubmitResultCommand(
            83_110,
            performer.telegram_user_id,
            assignment.id,
            uuid4(),
            {
                "summary": "A complete community result ready for review.",
                "findings": ["One useful finding"],
                "evidence": [],
            },
        )
    )
    now = datetime.datetime.now(datetime.UTC)
    async with sessions.begin() as session:
        stored_reviewer = await session.get(type(reviewer), reviewer.id)
        stored_assignment = await session.get(AssignmentModel, assignment.id)
        assert stored_reviewer is not None
        assert stored_assignment is not None
        stored_reviewer.status = "paused"
        stored_assignment.review_deadline_at = now - datetime.timedelta(seconds=1)
    stalled = await assignment_service.finalize_review(
        assignment_id=assignment.id,
        command_id=uuid4(),
        now=now,
    )
    assert stalled.status.value == "reviewer_required"

    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    actors = _actors(creator.telegram_user_id)
    send_message, send_callback = _transport(dispatcher, bot, actors)
    await send_message(83_111, creator.telegram_user_id, MY_TASKS_TEXT)
    replace = _visible(capture, lambda value: value.startswith("task:rr:"))
    capture.callbacks.clear()
    await send_callback(83_112, creator.telegram_user_id, replace)
    select_replacement = _visible(capture, lambda value: value.startswith("task:rs:"))
    capture.callbacks.clear()
    await send_callback(83_113, creator.telegram_user_id, select_replacement)

    async with sessions() as session:
        updated_task = await session.get(TaskModel, task.id)
        updated_assignment = await session.get(AssignmentModel, assignment.id)
    assert updated_task is not None
    assert updated_assignment is not None
    assert updated_task.reviewer_admin_id == replacement.id
    assert updated_assignment.status == "submitted"
    assert updated_assignment.review_deadline_at is not None
    assert updated_assignment.review_deadline_at > now
    await bot.session.close()
    await database.dispose()


async def test_karma_sanction_and_alert_use_only_visible_outputs(  # noqa: PLR0915
    database_url: str,
) -> None:
    """Reach the remaining administrative surfaces without constructing callbacks."""
    database = Database(database_url)
    admin = await _member(database, 84_001, MemberRole.ADMINISTRATOR)
    target = await _member(database, 84_002)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    assignment_ids = [await add_paid_interaction(database, admin, target) for _ in range(4)]
    async with database.unit_of_work() as uow:
        await uow.recompute_interaction_alert(assignment_ids[-1])
        await uow.commit()

    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    actors = _actors(admin.telegram_user_id)
    send_message, send_callback = _transport(dispatcher, bot, actors)

    capture.callbacks.clear()
    await send_message(84_100, admin.telegram_user_id, MEMBERS_TEXT)
    begin_vote = _visible_on_text(
        capture,
        lambda text: target.display_name in text,
        lambda value: value.startswith("karma:begin:"),
    )
    capture.callbacks.clear()
    await send_callback(84_101, admin.telegram_user_id, begin_vote)
    positive = _visible(
        capture, lambda value: value.startswith("karma:value:") and value.endswith(":1")
    )
    capture.callbacks.clear()
    await send_callback(84_102, admin.telegram_user_id, positive)
    await send_message(
        84_103,
        admin.telegram_user_id,
        "A useful and careful interaction with a clear result.",
    )
    confirm_vote = _visible(capture, lambda value: value.startswith("karma:confirm:"))
    capture.callbacks.clear()
    await send_callback(84_104, admin.telegram_user_id, confirm_vote)

    capture.callbacks.clear()
    await send_message(84_105, admin.telegram_user_id, MEMBERS_TEXT)
    raw_karma = _visible_on_text(
        capture,
        lambda text: target.display_name in text,
        lambda value: value.startswith("karma:raw:"),
    )
    capture.callbacks.clear()
    await send_callback(84_106, admin.telegram_user_id, raw_karma)
    exclude_vote = _visible(
        capture,
        lambda value: value.startswith("karma:mod:") and value.endswith(":x"),
    )
    capture.callbacks.clear()
    await send_callback(84_107, admin.telegram_user_id, exclude_vote)

    capture.callbacks.clear()
    await send_message(84_108, admin.telegram_user_id, MEMBERS_TEXT)
    restrict = _visible_on_text(
        capture,
        lambda text: target.display_name in text,
        lambda value: value.startswith("mod:restrict:"),
    )
    capture.callbacks.clear()
    await send_callback(84_109, admin.telegram_user_id, restrict)

    capture.callbacks.clear()
    await send_message(84_110, admin.telegram_user_id, ADMIN_TEXT)
    moderation = _visible(capture, lambda value: value == "nav:admin:moderation")
    capture.callbacks.clear()
    await send_callback(84_111, admin.telegram_user_id, moderation)
    sanctions = _visible(capture, lambda value: value == "mod:list:sanctions")
    capture.callbacks.clear()
    await send_callback(84_112, admin.telegram_user_id, sanctions)
    revoke = _visible(capture, lambda value: value.startswith("mod:revoke:"))
    capture.callbacks.clear()
    await send_callback(84_113, admin.telegram_user_id, revoke)

    capture.callbacks.clear()
    await send_message(84_114, admin.telegram_user_id, ADMIN_TEXT)
    moderation = _visible(capture, lambda value: value == "nav:admin:moderation")
    capture.callbacks.clear()
    await send_callback(84_115, admin.telegram_user_id, moderation)
    alerts = _visible(capture, lambda value: value == "mod:list:alerts")
    capture.callbacks.clear()
    await send_callback(84_116, admin.telegram_user_id, alerts)
    monitor = _visible(
        capture,
        lambda value: value.startswith("mod:alert:") and value.endswith(":watch"),
    )
    capture.callbacks.clear()
    await send_callback(84_117, admin.telegram_user_id, monitor)

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        votes = await session.scalar(select(func.count()).select_from(KarmaVoteModel))
        exclusion = await session.scalar(select(KarmaVoteModerationModel))
        sanction = await session.scalar(select(MemberSanctionModel))
        alert = await session.scalar(select(InteractionAlertModel))
    assert votes == 1
    assert exclusion is not None
    assert exclusion.state == "excluded"
    assert sanction is not None
    assert sanction.state == "revoked"
    assert alert is not None
    assert alert.state == "closed"
    assert alert.outcome == "monitor"
    assert all(len(value.encode()) <= 64 for value in capture.callbacks)
    await bot.session.close()
    await database.dispose()


async def test_no_show_is_visible_after_deadline_worker(database_url: str) -> None:
    """Accept visibly, run the deadline finalizer, and reopen the terminal card."""
    database = Database(database_url)
    admin = await _member(database, 86_001, MemberRole.ADMINISTRATOR)
    author = await _member(database, 86_002)
    performer = await _member(database, 86_003)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    economy = EconomyService(database.unit_of_work)
    await economy.apply_one(starting_grant(author.id))
    await economy.apply_one(starting_grant(performer.id))
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        template_id = await session.scalar(
            select(TaskTemplateModel.id).where(
                TaskTemplateModel.code == "repository_first_impression"
            )
        )
    assert template_id is not None
    task = await _published_task(database, author, template_id)

    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    actors = _actors(performer.telegram_user_id)
    send_message, send_callback = _transport(dispatcher, bot, actors)
    await send_message(86_100, performer.telegram_user_id, FIND_TASK_TEXT)
    await _click(capture, send_callback, 86_101, performer.telegram_user_id, "task:accept:")

    finalized = await AssignmentDeadlineWorker(
        PostgresAssignmentDeadlineSource(database.session_factory),
        AssignmentService(database.unit_of_work),
    ).tick(
        now=task.deadline_at + datetime.timedelta(seconds=1),
    )
    assert finalized == 1
    capture.callbacks.clear()
    capture.texts.clear()
    await send_message(86_102, performer.telegram_user_id, MY_TASKS_TEXT)
    assert any("неявка" in text for text in capture.texts)
    async with sessions() as session:
        assignment = await session.scalar(
            select(AssignmentModel).where(AssignmentModel.task_id == task.id)
        )
        assert assignment is not None
        refund = await session.scalar(
            select(func.count())
            .select_from(AccountTransactionModel)
            .where(
                AccountTransactionModel.assignment_id == assignment.id,
                AccountTransactionModel.transaction_type == "task_reward_refunded",
            )
        )
    assert assignment.status == "no_show"
    assert refund == 1
    await bot.session.close()
    await database.dispose()


async def test_deadline_worker_skips_non_actionable_older_tasks(database_url: str) -> None:
    """Do not let an older settling task starve a later accepted assignment."""
    database = Database(database_url)
    admin = await _member(database, 86_201, MemberRole.ADMINISTRATOR)
    old_author = await _member(database, 86_202)
    new_author = await _member(database, 86_203)
    old_performer = await _member(database, 86_204)
    new_performer = await _member(database, 86_205)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    economy = EconomyService(database.unit_of_work)
    await economy.apply_one(starting_grant(old_author.id))
    await economy.apply_one(starting_grant(new_author.id))
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        template_id = await session.scalar(
            select(TaskTemplateModel.id).where(
                TaskTemplateModel.code == "repository_first_impression"
            )
        )
    assert template_id is not None
    old_task = await _published_task(
        database,
        old_author,
        template_id,
        update_id_base=86_210,
    )
    new_task = await _published_task(
        database,
        new_author,
        template_id,
        update_id_base=86_220,
    )
    assignments = AssignmentService(database.unit_of_work)
    old_assignment = await assignments.accept(
        AcceptAssignmentCommand(86_230, old_performer.telegram_user_id, old_task.id)
    )
    new_assignment = await assignments.accept(
        AcceptAssignmentCommand(86_231, new_performer.telegram_user_id, new_task.id)
    )
    async with sessions.begin() as session:
        stored_old_task = await session.get(TaskModel, old_task.id)
        stored_old_assignment = await session.get(AssignmentModel, old_assignment.id)
        assert stored_old_task is not None
        assert stored_old_assignment is not None
        stored_old_task.status = "settling"
        stored_old_assignment.status = "submitted"

    finalized = await AssignmentDeadlineWorker(
        PostgresAssignmentDeadlineSource(database.session_factory),
        assignments,
        batch_size=1,
    ).tick(now=new_task.deadline_at + datetime.timedelta(seconds=1))

    async with sessions() as session:
        old_status = await session.scalar(
            select(AssignmentModel.status).where(AssignmentModel.id == old_assignment.id)
        )
        new_status = await session.scalar(
            select(AssignmentModel.status).where(AssignmentModel.id == new_assignment.id)
        )
    assert finalized == 1
    assert old_status == "submitted"
    assert new_status == "no_show"
    await database.dispose()


async def test_community_provenance_survives_exact_migration_cycle(
    database_url: str,
) -> None:
    """Run 0011→0012→0011→0012 and preserve a paid community exchange."""
    initial = Database(database_url)
    await initial.dispose()
    await _migrate(database_url, "0011")
    await _migrate(database_url, "0012", upgrade=True)

    database = Database(database_url)
    creator = await _member(database, 87_001, MemberRole.ADMINISTRATOR)
    reviewer = await _member(database, 87_002, MemberRole.ADMINISTRATOR)
    performer = await _member(database, 87_003)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=creator.id,
        activation_command_id=uuid4(),
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        template_id = await session.scalar(
            select(TaskTemplateModel.id).where(
                TaskTemplateModel.code == "repository_first_impression"
            )
        )
    assert template_id is not None
    task = await _published_community_task(database, creator, reviewer, template_id)
    service = AssignmentService(database.unit_of_work)
    assignment = await service.accept(
        AcceptAssignmentCommand(87_100, performer.telegram_user_id, task.id)
    )
    await service.submit(
        SubmitResultCommand(
            87_101,
            performer.telegram_user_id,
            assignment.id,
            uuid4(),
            {
                "summary": "A result persisted across an exact migration cycle.",
                "findings": ["One migration finding"],
                "evidence": [],
            },
        )
    )
    assignment = await service.decide(
        DecideAssignmentCommand(
            87_102,
            reviewer.telegram_user_id,
            assignment.id,
            uuid4(),
            AssignmentDecision.FULL,
        )
    )
    async with sessions() as session:
        transaction_ids = tuple(
            await session.scalars(
                select(AccountTransactionModel.id)
                .where(AccountTransactionModel.assignment_id == assignment.id)
                .order_by(AccountTransactionModel.id)
            )
        )
    assert transaction_ids
    await database.dispose()

    await _migrate(database_url, "0011")
    legacy = Database(database_url)
    async with legacy.engine.connect() as connection:
        backup = await connection.scalar(
            select(TaskModel.safety_snapshot_json).where(TaskModel.id == task.id)
        )
    assert backup is not None
    assert backup["_community_created_by_admin_id"] == str(creator.id)
    assert backup["_community_reviewer_admin_id"] == str(reviewer.id)
    await legacy.dispose()

    await _migrate(database_url, "0012", upgrade=True)
    restored = Database(database_url)
    restored_sessions = async_sessionmaker(restored.engine, expire_on_commit=False)
    async with restored_sessions() as session:
        restored_task = await session.get(TaskModel, task.id)
        restored_assignment = await session.get(AssignmentModel, assignment.id)
        restored_transactions = tuple(
            await session.scalars(
                select(AccountTransactionModel.id)
                .where(AccountTransactionModel.assignment_id == assignment.id)
                .order_by(AccountTransactionModel.id)
            )
        )
    assert restored_task is not None
    assert restored_task.created_by_admin_id == creator.id
    assert restored_task.reviewer_admin_id == reviewer.id
    assert "_community_created_by_admin_id" not in restored_task.safety_snapshot_json
    assert restored_assignment is not None
    assert restored_assignment.status == "approved"
    assert restored_transactions == transaction_ids
    await restored.dispose()


async def test_reject_dispute_and_moderator_resolution_use_visible_outputs(  # noqa: PLR0915
    database_url: str,
) -> None:
    """Reach the private dispute and staff decision from the buttons the bot emitted."""
    database = Database(database_url)
    creator = await _member(database, 85_001, MemberRole.ADMINISTRATOR)
    reviewer = await _member(database, 85_002, MemberRole.ADMINISTRATOR)
    performer = await _member(database, 85_003)
    moderator = await _member(database, 85_004, MemberRole.MODERATOR)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=creator.id,
        activation_command_id=uuid4(),
    )
    economy = EconomyService(database.unit_of_work)
    await economy.apply_one(starting_grant(performer.id))
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        template_id = await session.scalar(
            select(TaskTemplateModel.id).where(
                TaskTemplateModel.code == "repository_first_impression"
            )
        )
    assert template_id is not None
    task = await _published_community_task(database, creator, reviewer, template_id)

    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    actors = _actors(
        reviewer.telegram_user_id,
        performer.telegram_user_id,
        moderator.telegram_user_id,
    )
    send_message, send_callback = _transport(dispatcher, bot, actors)

    await send_message(85_100, performer.telegram_user_id, FIND_TASK_TEXT)
    await _click(capture, send_callback, 85_101, performer.telegram_user_id, "task:accept:")
    capture.callbacks.clear()
    await send_message(85_102, performer.telegram_user_id, MY_TASKS_TEXT)
    await _click(capture, send_callback, 85_103, performer.telegram_user_id, "as:a:s:")
    await send_message(
        85_104,
        performer.telegram_user_id,
        "A complete result that the author can review through the visible card.",
    )
    await _click(capture, send_callback, 85_105, performer.telegram_user_id, "assign:submit:")

    capture.callbacks.clear()
    await send_message(85_106, reviewer.telegram_user_id, MY_TASKS_TEXT)
    reject = _visible(capture, lambda value: value.endswith(":reject"))
    capture.callbacks.clear()
    await send_callback(85_107, reviewer.telegram_user_id, reject)

    capture.callbacks.clear()
    await send_message(85_108, performer.telegram_user_id, MY_TASKS_TEXT)
    begin_dispute = _visible(capture, lambda value: value.startswith("as:a:d:"))
    capture.callbacks.clear()
    await send_callback(85_109, performer.telegram_user_id, begin_dispute)
    private_comment = "The submitted result met the visible criteria; please review the rejection."
    await send_message(85_110, performer.telegram_user_id, private_comment)

    capture.reply_buttons.clear()
    await send_message(85_111, moderator.telegram_user_id, "/start")
    staff_button = next(value for value in capture.reply_buttons if value == ADMIN_TEXT)
    capture.callbacks.clear()
    await send_message(85_112, moderator.telegram_user_id, staff_button)
    refund = _visible(
        capture,
        lambda value: value.startswith("mod:case:") and value.endswith(":refund"),
    )
    capture.callbacks.clear()
    await send_callback(85_113, moderator.telegram_user_id, refund)
    await _click(capture, send_callback, 85_114, moderator.telegram_user_id, "mod:res:")

    async with sessions() as session:
        assignment = await session.scalar(
            select(AssignmentModel).where(AssignmentModel.task_id == task.id)
        )
        assert assignment is not None
        case = await session.scalar(
            select(ModerationCaseModel).where(ModerationCaseModel.assignment_id == assignment.id)
        )
        personal_reserve = await session.scalar(
            select(func.count())
            .select_from(AccountTransactionModel)
            .where(
                AccountTransactionModel.task_id == task.id,
                AccountTransactionModel.transaction_type == "task_reward_reserved",
            )
        )
    assert assignment.status == "rejected"
    assert case is not None
    assert case.status == "resolved"
    assert personal_reserve == 0
    assert private_comment not in capture.texts
    await bot.session.close()
    await database.dispose()


async def _published_community_task(
    database: Database,
    creator: MemberModel,
    reviewer: MemberModel,
    template_id: UUID,
) -> TaskModel:
    service = TaskService(database.unit_of_work)
    draft = await service.start(
        update_id=85_010,
        actor_telegram_user_id=creator.telegram_user_id,
        template_id=template_id,
        origin="community",
    )
    assert draft is not None
    draft = await service.select_community_reviewer(
        update_id=85_011,
        actor_telegram_user_id=creator.telegram_user_id,
        reviewer_id=reviewer.id,
    )
    values: list[object] = [
        {
            "context": "Community dispute context",
            "materials": "https://example.com/community-dispute",
            "constraints": "No private data",
        },
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=2),
        (TaskFormat.ONLINE, None),
        {"url": "https://example.com/community-dispute"},
        1,
    ]
    for offset, (step, value) in enumerate(
        zip(
            (
                TaskDraftStep.INPUT,
                TaskDraftStep.DEADLINE,
                TaskDraftStep.FORMAT,
                TaskDraftStep.MATERIALS,
                TaskDraftStep.SLOTS,
            ),
            values,
            strict=True,
        ),
        start=2,
    ):
        draft = await service.advance(
            AdvanceDraftCommand(
                85_010 + offset,
                creator.telegram_user_id,
                draft.id,
                step,
                draft.revision,
                value,
            )
        )
    preview = await service.preview(
        update_id=85_017,
        actor_telegram_user_id=creator.telegram_user_id,
        draft_id=draft.id,
        expected_revision=draft.revision,
    )
    published = await service.publish(
        PublishTaskCommand(
            85_018,
            creator.telegram_user_id,
            preview.draft.id,
            preview.draft.revision,
        )
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        task = await session.get(TaskModel, published.id)
    assert task is not None
    return task


async def _migrate(database_url: str, revision: str, *, upgrade: bool = False) -> None:
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    configuration = Config("alembic.ini")
    try:
        operation = command.upgrade if upgrade else command.downgrade
        await asyncio.to_thread(operation, configuration, revision)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _actors(*telegram_user_ids: int) -> dict[int, User]:
    return {
        value: User(id=value, is_bot=False, first_name=f"Member {value}")
        for value in telegram_user_ids
    }


def _transport(
    dispatcher: Dispatcher,
    bot: Bot,
    actors: dict[int, User],
) -> tuple[MessageSender, CallbackSender]:
    async def send_message(update_id: int, actor_id: int, text: str) -> None:
        await dispatcher.feed_update(
            bot,
            Update(
                update_id=update_id,
                message=Message(
                    message_id=update_id,
                    date=datetime.datetime.now(datetime.UTC),
                    chat=Chat(id=actor_id, type="private"),
                    from_user=actors[actor_id],
                    text=text,
                ),
            ),
        )

    async def send_callback(update_id: int, actor_id: int, data: str) -> None:
        await dispatcher.feed_update(
            bot,
            Update(
                update_id=update_id,
                callback_query=CallbackQuery(
                    id=str(update_id),
                    from_user=actors[actor_id],
                    chat_instance="output-driven",
                    data=data,
                    message=Message(
                        message_id=update_id,
                        date=datetime.datetime.now(datetime.UTC),
                        chat=Chat(id=actor_id, type="private"),
                        from_user=actors[actor_id],
                        text="button",
                    ),
                ),
            ),
        )

    return send_message, send_callback


def _visible(capture: CapturingSession, predicate: Callable[[str], bool]) -> str:
    return next(value for value in capture.callbacks if predicate(value))


def _visible_on_text(
    capture: CapturingSession,
    text_predicate: Callable[[str], bool],
    callback_predicate: Callable[[str], bool],
) -> str:
    return next(
        callback
        for text, callback in capture.button_payloads
        if text_predicate(text) and callback_predicate(callback)
    )


async def _click(
    capture: CapturingSession,
    send_callback: CallbackSender,
    update_id: int,
    actor_id: int,
    prefix: str,
) -> None:
    callback = _visible(capture, lambda value: value.startswith(prefix))
    capture.callbacks.clear()
    await send_callback(update_id, actor_id, callback)
