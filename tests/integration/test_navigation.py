from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast, override
from uuid import UUID, uuid4

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery
from aiogram.methods.get_me import GetMe
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.economy import EconomyService, ProductConfigBootstrapCoordinator
from community_bot.application.navigation import NavigationService
from community_bot.application.tasks import (
    AdvanceDraftCommand,
    PublishedTask,
    PublishTaskCommand,
    TaskService,
)
from community_bot.bootstrap.bot import _dispatcher
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.domain.catalog import TaskFormat
from community_bot.domain.economy import starting_grant
from community_bot.domain.members import (
    ADMINISTRATOR_PERMISSIONS,
    MemberRole,
)
from community_bot.domain.tasks import TaskDraftStep
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AssignmentModel,
    ConversationStateModel,
    InvitationModel,
    MemberModel,
    MemberSanctionModel,
    RegistrationApplicationModel,
    TaskCreationDraftModel,
    TaskModel,
    TaskTemplateModel,
)
from community_bot.transport.telegram.navigation import ADMIN_TEXT

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from aiogram.methods import TelegramMethod

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
CONFIG_PATH = Path(__file__).parents[2] / "config" / "product-config.v1.json"
TelegramType = TypeVar("TelegramType")


class CapturingSession(BaseSession):
    """Fake Bot API for the production-composed navigation scenario."""

    def __init__(self) -> None:
        """Initialize captured texts, callbacks, and reply buttons."""
        super().__init__()
        self.texts: list[str] = []
        self.text_payloads: list[tuple[str, object]] = []
        self.callbacks: list[str] = []
        self.callback_answers: list[str] = []
        self.button_payloads: list[tuple[str, str]] = []
        self.inline_buttons: list[tuple[str, str]] = []
        self.reply_buttons: list[str] = []

    async def close(self) -> None:
        """Close no external resources."""

    @override
    async def make_request(  # noqa: C901 - one fake Bot API capture boundary.
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,
    ) -> TelegramType:
        del bot, timeout
        text_value = getattr(method, "text", None)
        if isinstance(text_value, str):
            self.texts.append(text_value)
            self.text_payloads.append((text_value, getattr(method, "parse_mode", None)))
        markup = getattr(method, "reply_markup", None)
        if markup is not None and hasattr(markup, "inline_keyboard"):
            for row in markup.inline_keyboard:
                for button in row:
                    if button.callback_data is not None:
                        self.callbacks.append(button.callback_data)
                        self.inline_buttons.append((button.text, button.callback_data))
                        if isinstance(text_value, str):
                            self.button_payloads.append((text_value, button.callback_data))
        if markup is not None and hasattr(markup, "keyboard"):
            self.reply_buttons.extend(button.text for row in markup.keyboard for button in row)
        if isinstance(method, AnswerCallbackQuery):
            if method.text is not None:
                self.callback_answers.append(method.text)
            return cast("TelegramType", True)  # noqa: FBT003
        if isinstance(method, GetMe):
            return cast(
                "TelegramType",
                User(
                    id=123456,
                    is_bot=True,
                    first_name="HumanQuestBot",
                    username="humanquest_bot",
                ),
            )
        return cast(
            "TelegramType",
            Message(
                message_id=999,
                date=datetime.datetime.now(datetime.UTC),
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


async def _member(
    database: Database,
    telegram_user_id: int,
    role: MemberRole = MemberRole.MEMBER,
    *,
    permissions: list[str] | None = None,
) -> MemberModel:
    model = MemberModel(
        id=uuid4(),
        telegram_user_id=telegram_user_id,
        display_name=f"Member {telegram_user_id}",
        timezone="UTC",
        role=role.value,
        status="active",
        level_number=9,
        permissions_json=(
            permissions
            if permissions is not None
            else sorted(ADMINISTRATOR_PERMISSIONS)
            if role is MemberRole.ADMINISTRATOR
            else []
        ),
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add(model)
    return model


async def _submitted_member(database: Database, telegram_user_id: int) -> MemberModel:
    model = MemberModel(
        id=uuid4(),
        telegram_user_id=telegram_user_id,
        display_name="Pending member",
        city="Buenos Aires",
        timezone="America/Argentina/Buenos_Aires",
        short_bio="Помогаю проверять цифровые продукты.",
        current_goal="Делать сообщество полезнее.",
        availability="Два часа в неделю",
        help_categories_json=["Тестирование"],
        skill_tags_json=["Python"],
        role="member",
        status="pending",
        level_number=1,
        permissions_json=[],
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add(model)
        await session.flush()
        session.add_all(
            [
                RegistrationApplicationModel(
                    member_id=model.id,
                    status="submitted",
                    consented_at=datetime.datetime.now(datetime.UTC),
                    submitted_at=datetime.datetime.now(datetime.UTC),
                ),
                ConversationStateModel(
                    member_id=model.id,
                    flow_type="registration",
                    current_step="submitted",
                    payload_json={
                        "display_name": model.display_name,
                        "city": model.city,
                        "timezone": model.timezone,
                        "short_bio": model.short_bio,
                        "current_goal": model.current_goal,
                        "help_categories": model.help_categories_json,
                        "skill_tags": model.skill_tags_json,
                        "availability": model.availability,
                    },
                ),
            ]
        )
    return model


async def _published_task(
    database: Database,
    author: MemberModel,
    template_id: UUID,
    *,
    update_id_base: int = 60_000,
    performer_slots: int = 1,
) -> PublishedTask:
    service = TaskService(database.unit_of_work)
    draft = await service.start(
        update_id=update_id_base,
        actor_telegram_user_id=author.telegram_user_id,
        template_id=template_id,
    )
    assert draft is not None
    values: list[object] = [
        {
            "context": "Need a detailed and practical review.",
            "materials": "https://example.com/item",
            "constraints": "Do not publish private information.",
        },
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=2),
        (TaskFormat.ONLINE, None),
        {"url": "https://example.com/item"},
        performer_slots,
    ]
    current = draft
    for offset, (step, value) in enumerate(
        zip(
            [
                TaskDraftStep.INPUT,
                TaskDraftStep.DEADLINE,
                TaskDraftStep.FORMAT,
                TaskDraftStep.MATERIALS,
                TaskDraftStep.SLOTS,
            ],
            values,
            strict=True,
        ),
        start=1,
    ):
        current = await service.advance(
            AdvanceDraftCommand(
                update_id_base + offset,
                author.telegram_user_id,
                current.id,
                step,
                current.revision,
                value,
            )
        )
    preview = await service.preview(
        update_id=update_id_base + 6,
        actor_telegram_user_id=author.telegram_user_id,
        draft_id=current.id,
        expected_revision=current.revision,
    )
    publication = await service.publish(
        PublishTaskCommand(
            update_id_base + 7,
            author.telegram_user_id,
            preview.draft.id,
            preview.draft.revision,
        )
    )
    assert isinstance(publication, PublishedTask)
    return publication


async def test_production_navigation_requires_no_user_supplied_uuid(database_url: str) -> None:  # noqa: PLR0915
    database = Database(database_url)
    admin = await _member(database, 7_001, MemberRole.ADMINISTRATOR)
    author = await _member(database, 7_002)
    performer = await _member(database, 7_003)
    await _member(database, 7_004, MemberRole.MODERATOR)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    pending = await _submitted_member(database, 7_005)
    economy = EconomyService(database.unit_of_work)
    await economy.apply_one(starting_grant(author.id))
    await economy.apply_one(starting_grant(performer.id))
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as db_session:
        selected_template = await db_session.scalar(
            select(TaskTemplateModel.id).where(
                TaskTemplateModel.code == "repository_first_impression"
            )
        )
    assert selected_template is not None
    task = await _published_task(database, author, selected_template)

    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    session = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=session)
    users = {
        7_001: User(id=7_001, is_bot=False, first_name="Admin"),
        7_003: User(id=7_003, is_bot=False, first_name="Performer"),
        7_004: User(id=7_004, is_bot=False, first_name="Moderator"),
        7_005: User(id=7_005, is_bot=False, first_name="Applicant"),
    }

    def message_update(update_id: int, actor_id: int, text: str) -> Update:
        actor = users[actor_id]
        return Update(
            update_id=update_id,
            message=Message(
                message_id=update_id,
                date=datetime.datetime.now(datetime.UTC),
                chat=Chat(id=actor_id, type="private"),
                from_user=actor,
                text=text,
            ),
        )

    def callback_update(update_id: int, actor_id: int, data: str) -> Update:
        actor = users[actor_id]
        return Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=str(update_id),
                from_user=actor,
                chat_instance="navigation-test",
                data=data,
                message=Message(
                    message_id=update_id,
                    date=datetime.datetime.now(datetime.UTC),
                    chat=Chat(id=actor_id, type="private"),
                    from_user=actor,
                    text="button",
                ),
            ),
        )

    profile_callbacks = {
        "profile:edit:display_name",
        "profile:edit:city",
        "profile:edit:timezone",
        "profile:edit:short_bio",
        "profile:edit:current_goal",
        "profile:edit:help_categories",
        "profile:edit:skill_tags",
        "profile:edit:availability",
    }
    session.callbacks.clear()
    await dispatcher.feed_update(bot, message_update(69_001, 7_001, "/profile"))
    assert set(session.callbacks) == profile_callbacks
    await dispatcher.feed_update(bot, callback_update(69_002, 7_001, "profile:edit:city"))
    await dispatcher.feed_update(bot, message_update(69_003, 7_001, "Buenos Aires"))
    async with sessions() as db_session:
        stored_admin = await db_session.get(MemberModel, admin.id)
        assert stored_admin is not None
        assert stored_admin.city == "Buenos Aires"
        assert stored_admin.display_name == "Member 7001"

    session.callbacks.clear()
    await dispatcher.feed_update(bot, message_update(69_004, 7_003, "Моя карточка"))
    assert set(session.callbacks) == profile_callbacks

    await dispatcher.feed_update(bot, message_update(70_001, 7_003, "/start"))
    assert session.reply_buttons == [
        "Задания",
        "Участники",
        "Моя карточка",
        "Баланс и статистика",
        "Помощь",
        "Администрирование",
    ]
    session.texts.clear()
    await dispatcher.feed_update(bot, message_update(70_001_1, 7_003, "Найти задание"))
    assert session.texts == []

    session.inline_buttons.clear()
    await dispatcher.feed_update(bot, message_update(70_001_2, 7_003, "Баланс и статистика"))
    assert session.inline_buttons == [
        ("Баланс", "nav:menu:balance"),
        ("Статистика", "nav:menu:statistics"),
        ("Лидерборд", "nav:menu:leaderboard"),
        ("Назад", "nav:menu:root"),
    ]
    session.texts.clear()
    await dispatcher.feed_update(bot, callback_update(70_001_3, 7_003, "nav:menu:balance"))
    assert any("Баланс: 10 кредитов" in text for text in session.texts)

    session.texts.clear()
    await dispatcher.feed_update(
        bot,
        Update(
            update_id=70_000_1,
            message=Message(
                message_id=70_000_1,
                date=datetime.datetime.now(datetime.UTC),
                chat=Chat(id=-1007003, type="supergroup"),
                from_user=users[7_003],
                text="Задания",
            ),
        ),
    )
    assert session.texts == ["Задания доступны только в личном чате с ботом."]  # noqa: RUF001
    await dispatcher.feed_update(bot, callback_update(70_002, 7_003, "nav:tasks:not-a-uuid"))
    session.inline_buttons.clear()
    await dispatcher.feed_update(bot, message_update(70_003, 7_003, "Задания"))
    assert session.inline_buttons == [
        ("Найти", "nav:menu:find"),
        ("Создать", "nav:menu:create"),
        ("Мои задания", "nav:menu:mine"),
        ("Назад", "nav:menu:root"),
    ]
    session.inline_buttons.clear()
    await dispatcher.feed_update(bot, callback_update(70_003_1, 7_003, "nav:menu:mine"))
    assert session.inline_buttons == [
        ("Созданные мной", "nav:menu:created"),
        ("Взятые мной", "nav:menu:taken"),
        ("Назад", "nav:menu:tasks"),
    ]
    session.inline_buttons.clear()
    await dispatcher.feed_update(bot, callback_update(70_003_2, 7_003, "nav:menu:created"))
    assert session.inline_buttons == [
        ("Активные", "nav:menu:created:active"),
        ("Последние завершённые", "nav:menu:created:completed"),
        ("Архив", "nav:menu:created:archive"),
        ("Назад", "nav:menu:mine"),
    ]
    session.callbacks.clear()
    await dispatcher.feed_update(bot, callback_update(70_003_3, 7_003, "nav:menu:tasks"))
    await dispatcher.feed_update(bot, callback_update(70_003_4, 7_003, "nav:menu:find"))
    task_card = next(
        text for text, callback in session.button_payloads if callback == f"task:accept:{task.id}"
    )
    author_label = "\u0410\u0432\u0442\u043e\u0440"
    assert f"\n{author_label}: {author.display_name}\n" in task_card
    accept_callback = next(
        value for value in session.callbacks if value == f"task:accept:{task.id}"
    )
    await dispatcher.feed_update(
        bot,
        Update(
            update_id=70_003_5,
            callback_query=CallbackQuery(
                id="group-accept",
                from_user=users[7_003],
                chat_instance="group-navigation-test",
                data=accept_callback,
                message=Message(
                    message_id=70_003_5,
                    date=datetime.datetime.now(datetime.UTC),
                    chat=Chat(id=-1007003, type="supergroup"),
                    from_user=users[7_003],
                    text=task_card,
                ),
            ),
        ),
    )
    async with sessions() as db_session:
        assert await db_session.scalar(select(func.count()).select_from(AssignmentModel)) == 0
    await dispatcher.feed_update(bot, callback_update(70_004, 7_003, accept_callback))
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    await dispatcher.feed_update(bot, callback_update(70_004, 7_003, accept_callback))

    session.callbacks.clear()
    await dispatcher.feed_update(bot, callback_update(70_005, 7_003, "nav:menu:create"))
    await dispatcher.feed_update(bot, callback_update(70_006, 7_003, "nav:create:not-a-uuid"))
    create_callback = next(value for value in session.callbacks if value.startswith("nav:create:"))
    await dispatcher.feed_update(bot, callback_update(70_007, 7_003, create_callback))
    await dispatcher.feed_update(
        bot,
        message_update(
            70_008,
            7_003,
            '{"context":"Useful review","materials":"https://example.com",'
            '"constraints":"No private data"}',
        ),
    )
    await dispatcher.feed_update(bot, message_update(70_009, 7_003, "/balance"))
    await dispatcher.feed_update(bot, message_update(70_010, 7_003, "/help"))

    await dispatcher.feed_update(bot, message_update(70_011, 7_003, ADMIN_TEXT))
    await dispatcher.feed_update(bot, message_update(70_012, 7_004, "/admin"))
    await dispatcher.feed_update(bot, callback_update(70_013, 7_004, "nav:admin:invite"))
    session.reply_buttons.clear()
    session.callbacks.clear()
    await dispatcher.feed_update(bot, message_update(70_014, 7_001, "/start"))
    admin_button = next(value for value in session.reply_buttons if value == ADMIN_TEXT)
    await dispatcher.feed_update(bot, message_update(70_015, 7_001, admin_button))
    registration_list_callback = next(
        value for value in session.callbacks if value == "registration:list"
    )
    await dispatcher.feed_update(bot, callback_update(70_016, 7_001, registration_list_callback))
    approval_callback = next(
        value for value in session.callbacks if value == f"registration:approve:{pending.id}"
    )
    await dispatcher.feed_update(bot, callback_update(70_017, 7_001, approval_callback))
    await dispatcher.feed_update(bot, callback_update(70_017, 7_001, approval_callback))
    session.callbacks.clear()
    await dispatcher.feed_update(bot, message_update(70_021, 7_005, "/profile"))
    city_edit_callback = next(value for value in session.callbacks if value == "profile:edit:city")
    await dispatcher.feed_update(bot, callback_update(70_022, 7_005, city_edit_callback))
    await dispatcher.feed_update(bot, message_update(70_023, 7_005, "Mendoza"))
    await dispatcher.feed_update(bot, message_update(70_024, 7_001, "/admin"))
    await dispatcher.feed_update(bot, callback_update(70_025, 7_001, "nav:admin:invite"))
    await dispatcher.feed_update(bot, callback_update(70_025, 7_001, "nav:admin:invite"))
    await dispatcher.feed_update(bot, callback_update(70_026, 7_001, "nav:admin:moderation"))

    async with sessions() as db_session:
        assignment_count = await db_session.scalar(
            select(func.count()).select_from(AssignmentModel)
        )
        invite_count = await db_session.scalar(select(func.count()).select_from(InvitationModel))
        performer_draft = await db_session.scalar(
            select(TaskCreationDraftModel).where(TaskCreationDraftModel.creator_id == performer.id)
        )
        approved_member = await db_session.get(MemberModel, pending.id)
        approved_conversation = await db_session.get(ConversationStateModel, pending.id)
        grant_count = await db_session.scalar(
            select(func.count())
            .select_from(AccountTransactionModel)
            .where(
                AccountTransactionModel.member_id == pending.id,
                AccountTransactionModel.transaction_type == "starting_grant",
            )
        )
    assert assignment_count == 1
    assert invite_count == 1
    assert performer_draft is not None
    assert performer_draft.template_id == UUID(hex=create_callback.removeprefix("nav:create:"))
    assert performer_draft.current_step == "deadline"
    assert approved_member is not None
    assert approved_member.status == "active"
    assert approved_member.city == "Mendoza"
    assert approved_conversation is None
    assert grant_count == 1
    assert sum("Административное меню недоступно." in text for text in session.texts) == 1
    assert any("Очередь споров и расследований пуста." in text for text in session.texts)
    assert any("Баланс: 10 кредитов" in text for text in session.texts)
    assert any("Как пользоваться ботом" in text for text in session.texts)
    assert any("https://t.me/humanquest_bot?start=" in text for text in session.texts)
    invitation_payload = next(
        payload
        for payload in session.text_payloads
        if "https://t.me/humanquest_bot?start=" in payload[0]
    )
    assert invitation_payload[1] is None
    await bot.session.close()
    await database.dispose()


