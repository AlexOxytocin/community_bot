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

from community_bot.application import tasks as task_application
from community_bot.application.assignments import (
    AcceptAssignmentCommand,
    AssignmentDeadlineWorker,
    AssignmentService,
    BeginSubmissionCommand,
    ConfirmSubmissionDraftCommand,
    DecideAssignmentCommand,
    SaveSubmissionDraftCommand,
    SubmitResultCommand,
)
from community_bot.application.economy import EconomyService, ProductConfigBootstrapCoordinator
from community_bot.application.notifications import NotificationWorker
from community_bot.application.tasks import (
    AdvanceDraftCommand,
    PublishedTask,
    PublishTaskCommand,
    TaskCancellationOutcome,
    TaskService,
)
from community_bot.bootstrap.bot import _dispatcher
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.domain.assignments import (
    Assignment,
    AssignmentDecision,
    AssignmentError,
    SubmissionDraft,
)
from community_bot.domain.catalog import TaskFormat
from community_bot.domain.economy import starting_grant
from community_bot.domain.members import (
    ADMINISTRATOR_PERMISSIONS,
    SUPERADMINISTRATOR_PERMISSION,
    MemberRole,
)
from community_bot.domain.notifications import DeliveryWindow
from community_bot.domain.tasks import TaskDraftStep, TaskError, TaskStatus
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
    ReliabilityEventModel,
    TaskCancellationRequestModel,
    TaskCancellationResponseModel,
    TaskCreationDraftModel,
    TaskModel,
    TaskTemplateModel,
)
from community_bot.infrastructure.outbox import PostgresNotificationQueue
from community_bot.infrastructure.outbox.telegram import TelegramNotificationSender
from community_bot.transport.telegram.navigation import (
    ADMIN_TEXT,
    MEMBERS_TEXT,
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
FIND_TASK_COMMAND = "/tasks"
CREATE_TASK_COMMAND = "/create"
MY_TASKS_COMMAND = "/my_tasks"
ACCEPTED_TASKS_COMMAND = "/my_assignments"


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
    await send_message(81_100, performer.telegram_user_id, FIND_TASK_COMMAND)
    accept = _visible(capture, lambda value: value.startswith("task:accept:"))
    capture.callbacks.clear()
    await send_callback(81_101, performer.telegram_user_id, accept)
    submit = _visible(capture, lambda value: value.startswith("as:a:s:"))

    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    send_message, send_callback = _transport(dispatcher, bot, actors)
    capture.callbacks.clear()
    await send_message(81_102, performer.telegram_user_id, ACCEPTED_TASKS_COMMAND)
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
    await send_message(81_106, author.telegram_user_id, MY_TASKS_COMMAND)
    review = _visible(capture, lambda value: value.endswith(":partial"))
    capture.callbacks.clear()
    await send_callback(81_107, author.telegram_user_id, review)

    capture.callbacks.clear()
    await send_message(81_108, performer.telegram_user_id, CREATE_TASK_COMMAND)
    await _complete_freeform_creation(
        capture,
        send_message,
        send_callback,
        update_base=81_130,
        actor_id=performer.telegram_user_id,
        title="Практичная обратная связь",
        details="Нужно внимательно посмотреть материал и дать практичную обратную связь.",
        criteria="Есть понятный список наблюдений и конкретный итоговый вывод.",
        materials="Ссылка будет в описании задания.",
    )
    publish = _visible(capture, lambda value: value.startswith("task:pub:"))
    await send_callback(81_140, performer.telegram_user_id, publish)

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


async def test_task_publish_reports_insufficient_balance_without_losing_draft(
    database_url: str,
) -> None:
    """A rejected publication explains the balance problem and keeps the preview editable."""
    database = Database(database_url)
    admin = await _member(database, 81_501, MemberRole.ADMINISTRATOR)
    author = await _member(database, 81_502)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    actors = _actors(author.telegram_user_id)
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    send_message, send_callback = _transport(dispatcher, bot, actors)

    await send_message(81_510, author.telegram_user_id, CREATE_TASK_COMMAND)
    await _complete_freeform_creation(
        capture,
        send_message,
        send_callback,
        update_base=81_511,
        actor_id=author.telegram_user_id,
        title="Проверить отказ при недостаточном балансе",
        details="Нужно подтвердить безопасное сообщение об ошибке публикации.",  # noqa: RUF001
        criteria="Карточка не опубликована, а черновик остаётся доступен.",  # noqa: RUF001
        materials="Материалы не требуются.",
        group_slots=3,
    )
    publish = _visible(capture, lambda value: value.startswith("task:pub:"))
    await send_callback(81_530, author.telegram_user_id, publish)

    assert capture.callback_answers[-1] == (
        "Недостаточно кредитов для публикации. Уменьшите награду или количество исполнителей."
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        assert await session.scalar(select(func.count(TaskModel.id))) == 0
        draft = await session.scalar(
            select(TaskCreationDraftModel).where(
                TaskCreationDraftModel.creator_id == author.id,
                TaskCreationDraftModel.is_current.is_(True),
            )
        )
    assert draft is not None
    assert draft.current_step == TaskDraftStep.PREVIEW.value

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

    await send_message(81_210, author.telegram_user_id, CREATE_TASK_COMMAND)
    await _complete_freeform_creation(
        capture,
        send_message,
        send_callback,
        update_base=81_230,
        actor_id=author.telegram_user_id,
        title="Проверить первый экран",
        details=details,
        criteria="Есть три конкретных улучшения и короткий вывод о ясности.",  # noqa: RUF001
        materials=materials,
    )
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
    task_title = preview_text.splitlines()[0]
    _assert_task_card(capture, preview_text, details, materials)
    assert "Автор: Member 81202" in preview_text
    assert "Как выполнить:" in preview_text

    publish = _visible(capture, lambda value: value.startswith("task:pub:"))
    await send_callback(81_218, author.telegram_user_id, publish)
    capture.texts.clear()
    capture.callbacks.clear()
    capture.button_payloads.clear()
    await send_message(81_218_1, author.telegram_user_id, MY_TASKS_COMMAND)
    owned_summary = next(text for text in capture.texts if task_title in text)
    assert "Свободно" in owned_summary
    assert details not in owned_summary
    assert materials not in owned_summary
    expand = _visible_on_text(
        capture,
        lambda text: text == owned_summary,
        lambda value: value.startswith("task:view:open:"),
    )
    capture.callbacks.clear()
    capture.button_payloads.clear()
    await send_callback(81_218_2, author.telegram_user_id, expand)
    expanded = next(text for text in capture.texts if details in text)
    _assert_task_card(capture, expanded, details, materials)
    collapse = _visible_on_text(
        capture,
        lambda text: text == expanded,
        lambda value: value.startswith("task:view:close:"),
    )
    assert len(expand.encode()) <= 64
    assert len(collapse.encode()) <= 64
    capture.callbacks.clear()
    await send_callback(81_218_3, author.telegram_user_id, collapse)
    assert capture.texts[-1] == owned_summary
    capture.texts.clear()
    capture.callbacks.clear()
    capture.button_payloads.clear()
    await send_message(81_219, performer.telegram_user_id, FIND_TASK_COMMAND)
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
    await send_message(81_221, performer.telegram_user_id, ACCEPTED_TASKS_COMMAND)
    recovered_summary = next(text for text in capture.texts if task_title in text)
    assert "Статус: в работе" in recovered_summary
    assert details not in recovered_summary
    assignment_expand = _visible_on_text(
        capture,
        lambda text: text == recovered_summary,
        lambda value: value.startswith("as:view:open:"),
    )
    capture.callbacks.clear()
    capture.button_payloads.clear()
    await send_callback(81_221_1, performer.telegram_user_id, assignment_expand)
    recovered_text = next(text for text in capture.texts if details in text)
    _assert_task_card(capture, recovered_text, details, materials)
    assert "Статус: в работе" in recovered_text
    capture.texts.clear()
    capture.callbacks.clear()
    capture.button_payloads.clear()
    await send_message(81_222, author.telegram_user_id, MY_TASKS_COMMAND)
    occupied_summary = next(text for text in capture.texts if task_title in text)
    assert "Member 81203" in occupied_summary
    assert "1/1" in occupied_summary
    assert details not in occupied_summary
    cancel_request = _visible_on_text(
        capture,
        lambda text: text == occupied_summary,
        lambda value: value.startswith("task:cancel:ask:"),
    )
    capture.callbacks.clear()
    await send_callback(81_223, author.telegram_user_id, cancel_request)
    cancel_confirm = _visible_on_text(
        capture,
        lambda text: "Завершить набор" in text,
        lambda value: value.startswith("task:cancel:req:"),
    )
    await send_callback(81_224, author.telegram_user_id, cancel_confirm)
    assert capture.callback_answers[-1] == "Набор завершён."  # noqa: RUF001
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        assert await session.scalar(select(TaskCancellationResponseModel.id)) is not None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.event_type == "task.cancellation_requested")
            )
        ) == 1
    capture.texts.clear()
    capture.callbacks.clear()
    capture.button_payloads.clear()
    worker = NotificationWorker(
        PostgresNotificationQueue(database.session_factory),
        TelegramNotificationSender(bot),
        delivery_window=DeliveryWindow(start=datetime.time.min, end=datetime.time.max),
        batch_size=100,
    )
    notifications_sent = 0
    for _ in range(3):
        tick = await worker.tick(now=datetime.datetime.now(datetime.UTC))
        notifications_sent += tick.notifications_sent
        if any(value.startswith("task:cancel:yes:") for value in capture.callbacks):
            break
        capture.texts.clear()
        capture.callbacks.clear()
        capture.button_payloads.clear()
    assert notifications_sent > 0
    assert any("сдать результат" in text for text in capture.texts), capture.texts
    performer_confirmation = _visible(capture, lambda value: value.startswith("task:cancel:yes:"))
    await send_callback(81_225, performer.telegram_user_id, performer_confirmation)
    await send_callback(81_226, performer.telegram_user_id, performer_confirmation)
    assert capture.callback_answers[-1] == "Запрос отмены больше не актуален."
    capture.texts.clear()
    capture.callbacks.clear()
    capture.button_payloads.clear()
    await send_message(81_227, performer.telegram_user_id, ACCEPTED_TASKS_COMMAND)
    cancelled_summary = next(text for text in capture.texts if "Статус: cancelled" in text)
    assert "Статус: отменено" not in cancelled_summary
    assert details not in cancelled_summary
    cancelled_expand = _visible_on_text(
        capture,
        lambda text: text == cancelled_summary,
        lambda value: value.startswith("as:view:open:"),
    )
    capture.callbacks.clear()
    capture.button_payloads.clear()
    await send_callback(81_228, performer.telegram_user_id, cancelled_expand)
    cancelled_details = next(
        text for text in capture.texts if details in text and "Статус: cancelled" in text
    )
    assert "Статус: отменено" not in cancelled_details
    async with sessions() as session:
        cancelled_task = await session.scalar(select(TaskModel))
        creator_cancellations = await session.scalar(
            select(func.count())
            .select_from(ReliabilityEventModel)
            .where(ReliabilityEventModel.event_type == "cancelled_creator")
        )
        performer_cancellations = await session.scalar(
            select(func.count())
            .select_from(ReliabilityEventModel)
            .where(ReliabilityEventModel.event_type == "cancelled_performer")
        )
    assert cancelled_task is not None
    assert cancelled_task.status == "cancelled"
    assert creator_cancellations == 1
    assert performer_cancellations == 0
    await bot.session.close()
    await database.dispose()