async def test_task_discovery_paginates_and_stale_cursor_restarts(database_url: str) -> None:
    database = Database(database_url)
    admin = await _member(database, 8_001, MemberRole.ADMINISTRATOR)
    author = await _member(database, 8_002)
    performer = await _member(database, 8_003)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    await EconomyService(database.unit_of_work).apply_one(starting_grant(author.id))
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as db_session:
        template = await db_session.scalar(
            select(TaskTemplateModel.id).where(
                TaskTemplateModel.code == "repository_first_impression"
            )
        )
    assert template is not None
    published = await _published_task(database, author, template)
    async with sessions.begin() as db_session:
        source = await db_session.get(TaskModel, published.id)
        assert source is not None
        for index in range(10):
            db_session.add(
                TaskModel(
                    id=uuid4(),
                    origin=source.origin,
                    template_id=source.template_id,
                    template_version=source.template_version,
                    creator_id=source.creator_id,
                    author_display_name=source.author_display_name,
                    category_id=source.category_id,
                    title=f"Task {index}",
                    description=source.description,
                    completion_criteria=source.completion_criteria,
                    materials_json=source.materials_json,
                    input_payload_json=source.input_payload_json,
                    credit_reward_per_performer=source.credit_reward_per_performer,
                    performer_slots=source.performer_slots,
                    reserved_credit_total=source.reserved_credit_total,
                    estimated_minutes=source.estimated_minutes,
                    minimum_level=source.minimum_level,
                    format=source.format,
                    city=source.city,
                    deadline_at=source.deadline_at,
                    status=source.status,
                    safety_snapshot_json=source.safety_snapshot_json,
                    publish_command_id=uuid4(),
                )
            )

    service = TaskService(database.unit_of_work)
    first = await service.list_available(actor_telegram_user_id=performer.telegram_user_id)
    assert len(first.items) == 10
    assert first.next_cursor_task_id is not None
    second = await service.list_available(
        actor_telegram_user_id=performer.telegram_user_id,
        cursor_task_id=first.next_cursor_task_id,
    )
    assert len(second.items) == 1
    assert {item.id for item in first.items}.isdisjoint(item.id for item in second.items)
    restarted = await service.list_available(
        actor_telegram_user_id=performer.telegram_user_id,
        cursor_task_id=uuid4(),
    )
    assert [item.id for item in restarted.items] == [item.id for item in first.items]
    assert first.next_cursor_task_id is not None
    async with sessions.begin() as db_session:
        cursor = await db_session.get(TaskModel, first.next_cursor_task_id)
        assert cursor is not None
        cursor.status = "cancelled"
    current_first = await service.list_available(actor_telegram_user_id=performer.telegram_user_id)
    existing_stale = await service.list_available(
        actor_telegram_user_id=performer.telegram_user_id,
        cursor_task_id=first.next_cursor_task_id,
    )
    assert [item.id for item in existing_stale.items] == [item.id for item in current_first.items]
    async with sessions.begin() as db_session:
        db_session.add_all(
            AssignmentModel(
                task_id=item.id,
                performer_id=performer.id,
                slot_number=1,
                status="accepted",
            )
            for item in current_first.items[:3]
        )
    at_limit = await service.list_available(actor_telegram_user_id=performer.telegram_user_id)
    assert at_limit.items == ()
    assert at_limit.next_cursor_task_id is None
    await database.dispose()


async def test_nested_task_history_limits_recent_and_paginates_archive(  # noqa: PLR0915
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await _member(database, 8_101, MemberRole.ADMINISTRATOR)
    author = await _member(database, 8_102)
    performer = await _member(database, 8_103)
    reviewer = await _member(database, 8_104, MemberRole.ADMINISTRATOR)
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )
    await EconomyService(database.unit_of_work).apply_one(starting_grant(author.id))
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as db_session:
        template = await db_session.scalar(
            select(TaskTemplateModel.id).where(
                TaskTemplateModel.code == "repository_first_impression"
            )
        )
    assert template is not None
    published = await _published_task(database, author, template, update_id_base=61_000)
    statuses = ["completed"] * 52 + ["partially_completed", "cancelled", "expired"]
    assignment_statuses = ["approved"] * 52 + [
        "partially_approved",
        "cancelled",
        "no_show",
    ]
    history_titles: set[str] = set()
    assignment_models: list[AssignmentModel] = []
    now = datetime.datetime.now(datetime.UTC)
    async with sessions.begin() as db_session:
        source = await db_session.get(TaskModel, published.id)
        assert source is not None
        db_session.add(
            TaskModel(
                id=uuid4(),
                origin="community",
                template_id=source.template_id,
                template_version=source.template_version,
                creator_id=None,
                created_by_admin_id=admin.id,
                reviewer_admin_id=reviewer.id,
                community_approved_by_admin_id=admin.id,
                author_display_name="Сообщество",
                category_id=source.category_id,
                title="Reviewer only",
                description=source.description,
                completion_criteria=source.completion_criteria,
                materials_json=source.materials_json,
                input_payload_json=source.input_payload_json,
                credit_reward_per_performer=source.credit_reward_per_performer,
                performer_slots=source.performer_slots,
                reserved_credit_total=0,
                estimated_minutes=source.estimated_minutes,
                minimum_level=source.minimum_level,
                format=source.format,
                city=source.city,
                deadline_at=source.deadline_at,
                status="completed",
                safety_snapshot_json=source.safety_snapshot_json,
                publish_command_id=uuid4(),
                created_at=now,
                updated_at=now,
            )
        )
        for index, (task_status, assignment_status) in enumerate(
            zip(statuses, assignment_statuses, strict=True)
        ):
            task_id = uuid4()
            title = f"History {index:02d}"
            history_titles.add(title)
            completion_at = now - datetime.timedelta(minutes=index + 1)
            created_at = now - datetime.timedelta(days=len(statuses) - index)
            db_session.add(
                TaskModel(
                    id=task_id,
                    origin=source.origin,
                    template_id=source.template_id,
                    template_version=source.template_version,
                    creator_id=source.creator_id,
                    author_display_name=source.author_display_name,
                    category_id=source.category_id,
                    title=title,
                    description=source.description,
                    completion_criteria=source.completion_criteria,
                    materials_json=source.materials_json,
                    input_payload_json=source.input_payload_json,
                    credit_reward_per_performer=source.credit_reward_per_performer,
                    performer_slots=source.performer_slots,
                    reserved_credit_total=source.reserved_credit_total,
                    estimated_minutes=source.estimated_minutes,
                    minimum_level=source.minimum_level,
                    format=source.format,
                    city=source.city,
                    deadline_at=source.deadline_at,
                    status=task_status,
                    safety_snapshot_json=source.safety_snapshot_json,
                    publish_command_id=uuid4(),
                    created_at=created_at,
                    updated_at=completion_at,
                )
            )
            assignment_models.append(
                AssignmentModel(
                    task_id=task_id,
                    performer_id=performer.id,
                    slot_number=1,
                    status=assignment_status,
                    accepted_at=created_at,
                    reviewed_at=(
                        completion_at
                        if assignment_status in {"approved", "partially_approved"}
                        else None
                    ),
                )
            )
        await db_session.flush()
        db_session.add_all(assignment_models)

    reviewer_cards = await TaskService(database.unit_of_work).list_owned_cards(
        actor_telegram_user_id=reviewer.telegram_user_id,
        creator_only=True,
    )
    assert reviewer_cards == ()

    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    session = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=session)
    users = {
        author.telegram_user_id: User(
            id=author.telegram_user_id,
            is_bot=False,
            first_name="Author",
        ),
        performer.telegram_user_id: User(
            id=performer.telegram_user_id,
            is_bot=False,
            first_name="Performer",
        ),
    }

    def callback_update(update_id: int, actor_id: int, data: str) -> Update:
        actor = users[actor_id]
        return Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=str(update_id),
                from_user=actor,
                chat_instance="history-test",
                data=data,
                message=Message(
                    message_id=update_id,
                    date=datetime.datetime.now(datetime.UTC),
                    chat=Chat(id=actor_id, type="private"),
                    from_user=actor,
                    text="Мои задания",
                ),
            ),
        )

    async def assert_history(*, actor_id: int, list_kind: str, update_id_base: int) -> None:
        session.texts.clear()
        session.callbacks.clear()
        session.button_payloads.clear()
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id_base,
                actor_id,
                f"nav:menu:{list_kind}:completed",
            ),
        )
        recent = {text.splitlines()[0] for text in session.texts if text.startswith("History ")}
        assert recent == {f"History {index:02d}" for index in range(10)}
        assert not any(value.startswith("nav:list:") for value in session.callbacks)

        session.texts.clear()
        session.callbacks.clear()
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id_base + 1,
                actor_id,
                f"nav:menu:{list_kind}:archive",
            ),
        )
        first_page = {text.splitlines()[0] for text in session.texts if text.startswith("History ")}
        assert len(first_page) == 10
        archive = set(first_page)
        page_number = 0
        while next_pages := [value for value in session.callbacks if value.startswith("nav:list:")]:
            page_number += 1
            session.callbacks.clear()
            await dispatcher.feed_update(
                bot,
                callback_update(update_id_base + 1 + page_number, actor_id, next_pages[-1]),
            )
            archive.update(
                text.splitlines()[0] for text in session.texts if text.startswith("History ")
            )
        assert archive == history_titles
        assert not any(value.startswith("nav:list:") for value in session.callbacks)

    await assert_history(
        actor_id=author.telegram_user_id,
        list_kind="created",
        update_id_base=71_100,
    )
    await assert_history(
        actor_id=performer.telegram_user_id,
        list_kind="taken",
        update_id_base=71_200,
    )
    old_assignment = next(
        callback
        for text, callback in session.button_payloads
        if text.startswith("History 00\n") and callback.startswith("as:view:open:")
    )
    session.texts.clear()
    await dispatcher.feed_update(
        bot,
        callback_update(71_300, performer.telegram_user_id, old_assignment),
    )
    assert any(text.startswith("History 00\n") and "Результат:" in text for text in session.texts)
    await bot.session.close()
    await database.dispose()