async def test_freeform_draft_edits_every_preview_field_and_uses_slot_counter(  # noqa: PLR0915
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await _member(database, 81_301, MemberRole.ADMINISTRATOR)
    author = await _member(database, 81_302)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    actors = _actors(author.telegram_user_id)
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    send_message, send_callback = _transport(dispatcher, bot, actors)
    next_update = 81_310

    async def press(callback_data: str) -> None:
        nonlocal next_update
        capture.callbacks.clear()
        await send_callback(next_update, author.telegram_user_id, callback_data)
        next_update += 1

    async def press_visible(predicate: Callable[[str], bool]) -> None:
        await press(_visible(capture, predicate))

    async def answer(text: str) -> None:
        nonlocal next_update
        capture.callbacks.clear()
        await send_message(next_update, author.telegram_user_id, text)
        next_update += 1

    async def open_preview() -> None:
        await press_visible(lambda value: value == "task:step:preview")

    await send_message(next_update, author.telegram_user_id, CREATE_TASK_COMMAND)
    next_update += 1
    await press_visible(lambda value: value == "task:step:kind:group")
    await press_visible(lambda value: value.startswith("task:step:cat:"))
    await press_visible(lambda value: value == "task:step:size:s")

    await press_visible(
        lambda value: value.startswith("task:step:slots:adjust:") and value.endswith(":-5")
    )
    assert capture.callback_answers[-1] == "Минимум — 2 исполнителя."
    assert capture.texts[-1].startswith("Количество исполнителей: 2.")
    await press_visible(
        lambda value: value.startswith("task:step:slots:adjust:") and value.endswith(":5")
    )
    await press_visible(
        lambda value: value.startswith("task:step:slots:adjust:") and value.endswith(":-1")
    )
    await press_visible(
        lambda value: value.startswith("task:step:slots:adjust:") and value.endswith(":1")
    )
    assert capture.texts[-1].startswith("Количество исполнителей: 7.")
    await press_visible(lambda value: value.startswith("task:step:slots:confirm:"))
    await press_visible(lambda value: value == "task:step:reward:2")
    for value in (
        "Первоначальное название",
        "Первоначальное описание задания.",
        "Первоначальные критерии результата.",
        "https://example.com/initial",
    ):
        await answer(value)
    await press_visible(lambda value: value.startswith("task:step:days:"))
    await press_visible(lambda value: value == "task:step:online")
    await open_preview()

    original_edit_callbacks = {
        callback.rsplit(":", 1)[-1]: callback
        for callback in capture.callbacks
        if callback.startswith("task:edit:")
    }
    assert set(original_edit_callbacks) == {
        "tk",
        "cat",
        "ts",
        "sl",
        "rw",
        "ti",
        "ds",
        "cc",
        "mt",
        "dl",
        "fm",
    }

    async def edit(code: str) -> None:
        await press(original_edit_callbacks[code])
        assert capture.callback_answers[-1] == "Можно изменить пункт."

    async def finish_edit() -> None:
        assert "task:step:preview" in capture.callbacks
        await open_preview()

    await edit("tk")
    await press_visible(lambda value: value == "task:step:kind:group")
    await finish_edit()

    await edit("cat")
    await press_visible(lambda value: value.startswith("task:step:cat:"))
    await finish_edit()

    await edit("ts")
    await press_visible(lambda value: value == "task:step:size:m")
    await press_visible(lambda value: value == "task:step:reward:4")
    await finish_edit()

    await edit("sl")
    await press_visible(
        lambda value: value.startswith("task:step:slots:adjust:") and value.endswith(":1")
    )
    await press_visible(lambda value: value.startswith("task:step:slots:confirm:"))
    await finish_edit()

    await edit("rw")
    await press_visible(lambda value: value == "task:step:reward:5")
    await finish_edit()

    for code, value in (
        ("ti", "Обновлённое название"),
        ("ds", "Обновлённое описание задания."),
        ("cc", "Обновлённые критерии результата."),
        ("mt", "https://example.com/updated"),
    ):
        await edit(code)
        await answer(value)
        await finish_edit()

    await edit("dl")
    await press_visible(lambda value: value.startswith("task:step:days:"))
    await finish_edit()

    await edit("fm")
    await press_visible(lambda value: value == "task:step:online")
    await finish_edit()

    await edit("ds")
    await press(original_edit_callbacks["ti"])
    assert capture.callback_answers[-1] == (
        "Черновик уже изменился. Откройте его заново."  # noqa: RUF001
    )
    await answer("Финальное описание после проверки конфликта.")
    await finish_edit()

    draft = await TaskService(database.unit_of_work).current(
        actor_telegram_user_id=author.telegram_user_id
    )
    assert draft is not None
    assert draft.current_step is TaskDraftStep.PREVIEW
    assert draft.performer_slots == 8
    assert draft.credit_reward_per_performer == 5
    assert draft.title == "Обновлённое название"
    assert draft.description == "Финальное описание после проверки конфликта."
    assert draft.completion_criteria == "Обновлённые критерии результата."
    assert draft.materials == {"text": "https://example.com/updated"}
    assert all(len(value.encode()) <= 64 for value in capture.callbacks)
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

    await send_message(81_320, author.telegram_user_id, MY_TASKS_COMMAND)
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
    await send_message(81_323, author.telegram_user_id, MY_TASKS_COMMAND)
    assert not any(value.startswith("task:cancel:ask:") for value in capture.callbacks)
    await bot.session.close()
    await database.dispose()


async def test_old_owned_task_callback_survives_more_than_twenty_newer_tasks(
    database_url: str,
) -> None:
    """An already rendered card remains addressable after it leaves the first page."""
    database = Database(database_url)
    admin = await _member(database, 81_351, MemberRole.ADMINISTRATOR)
    author = await _member(database, 81_352)
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
    oldest = await _published_task(database, author, template_id, update_id_base=81_360)
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    send_message, send_callback = _transport(
        dispatcher,
        bot,
        _actors(author.telegram_user_id),
    )
    await send_message(81_370, author.telegram_user_id, MY_TASKS_COMMAND)
    old_expand = _visible_on_text(
        capture,
        lambda text: oldest.title in text,
        lambda value: value.startswith("task:view:open:"),
    )

    async with sessions.begin() as session:
        source = await session.get(TaskModel, oldest.id)
        assert source is not None
        excluded = {"id", "title", "publish_command_id", "created_at", "updated_at"}
        source_values = {
            column.name: getattr(source, column.name)
            for column in TaskModel.__table__.columns
            if column.name not in excluded
        }
        for index in range(20):
            created_at = source.created_at + datetime.timedelta(seconds=index + 1)
            session.add(
                TaskModel(
                    **source_values,
                    id=uuid4(),
                    title=f"Newer task {index}",
                    publish_command_id=uuid4(),
                    created_at=created_at,
                    updated_at=created_at,
                )
            )

    capture.texts.clear()
    await send_callback(81_371, author.telegram_user_id, old_expand)
    assert any(text.startswith(oldest.title) and "Описание:" in text for text in capture.texts)
    await bot.session.close()
    await database.dispose()


async def test_performer_declines_creator_cancellation_and_task_stays_active(
    database_url: str,
) -> None:
    """A pending request blocks acceptance; a decline preserves task and assignment."""
    database = Database(database_url)
    admin = await _member(database, 81_401, MemberRole.ADMINISTRATOR)
    author = await _member(database, 81_402)
    performer = await _member(database, 81_403)
    outsider = await _member(database, 81_404)
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
    task = await _published_task(database, author, template_id, update_id_base=81_410)
    assignments = AssignmentService(database.unit_of_work)
    assignment = await assignments.accept(
        AcceptAssignmentCommand(81_420, performer.telegram_user_id, task.id)
    )
    tasks = TaskService(database.unit_of_work)
    requested = await tasks.request_cancellation(
        update_id=81_421,
        actor_telegram_user_id=author.telegram_user_id,
        task_id=task.id,
    )
    assert requested.status == "pending"
    with pytest.raises(AssignmentError, match="awaiting cancellation responses"):
        await assignments.accept(
            AcceptAssignmentCommand(81_422, outsider.telegram_user_id, task.id)
        )
    async with sessions() as session:
        response_id = await session.scalar(select(TaskCancellationResponseModel.id))
    assert response_id is not None
    declined = await tasks.respond_cancellation(
        update_id=81_423,
        actor_telegram_user_id=performer.telegram_user_id,
        response_id=response_id,
        accepted=False,
    )
    assert declined.status == "declined"
    async with sessions() as session:
        stored_task = await session.get(TaskModel, task.id)
        stored_assignment = await session.get(AssignmentModel, assignment.id)
    assert stored_task is not None
    assert stored_task.status == TaskStatus.CLOSED_FOR_NEW_PERFORMERS.value
    assert stored_assignment is not None
    assert stored_assignment.status == "accepted"
    with pytest.raises(TaskError, match="current state"):
        await tasks.request_cancellation(
            update_id=81_424,
            actor_telegram_user_id=author.telegram_user_id,
            task_id=task.id,
        )
    await database.dispose()


async def test_accept_and_creator_cancel_are_serialized_in_both_orders(
    database_url: str,
) -> None:
    """The shared PostgreSQL task gate prevents a cancelled occupied task."""
    database = Database(database_url)
    admin = await _member(database, 81_501, MemberRole.ADMINISTRATOR)
    author = await _member(database, 81_502)
    performer = await _member(database, 81_503)
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
    cancel_first = await _published_task(database, author, template_id, update_id_base=81_510)
    accept_first = await _published_task(database, author, template_id, update_id_base=81_530)
    tasks = TaskService(database.unit_of_work)
    assignments = AssignmentService(database.unit_of_work)

    async with database.unit_of_work() as gate:
        await gate.acquire_assignment_task_gate(cancel_first.id)
        cancel_operation = asyncio.create_task(
            tasks.request_cancellation(
                update_id=81_550,
                actor_telegram_user_id=author.telegram_user_id,
                task_id=cancel_first.id,
            )
        )
        await asyncio.sleep(0.05)
        accept_operation = asyncio.create_task(
            assignments.accept(
                AcceptAssignmentCommand(81_551, performer.telegram_user_id, cancel_first.id)
            )
        )
        await gate.commit()
    cancel_result, accept_result = await asyncio.gather(
        cancel_operation, accept_operation, return_exceptions=True
    )
    assert isinstance(cancel_result, TaskCancellationOutcome)
    assert cancel_result.status == "cancelled"
    assert isinstance(accept_result, TaskError)

    async with database.unit_of_work() as gate:
        await gate.acquire_assignment_task_gate(accept_first.id)
        accepted_operation = asyncio.create_task(
            assignments.accept(
                AcceptAssignmentCommand(81_552, performer.telegram_user_id, accept_first.id)
            )
        )
        await asyncio.sleep(0.05)
        requested_operation = asyncio.create_task(
            tasks.request_cancellation(
                update_id=81_553,
                actor_telegram_user_id=author.telegram_user_id,
                task_id=accept_first.id,
            )
        )
        await gate.commit()
    accepted_result, requested_result = await asyncio.gather(
        accepted_operation, requested_operation
    )
    assert accepted_result.task_id == accept_first.id
    assert requested_result.status == "pending"
    async with sessions() as session:
        first_task = await session.get(TaskModel, cancel_first.id)
        second_task = await session.get(TaskModel, accept_first.id)
        second_assignment = await session.get(AssignmentModel, accepted_result.id)
    assert first_task is not None
    assert first_task.status == "cancelled"
    assert second_task is not None
    assert second_task.status == TaskStatus.CLOSED_FOR_NEW_PERFORMERS.value
    assert second_assignment is not None
    assert second_assignment.status == "accepted"
    await database.dispose()


async def test_multislot_cancellation_waits_for_every_performer_and_replays(
    database_url: str,
) -> None:
    """Partial consent changes no assignment; the final consent settles exactly once."""
    database = Database(database_url)
    admin = await _member(database, 81_601, MemberRole.ADMINISTRATOR)
    author = await _member(database, 81_602)
    first = await _member(database, 81_603)
    second = await _member(database, 81_604)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    await EconomyService(database.unit_of_work).apply_one(starting_grant(author.id))
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        source = await session.scalar(
            select(TaskTemplateModel).where(TaskTemplateModel.code == "repository_first_impression")
        )
        assert source is not None
        template = TaskTemplateModel(
            id=uuid4(),
            category_id=source.category_id,
            code=f"multislot-cancellation-{uuid4().hex}",
            version=1,
            name=source.name,
            description=source.description,
            creator_instructions=source.creator_instructions,
            performer_instructions=source.performer_instructions,
            completion_criteria=source.completion_criteria,
            input_schema_json=source.input_schema_json,
            result_schema_json=source.result_schema_json,
            credit_reward=source.credit_reward,
            estimated_minutes=source.estimated_minutes,
            format=source.format,
            minimum_level=source.minimum_level,
            maximum_performers=2,
            moderation_required=source.moderation_required,
            is_active=True,
        )
        session.add(template)
        template_id = template.id
    task = await _published_task(
        database,
        author,
        template_id,
        update_id_base=81_610,
        performer_slots=2,
    )
    assignments = AssignmentService(database.unit_of_work)
    await assignments.accept(AcceptAssignmentCommand(81_620, first.telegram_user_id, task.id))
    await assignments.accept(AcceptAssignmentCommand(81_621, second.telegram_user_id, task.id))
    tasks = TaskService(database.unit_of_work)
    request = await tasks.request_cancellation(
        update_id=81_622,
        actor_telegram_user_id=author.telegram_user_id,
        task_id=task.id,
    )
    replayed_request = await tasks.request_cancellation(
        update_id=81_622,
        actor_telegram_user_id=author.telegram_user_id,
        task_id=task.id,
    )
    assert replayed_request == request
    async with sessions() as session:
        response_rows = (
            await session.execute(
                select(
                    TaskCancellationResponseModel.performer_id,
                    TaskCancellationResponseModel.id,
                )
            )
        ).all()
    responses = {row[0]: row[1] for row in response_rows}
    partial = await tasks.respond_cancellation(
        update_id=81_623,
        actor_telegram_user_id=first.telegram_user_id,
        response_id=responses[first.id],
        accepted=True,
    )
    replayed_partial = await tasks.respond_cancellation(
        update_id=81_623,
        actor_telegram_user_id=first.telegram_user_id,
        response_id=responses[first.id],
        accepted=True,
    )
    assert partial.status == "pending"
    assert replayed_partial == partial
    async with sessions() as session:
        before_final = await session.get(TaskModel, task.id)
        active_before_final = await session.scalar(
            select(func.count())
            .select_from(AssignmentModel)
            .where(AssignmentModel.task_id == task.id, AssignmentModel.status == "accepted")
        )
    assert before_final is not None
    assert before_final.status == TaskStatus.CLOSED_FOR_NEW_PERFORMERS.value
    assert active_before_final == 1
    final = await tasks.respond_cancellation(
        update_id=81_624,
        actor_telegram_user_id=second.telegram_user_id,
        response_id=responses[second.id],
        accepted=True,
    )
    replayed_final = await tasks.respond_cancellation(
        update_id=81_624,
        actor_telegram_user_id=second.telegram_user_id,
        response_id=responses[second.id],
        accepted=True,
    )
    assert final.status == "cancelled"
    assert replayed_final == final
    async with sessions() as session:
        cancelled_assignments = await session.scalar(
            select(func.count())
            .select_from(AssignmentModel)
            .where(AssignmentModel.task_id == task.id, AssignmentModel.status == "cancelled")
        )
        creator_events = await session.scalar(
            select(func.count())
            .select_from(ReliabilityEventModel)
            .where(ReliabilityEventModel.event_type == "cancelled_creator")
        )
        creator_event_actors = set(
            await session.scalars(
                select(ReliabilityEventModel.actor_member_id).where(
                    ReliabilityEventModel.event_type == "cancelled_creator"
                )
            )
        )
    assert cancelled_assignments == 2
    assert creator_events == 2
    assert creator_event_actors == {author.id}
    await database.dispose()


async def test_result_submission_obsoletes_pending_cancellation(
    database_url: str,
) -> None:
    """A result that wins the task gate prevents later consent from cancelling work."""
    database = Database(database_url)
    admin = await _member(database, 81_701, MemberRole.ADMINISTRATOR)
    author = await _member(database, 81_702)
    performer = await _member(database, 81_703)
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
    task = await _published_task(database, author, template_id, update_id_base=81_710)
    assignments = AssignmentService(database.unit_of_work)
    assignment = await assignments.accept(
        AcceptAssignmentCommand(81_720, performer.telegram_user_id, task.id)
    )
    tasks = TaskService(database.unit_of_work)
    await tasks.request_cancellation(
        update_id=81_721,
        actor_telegram_user_id=author.telegram_user_id,
        task_id=task.id,
    )
    async with sessions() as session:
        response_id = await session.scalar(select(TaskCancellationResponseModel.id))
    assert response_id is not None
    await assignments.submit(
        SubmitResultCommand(
            81_722,
            performer.telegram_user_id,
            assignment.id,
            uuid4(),
            {
                "summary": "Работа начата и результат подготовлен.",
                "findings": ["Проверен основной пользовательский путь."],
                "evidence": [],
            },
        )
    )
    obsolete = await tasks.respond_cancellation(
        update_id=81_723,
        actor_telegram_user_id=performer.telegram_user_id,
        response_id=response_id,
        accepted=True,
    )
    replayed = await tasks.respond_cancellation(
        update_id=81_723,
        actor_telegram_user_id=performer.telegram_user_id,
        response_id=response_id,
        accepted=True,
    )
    assert obsolete.status == "obsolete"
    assert obsolete.reason == "work_started"
    assert replayed == obsolete
    async with sessions() as session:
        request = await session.scalar(select(TaskCancellationRequestModel))
        stored_assignment = await session.get(AssignmentModel, assignment.id)
        stored_task = await session.get(TaskModel, task.id)
    assert request is not None
    assert request.status == "obsolete"
    assert stored_assignment is not None
    assert stored_assignment.status == "submitted"
    assert stored_task is not None
    assert stored_task.status == TaskStatus.CLOSED_FOR_NEW_PERFORMERS.value
    await database.dispose()


async def test_deadline_blocks_new_request_and_makes_pending_response_obsolete(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither side may negotiate cancellation after the task deadline."""
    database = Database(database_url)
    admin = await _member(database, 81_801, MemberRole.ADMINISTRATOR)
    author = await _member(database, 81_802)
    performer = await _member(database, 81_803)
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
    pending_task = await _published_task(database, author, template_id, update_id_base=81_810)
    expired_free_task = await _published_task(database, author, template_id, update_id_base=81_820)
    assignments = AssignmentService(database.unit_of_work)
    await assignments.accept(
        AcceptAssignmentCommand(81_830, performer.telegram_user_id, pending_task.id)
    )
    tasks = TaskService(database.unit_of_work)
    requested = await tasks.request_cancellation(
        update_id=81_831,
        actor_telegram_user_id=author.telegram_user_id,
        task_id=pending_task.id,
    )
    async with sessions() as session:
        response_id = await session.scalar(
            select(TaskCancellationResponseModel.id).where(
                TaskCancellationResponseModel.request_id == requested.request_id
            )
        )
    assert response_id is not None
    latest_deadline = max(pending_task.deadline_at, expired_free_task.deadline_at)
    after_deadline = latest_deadline + datetime.timedelta(seconds=1)
    monkeypatch.setattr(task_application, "_utc_now", lambda: after_deadline)

    with pytest.raises(TaskError, match="deadline has passed"):
        await tasks.request_cancellation(
            update_id=81_832,
            actor_telegram_user_id=author.telegram_user_id,
            task_id=expired_free_task.id,
        )
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    send_message, send_callback = _transport(
        dispatcher,
        bot,
        _actors(author.telegram_user_id, performer.telegram_user_id),
    )
    await send_message(81_832_1, author.telegram_user_id, MY_TASKS_COMMAND)
    ask = _visible_on_text(
        capture,
        lambda text: expired_free_task.title in text,
        lambda value: value.startswith("task:cancel:ask:"),
    )
    await send_callback(81_832_2, author.telegram_user_id, ask)
    confirm = _visible_on_text(
        capture,
        lambda text: f"Отменить «{expired_free_task.title}»?" in text,
        lambda value: value.startswith("task:cancel:do:"),
    )
    await send_callback(81_832_3, author.telegram_user_id, confirm)
    assert capture.callback_answers[-1] == "Срок задания уже истёк. Отмена больше недоступна."
    obsolete = await tasks.respond_cancellation(
        update_id=81_833,
        actor_telegram_user_id=performer.telegram_user_id,
        response_id=response_id,
        accepted=True,
    )
    replayed = await tasks.respond_cancellation(
        update_id=81_833,
        actor_telegram_user_id=performer.telegram_user_id,
        response_id=response_id,
        accepted=True,
    )
    assert obsolete.status == "obsolete"
    assert obsolete.reason == "deadline_passed"
    assert replayed == obsolete
    async with sessions() as session:
        stored_request = await session.get(TaskCancellationRequestModel, requested.request_id)
        stored_response = await session.get(TaskCancellationResponseModel, response_id)
    assert stored_request is not None
    assert stored_request.status == "obsolete"
    assert stored_request.resolution_reason == "deadline_passed"
    assert stored_response is not None
    assert stored_response.status == "obsolete"
    await bot.session.close()
    await database.dispose()


async def test_performer_self_cancel_obsoletes_request_then_author_cancels_free_task(
    database_url: str,
) -> None:
    """A vacated slot turns a pending negotiation into an immediate creator cancellation."""
    database = Database(database_url)
    admin = await _member(database, 81_901, MemberRole.ADMINISTRATOR)
    author = await _member(database, 81_902)
    performer = await _member(database, 81_903)
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
    task = await _published_task(database, author, template_id, update_id_base=81_910)
    assignments = AssignmentService(database.unit_of_work)
    assignment = await assignments.accept(
        AcceptAssignmentCommand(81_920, performer.telegram_user_id, task.id)
    )
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    send_message, send_callback = _transport(
        dispatcher,
        bot,
        _actors(author.telegram_user_id, performer.telegram_user_id),
    )
    await send_message(81_920_1, author.telegram_user_id, MY_TASKS_COMMAND)
    request_button = _visible_on_text(
        capture,
        lambda text: task.title in text,
        lambda value: value.startswith("task:cancel:ask:"),
    )
    await send_callback(81_920_2, author.telegram_user_id, request_button)
    confirm_button = _visible_on_text(
        capture,
        lambda text: "Завершить набор" in text,
        lambda value: value.startswith("task:cancel:req:"),
    )
    tasks = TaskService(database.unit_of_work)
    requested = await tasks.request_cancellation(
        update_id=81_921,
        actor_telegram_user_id=author.telegram_user_id,
        task_id=task.id,
    )
    await assignments.cancel(
        update_id=81_922,
        actor_telegram_user_id=performer.telegram_user_id,
        assignment_id=assignment.id,
        reason="Cannot start the work.",
    )
    await send_callback(81_923, author.telegram_user_id, confirm_button)
    assert capture.callback_answers[-1] == "Задание отменено."
    assert any("возвращены в доступный баланс" in text for text in capture.texts)
    async with sessions() as session:
        stored_request = await session.get(TaskCancellationRequestModel, requested.request_id)
        stored_task = await session.get(TaskModel, task.id)
        cancellation_audits = await session.scalar(
            select(func.count())
            .select_from(AuditEventModel)
            .where(
                AuditEventModel.entity_id == str(task.id),
                AuditEventModel.action == "task_cancelled",
                AuditEventModel.actor_member_id == author.id,
            )
        )
    assert stored_request is not None
    assert stored_request.status == "obsolete"
    assert stored_request.resolution_reason == "assignment_cancelled"
    assert stored_task is not None
    assert stored_task.status == "cancelled"
    assert cancellation_audits == 1
    await bot.session.close()
    await database.dispose()


async def test_last_cancellation_consent_and_draft_confirmation_serialize_both_orders(  # noqa: PLR0915
    database_url: str,
) -> None:
    """A partially approved multislot request has one atomic final winner."""
    database = Database(database_url)
    admin = await _member(database, 82_001, MemberRole.ADMINISTRATOR)
    author = await _member(database, 82_002)
    first_performer = await _member(database, 82_003)
    last_performer = await _member(database, 82_004)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    await EconomyService(database.unit_of_work).apply_one(starting_grant(author.id))
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        source = await session.scalar(
            select(TaskTemplateModel).where(TaskTemplateModel.code == "repository_first_impression")
        )
        assert source is not None
        template = TaskTemplateModel(
            id=uuid4(),
            category_id=source.category_id,
            code=f"multislot-race-{uuid4().hex}",
            version=1,
            name=source.name,
            description=source.description,
            creator_instructions=source.creator_instructions,
            performer_instructions=source.performer_instructions,
            completion_criteria=source.completion_criteria,
            input_schema_json=source.input_schema_json,
            result_schema_json=source.result_schema_json,
            credit_reward=source.credit_reward,
            estimated_minutes=source.estimated_minutes,
            format=source.format,
            minimum_level=source.minimum_level,
            maximum_performers=2,
            moderation_required=source.moderation_required,
            is_active=True,
        )
        session.add(template)
        template_id = template.id
    tasks = TaskService(database.unit_of_work)
    assignments = AssignmentService(database.unit_of_work)

    async def prepared_case(
        update_base: int,
    ) -> tuple[PublishedTask, SubmissionDraft, Assignment, Assignment, UUID, UUID]:
        task = await _published_task(
            database,
            author,
            template_id,
            update_id_base=update_base,
            performer_slots=2,
        )
        first_assignment = await assignments.accept(
            AcceptAssignmentCommand(update_base + 10, first_performer.telegram_user_id, task.id)
        )
        last_assignment = await assignments.accept(
            AcceptAssignmentCommand(update_base + 11, last_performer.telegram_user_id, task.id)
        )
        draft = await assignments.begin_submission(
            BeginSubmissionCommand(
                update_base + 12, last_performer.telegram_user_id, last_assignment.id
            )
        )
        draft = await assignments.save_submission_draft(
            SaveSubmissionDraftCommand(
                update_base + 13,
                last_performer.telegram_user_id,
                draft.id,
                draft.revision,
                {
                    "summary": "Подготовлен подробный результат для проверки задания.",
                    "findings": ["Проверен основной пользовательский путь."],
                    "evidence": [],
                },
            )
        )
        request = await tasks.request_cancellation(
            update_id=update_base + 14,
            actor_telegram_user_id=author.telegram_user_id,
            task_id=task.id,
        )
        assert request.request_id is not None
        async with sessions() as session:
            response_rows = (
                await session.execute(
                    select(
                        TaskCancellationResponseModel.performer_id,
                        TaskCancellationResponseModel.id,
                    ).where(TaskCancellationResponseModel.request_id == request.request_id)
                )
            ).all()
        response_ids = {row[0]: row[1] for row in response_rows}
        partial = await tasks.respond_cancellation(
            update_id=update_base + 15,
            actor_telegram_user_id=first_performer.telegram_user_id,
            response_id=response_ids[first_performer.id],
            accepted=True,
        )
        assert partial.status == "pending"
        return (
            task,
            draft,
            first_assignment,
            last_assignment,
            request.request_id,
            response_ids[last_performer.id],
        )

    (
        cancel_first_task,
        cancel_first_draft,
        cancel_first_assignment,
        cancel_last_assignment,
        cancel_request_id,
        cancel_last_response,
    ) = await prepared_case(82_010)
    assert cancel_request_id is not None
    async with database.unit_of_work() as gate:
        await gate.acquire_assignment_task_gate(cancel_first_task.id)
        cancellation = asyncio.create_task(
            tasks.respond_cancellation(
                update_id=82_030,
                actor_telegram_user_id=last_performer.telegram_user_id,
                response_id=cancel_last_response,
                accepted=True,
            )
        )
        await asyncio.sleep(0.05)
        confirmation = asyncio.create_task(
            assignments.confirm_submission_draft(
                ConfirmSubmissionDraftCommand(
                    82_031,
                    last_performer.telegram_user_id,
                    cancel_first_draft.id,
                    cancel_first_draft.revision,
                )
            )
        )
        await gate.commit()
    cancellation_result, confirmation_result = await asyncio.gather(
        cancellation, confirmation, return_exceptions=True
    )
    assert isinstance(cancellation_result, TaskCancellationOutcome)
    assert cancellation_result.status == "cancelled"
    assert isinstance(confirmation_result, AssignmentError)

    (
        submit_first_task,
        submit_first_draft,
        submit_first_assignment,
        submit_last_assignment,
        submit_request_id,
        submit_last_response,
    ) = await prepared_case(82_100)
    assert submit_request_id is not None
    async with database.unit_of_work() as gate:
        await gate.acquire_assignment_task_gate(submit_first_task.id)
        confirmation = asyncio.create_task(
            assignments.confirm_submission_draft(
                ConfirmSubmissionDraftCommand(
                    82_130,
                    last_performer.telegram_user_id,
                    submit_first_draft.id,
                    submit_first_draft.revision,
                )
            )
        )
        await asyncio.sleep(0.05)
        cancellation = asyncio.create_task(
            tasks.respond_cancellation(
                update_id=82_131,
                actor_telegram_user_id=last_performer.telegram_user_id,
                response_id=submit_last_response,
                accepted=True,
            )
        )
        await gate.commit()
    confirmation_result, cancellation_result = await asyncio.gather(
        confirmation, cancellation, return_exceptions=True
    )
    assert getattr(confirmation_result, "version", None) == 1
    assert isinstance(cancellation_result, TaskCancellationOutcome)
    assert cancellation_result.status == "obsolete"
    assert cancellation_result.reason == "work_started"

    cancel_assignment_ids = {cancel_first_assignment.id, cancel_last_assignment.id}
    submit_assignment_ids = {submit_first_assignment.id, submit_last_assignment.id}
    async with sessions() as session:
        stored_tasks = {
            item.id: item
            for item in await session.scalars(
                select(TaskModel).where(
                    TaskModel.id.in_((cancel_first_task.id, submit_first_task.id))
                )
            )
        }
        stored_assignments = {
            item.id: item
            for item in await session.scalars(
                select(AssignmentModel).where(
                    AssignmentModel.id.in_(cancel_assignment_ids | submit_assignment_ids)
                )
            )
        }
        stored_requests = {
            item.id: item
            for item in await session.scalars(
                select(TaskCancellationRequestModel).where(
                    TaskCancellationRequestModel.id.in_((cancel_request_id, submit_request_id))
                )
            )
        }
        stored_responses = {
            (item.request_id, item.performer_id): item.status
            for item in await session.scalars(
                select(TaskCancellationResponseModel).where(
                    TaskCancellationResponseModel.request_id.in_(
                        (cancel_request_id, submit_request_id)
                    )
                )
            )
        }
        refund_rows = (
            await session.execute(
                select(
                    AccountTransactionModel.idempotency_key,
                    func.count(),
                    func.sum(AccountTransactionModel.credit_delta),
                )
                .where(
                    AccountTransactionModel.idempotency_key.in_(
                        (
                            (
                                f"task_cancel:{cancel_first_task.id}:"
                                f"{cancel_first_assignment.id}:refund"
                            ),
                            (
                                f"task_cancel:{cancel_first_task.id}:"
                                f"{cancel_last_assignment.id}:refund"
                            ),
                            (
                                f"task_cancel:{submit_first_task.id}:"
                                f"{submit_first_assignment.id}:refund"
                            ),
                            (
                                f"task_cancel:{submit_first_task.id}:"
                                f"{submit_last_assignment.id}:refund"
                            ),
                        )
                    ),
                    AccountTransactionModel.transaction_type == "task_reward_refunded",
                )
                .group_by(AccountTransactionModel.idempotency_key)
            )
        ).all()
        refund_by_key = {row[0]: (row[1], row[2]) for row in refund_rows}
        cancellation_audits = (
            await session.scalars(
                select(AuditEventModel).where(
                    AuditEventModel.action == "task_cancelled_by_consent",
                    AuditEventModel.entity_id.in_(
                        (str(cancel_first_task.id), str(submit_first_task.id))
                    ),
                )
            )
        ).all()
        reliability_rows = (
            await session.execute(
                select(
                    ReliabilityEventModel.assignment_id,
                    ReliabilityEventModel.event_type,
                    ReliabilityEventModel.actor_member_id,
                ).where(
                    ReliabilityEventModel.assignment_id.in_(
                        cancel_assignment_ids | submit_assignment_ids
                    ),
                    ReliabilityEventModel.event_type.in_(
                        ("cancelled_creator", "cancelled_performer")
                    ),
                )
            )
        ).all()
        cancel_outbox = await session.scalar(
            select(func.count())
            .select_from(OutboxEventModel)
            .where(
                OutboxEventModel.event_type == "task.cancelled",
                OutboxEventModel.aggregate_id == cancel_first_task.id,
            )
        )
        submit_cancel_outbox = await session.scalar(
            select(func.count())
            .select_from(OutboxEventModel)
            .where(
                OutboxEventModel.event_type == "task.cancelled",
                OutboxEventModel.aggregate_id == submit_first_task.id,
            )
        )
        submit_outbox = await session.scalar(
            select(func.count())
            .select_from(OutboxEventModel)
            .where(
                OutboxEventModel.event_type == "assignment_submitted",
                OutboxEventModel.aggregate_id == submit_last_assignment.id,
            )
        )
        cancel_receipt = await session.get(ProcessedTelegramUpdateModel, 82_030)
        failed_confirmation_receipt = await session.get(ProcessedTelegramUpdateModel, 82_031)
        submit_receipt = await session.get(ProcessedTelegramUpdateModel, 82_130)
        obsolete_receipt = await session.get(ProcessedTelegramUpdateModel, 82_131)

    assert stored_tasks[cancel_first_task.id].status == "cancelled"
    assert stored_tasks[submit_first_task.id].status == TaskStatus.CLOSED_FOR_NEW_PERFORMERS.value
    assert {stored_assignments[item].status for item in cancel_assignment_ids} == {"cancelled"}
    assert stored_assignments[submit_first_assignment.id].status == "cancelled"
    assert stored_assignments[submit_last_assignment.id].status == "submitted"
    assert stored_requests[cancel_request_id].status == "completed"
    assert stored_requests[submit_request_id].status == "obsolete"
    assert stored_requests[submit_request_id].resolution_reason == "work_started"
    assert stored_responses == {
        (cancel_request_id, first_performer.id): "accepted",
        (cancel_request_id, last_performer.id): "accepted",
        (submit_request_id, first_performer.id): "accepted",
        (submit_request_id, last_performer.id): "obsolete",
    }
    assert refund_by_key == {
        f"task_cancel:{cancel_first_task.id}:{cancel_first_assignment.id}:refund": (
            1,
            cancel_first_task.credit_reward_per_performer,
        ),
        f"task_cancel:{cancel_first_task.id}:{cancel_last_assignment.id}:refund": (
            1,
            cancel_first_task.credit_reward_per_performer,
        ),
        f"task_cancel:{submit_first_task.id}:{submit_first_assignment.id}:refund": (
            1,
            submit_first_task.credit_reward_per_performer,
        ),
    }
    assert len(cancellation_audits) == 1
    assert cancellation_audits[0].entity_id == str(cancel_first_task.id)
    assert cancellation_audits[0].actor_member_id == last_performer.id
    assert {row[0] for row in reliability_rows} == (
        cancel_assignment_ids | {submit_first_assignment.id}
    )
    assert {row[1] for row in reliability_rows} == {"cancelled_creator"}
    assert {row[2] for row in reliability_rows} == {author.id}
    assert cancel_outbox == 1
    assert submit_cancel_outbox == 0
    assert submit_outbox == 1
    assert cancel_receipt is not None
    assert cancel_receipt.outcome_code == (
        f"task_cancelled:{cancel_first_task.id}:{cancel_request_id}"
    )
    assert failed_confirmation_receipt is None
    assert submit_receipt is not None
    assert submit_receipt.outcome_code.startswith("result:")
    assert obsolete_receipt is not None
    assert obsolete_receipt.outcome_code == (
        f"task_cancel_obsolete:{submit_first_task.id}:{submit_request_id}:work_started"
    )
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


async def _complete_freeform_creation(  # noqa: PLR0913
    capture: CapturingSession,
    send_message: MessageSender,
    send_callback: CallbackSender,
    *,
    update_base: int,
    actor_id: int,
    title: str,
    details: str,
    criteria: str,
    materials: str,
    group_slots: int | None = None,
) -> None:
    next_update = update_base
    await _click(
        capture,
        send_callback,
        next_update,
        actor_id,
        "task:step:kind:group" if group_slots is not None else "task:step:kind:solo",
    )
    next_update += 1
    await _click(capture, send_callback, next_update, actor_id, "task:step:cat:")
    next_update += 1
    await _click(capture, send_callback, next_update, actor_id, "task:step:size:s")
    next_update += 1
    if group_slots is not None:
        if group_slots < 2:
            message = "Group slot count must be at least two."
            raise ValueError(message)
        remaining = group_slots - 2
        while remaining >= 5:
            callback = _visible(
                capture,
                lambda value: value.startswith("task:step:slots:adjust:") and value.endswith(":5"),
            )
            capture.callbacks.clear()
            await send_callback(next_update, actor_id, callback)
            remaining -= 5
            next_update += 1
        while remaining:
            callback = _visible(
                capture,
                lambda value: value.startswith("task:step:slots:adjust:") and value.endswith(":1"),
            )
            capture.callbacks.clear()
            await send_callback(next_update, actor_id, callback)
            remaining -= 1
            next_update += 1
        await _click(
            capture,
            send_callback,
            next_update,
            actor_id,
            "task:step:slots:confirm:",
        )
        next_update += 1
    await _click(capture, send_callback, next_update, actor_id, "task:step:reward:2")
    next_update += 1
    for answer in (title, details, criteria, materials):
        capture.callbacks.clear()
        await send_message(next_update, actor_id, answer)
        next_update += 1
    await _click(capture, send_callback, next_update, actor_id, "task:step:days:")
    next_update += 1
    await _click(capture, send_callback, next_update, actor_id, "task:step:online")
    next_update += 1
    await _click(capture, send_callback, next_update, actor_id, "task:step:preview")


async def test_community_journey_and_admin_surfaces_are_reachable(database_url: str) -> None:  # noqa: PLR0915
    """Publish and pay a community task through captured administrator and member buttons."""
    database = Database(database_url)
    creator = await _member(database, 82_001, MemberRole.ADMINISTRATOR)
    reviewer = await _member(database, 82_002, MemberRole.ADMINISTRATOR)
    performer = await _member(database, 82_003)
    resolver = await _member(database, 82_004, MemberRole.ADMINISTRATOR)
    appeal_resolver = await _member(database, 82_005, MemberRole.ADMINISTRATOR)
    superadministrator = await _member(
        database,
        82_006,
        MemberRole.ADMINISTRATOR,
        permissions=sorted(ADMINISTRATOR_PERMISSIONS | {SUPERADMINISTRATOR_PERMISSION}),
    )
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
        superadministrator.telegram_user_id,
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
    capture.reply_buttons.clear()
    await send_message(82_112, superadministrator.telegram_user_id, "/start")
    superadmin_button = next(value for value in capture.reply_buttons if value == ADMIN_TEXT)
    await send_message(82_113, superadministrator.telegram_user_id, superadmin_button)
    approvals = _visible(capture, lambda value: value == "nav:admin:community_approvals")
    capture.callbacks.clear()
    await send_callback(82_114, superadministrator.telegram_user_id, approvals)
    approve = _visible(capture, lambda value: value.startswith("task:approve:"))
    capture.callbacks.clear()
    await send_callback(82_115, superadministrator.telegram_user_id, approve)

    capture.callbacks.clear()
    await send_message(82_116, performer.telegram_user_id, FIND_TASK_COMMAND)
    await send_callback(
        82_117,
        performer.telegram_user_id,
        _visible(capture, lambda value: value.startswith("task:accept:")),
    )
    capture.callbacks.clear()
    await send_message(82_118, performer.telegram_user_id, ACCEPTED_TASKS_COMMAND)
    await send_callback(
        82_119,
        performer.telegram_user_id,
        _visible(capture, lambda value: value.startswith("as:a:s:")),
    )
    await send_message(
        82_120,
        performer.telegram_user_id,
        "Подготовил полный результат для задания сообщества и проверил детали.",
    )
    confirm = _visible(capture, lambda value: value.startswith("assign:submit:"))
    capture.callbacks.clear()
    await send_callback(82_121, performer.telegram_user_id, confirm)
    capture.callbacks.clear()
    await send_message(82_122, reviewer.telegram_user_id, MY_TASKS_COMMAND)
    full = _visible(capture, lambda value: value.endswith(":full"))
    capture.callbacks.clear()
    await send_callback(82_123, reviewer.telegram_user_id, full)

    capture.callbacks.clear()
    await send_message(82_124, creator.telegram_user_id, admin_button)
    moderation = _visible(capture, lambda value: value == "nav:admin:moderation")
    capture.callbacks.clear()
    await send_callback(82_125, creator.telegram_user_id, moderation)
    assert {"mod:list:fraud", "mod:list:alerts", "mod:list:sanctions"} <= set(capture.callbacks)

    fraud_list = _visible(capture, lambda value: value == "mod:list:fraud")
    capture.callbacks.clear()
    await send_callback(82_126, creator.telegram_user_id, fraud_list)
    open_fraud = _visible(capture, lambda value: value.startswith("mod:fraud:"))
    capture.callbacks.clear()
    await send_callback(82_127, creator.telegram_user_id, open_fraud)

    capture.reply_buttons.clear()
    await send_message(82_128, resolver.telegram_user_id, "/start")
    resolver_admin = next(value for value in capture.reply_buttons if value == ADMIN_TEXT)
    capture.callbacks.clear()
    await send_message(82_129, resolver.telegram_user_id, resolver_admin)
    resolver_moderation = _visible(capture, lambda value: value == "nav:admin:moderation")
    capture.callbacks.clear()
    await send_callback(82_130, resolver.telegram_user_id, resolver_moderation)
    fraud_resolution = _visible(
        capture,
        lambda value: value.startswith("mod:case:") and value.endswith(":fraud"),
    )
    capture.callbacks.clear()
    await send_callback(82_131, resolver.telegram_user_id, fraud_resolution)
    confirm_refund = _visible(capture, lambda value: value.startswith("mod:res:"))
    capture.callbacks.clear()
    await send_callback(82_132, resolver.telegram_user_id, confirm_refund)

    capture.callbacks.clear()
    await send_message(82_133, performer.telegram_user_id, ACCEPTED_TASKS_COMMAND)
    appeal = _visible(capture, lambda value: value.startswith("mod:appeal:"))
    capture.callbacks.clear()
    await send_callback(82_134, performer.telegram_user_id, appeal)

    capture.reply_buttons.clear()
    await send_message(82_135, appeal_resolver.telegram_user_id, "/start")
    appeal_admin = next(value for value in capture.reply_buttons if value == ADMIN_TEXT)
    capture.callbacks.clear()
    await send_message(82_136, appeal_resolver.telegram_user_id, appeal_admin)
    appeal_moderation = _visible(capture, lambda value: value == "nav:admin:moderation")
    capture.callbacks.clear()
    await send_callback(82_137, appeal_resolver.telegram_user_id, appeal_moderation)
    full_payment = _visible(
        capture,
        lambda value: value.startswith("mod:case:") and value.endswith(":pay"),
    )
    capture.callbacks.clear()
    await send_callback(82_138, appeal_resolver.telegram_user_id, full_payment)
    confirm_appeal = _visible(capture, lambda value: value.startswith("mod:res:"))
    capture.callbacks.clear()
    await send_callback(82_139, appeal_resolver.telegram_user_id, confirm_appeal)

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
    assert task.community_approved_by_admin_id == superadministrator.id
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
    creator = await _member(
        database,
        83_001,
        MemberRole.ADMINISTRATOR,
        permissions=sorted(ADMINISTRATOR_PERMISSIONS | {SUPERADMINISTRATOR_PERMISSION}),
    )
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
    await send_message(83_111, creator.telegram_user_id, MY_TASKS_COMMAND)
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
    open_target = _member_catalog_open(capture, target.display_name)
    capture.callbacks.clear()
    await send_callback(84_100_1, admin.telegram_user_id, open_target)
    begin_vote = _visible(capture, lambda value: value.startswith("karma:begin:"))
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
    open_target = _member_catalog_open(capture, target.display_name)
    capture.callbacks.clear()
    await send_callback(84_105_1, admin.telegram_user_id, open_target)
    raw_karma = _visible(capture, lambda value: value.startswith("karma:raw:"))
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
    open_target = _member_catalog_open(capture, target.display_name)
    capture.callbacks.clear()
    await send_callback(84_108_1, admin.telegram_user_id, open_target)
    restrict = _visible(capture, lambda value: value.startswith("mod:restrict:"))
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
    await send_message(86_100, performer.telegram_user_id, FIND_TASK_COMMAND)
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
    await send_message(86_102, performer.telegram_user_id, ACCEPTED_TASKS_COMMAND)
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
    async with restored.engine.connect() as connection:
        restored_task = (
            await connection.execute(
                select(
                    TaskModel.created_by_admin_id,
                    TaskModel.reviewer_admin_id,
                    TaskModel.safety_snapshot_json,
                ).where(TaskModel.id == task.id)
            )
        ).one()
    async with restored_sessions() as session:
        restored_assignment = await session.get(AssignmentModel, assignment.id)
        restored_transactions = tuple(
            await session.scalars(
                select(AccountTransactionModel.id)
                .where(AccountTransactionModel.assignment_id == assignment.id)
                .order_by(AccountTransactionModel.id)
            )
        )
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

    await send_message(85_100, performer.telegram_user_id, FIND_TASK_COMMAND)
    await _click(capture, send_callback, 85_101, performer.telegram_user_id, "task:accept:")
    capture.callbacks.clear()
    await send_message(85_102, performer.telegram_user_id, ACCEPTED_TASKS_COMMAND)
    await _click(capture, send_callback, 85_103, performer.telegram_user_id, "as:a:s:")
    await send_message(
        85_104,
        performer.telegram_user_id,
        "A complete result that the author can review through the visible card.",
    )
    await _click(capture, send_callback, 85_105, performer.telegram_user_id, "assign:submit:")

    capture.callbacks.clear()
    await send_message(85_106, reviewer.telegram_user_id, MY_TASKS_COMMAND)
    reject = _visible(capture, lambda value: value.endswith(":reject"))
    capture.callbacks.clear()
    await send_callback(85_107, reviewer.telegram_user_id, reject)

    capture.callbacks.clear()
    await send_message(85_108, performer.telegram_user_id, ACCEPTED_TASKS_COMMAND)
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
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        stored_creator = await session.get(MemberModel, creator.id)
        assert stored_creator is not None
        stored_creator.permissions_json = sorted(
            set(stored_creator.permissions_json) | {SUPERADMINISTRATOR_PERMISSION}
        )
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


def _member_catalog_open(capture: CapturingSession, display_name: str) -> str:
    for text, callback in capture.button_payloads:
        if not callback.startswith("mc:o:"):
            continue
        row_index = _member_catalog_row_index(text, display_name)
        if row_index is not None and callback.endswith(f":{row_index}"):
            return callback
    message = "Visible member catalog row was not found."
    raise LookupError(message)


def _member_catalog_row_index(text: str, display_name: str) -> int | None:
    for line in text.splitlines():
        if display_name not in line:
            continue
        raw_number = line.split(maxsplit=1)[0]
        if raw_number.isdecimal():
            return int(raw_number) - 1
    return None


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