async def test_navigation_admin_gate_rejects_every_non_active_admin(database_url: str) -> None:
    database = Database(database_url)
    admin = await _member(database, 9_000, MemberRole.ADMINISTRATOR)
    member = await _member(database, 9_001)
    pending = await _member(database, 9_002, MemberRole.ADMINISTRATOR)
    restricted = await _member(database, 9_003)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as db_session:
        model = await db_session.get(MemberModel, pending.id)
        assert model is not None
        model.status = "pending"
        db_session.add(
            MemberSanctionModel(
                target_member_id=restricted.id,
                author_member_id=admin.id,
                sanction_type="restriction",
                restricted_actions_json=["accept_task"],
                reason="temporary_action_restriction",
                starts_at=datetime.datetime.now(datetime.UTC),
                state="active",
                command_id=uuid4(),
            )
        )
    service = NavigationService(database.unit_of_work)
    for telegram_user_id in (member.telegram_user_id, pending.telegram_user_id, 9_999):
        with pytest.raises(PermissionError, match="unavailable"):
            await service.require_active_administrator(telegram_user_id)
    with pytest.raises(PermissionError, match="accept_task"):
        await TaskService(database.unit_of_work).list_available(
            actor_telegram_user_id=restricted.telegram_user_id
        )
    await database.dispose()
