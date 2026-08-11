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
from community_bot.domain.members import MemberRole
from community_bot.domain.tasks import TaskDraftStep
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.db.models import (
    AssignmentModel,
    InvitationModel,
    MemberModel,
    MemberSanctionModel,
    TaskCreationDraftModel,
    TaskModel,
    TaskTemplateModel,
)

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
        self.reply_buttons: list[str] = []

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
            self.text_payloads.append((text_value, getattr(method, "parse_mode", None)))
        markup = getattr(method, "reply_markup", None)
        if markup is not None and hasattr(markup, "inline_keyboard"):
            for row in markup.inline_keyboard:
                self.callbacks.extend(
                    button.callback_data for button in row if button.callback_data is not None
                )
        if markup is not None and hasattr(markup, "keyboard"):
            self.reply_buttons.extend(button.text for row in markup.keyboard for button in row)
        if isinstance(method, AnswerCallbackQuery):
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
    database: Database, telegram_user_id: int, role: MemberRole = MemberRole.MEMBER
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
            ["interaction_review", "karma_review", "member_read"]
            if role is MemberRole.ADMINISTRATOR
            else []
        ),
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add(model)
    return model


async def _published_task(
    database: Database, author: MemberModel, template_id: UUID
) -> PublishedTask:
    service = TaskService(database.unit_of_work)
    draft = await service.start(
        update_id=60_000, actor_telegram_user_id=author.telegram_user_id, template_id=template_id
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
        1,
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
                60_000 + offset,
                author.telegram_user_id,
                current.id,
                step,
                current.revision,
                value,
            )
        )
    preview = await service.preview(
        update_id=60_006,
        actor_telegram_user_id=author.telegram_user_id,
        draft_id=current.id,
        expected_revision=current.revision,
    )
    return await service.publish(
        PublishTaskCommand(
            60_007, author.telegram_user_id, preview.draft.id, preview.draft.revision
        )
    )


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

    await dispatcher.feed_update(bot, message_update(70_001, 7_003, "/start"))
    assert {"Найти задание", "Создать задание", "Баланс", "Помощь"} <= set(session.reply_buttons)

    await dispatcher.feed_update(bot, callback_update(70_002, 7_003, "nav:tasks:not-a-uuid"))
    await dispatcher.feed_update(bot, message_update(70_003, 7_003, "Найти задание"))
    accept_callback = next(
        value for value in session.callbacks if value == f"task:accept:{task.id}"
    )
    await dispatcher.feed_update(bot, callback_update(70_004, 7_003, accept_callback))
    dispatcher = _dispatcher(database, invite_token_secret="x" * 32)
    await dispatcher.feed_update(bot, callback_update(70_004, 7_003, accept_callback))

    await dispatcher.feed_update(bot, message_update(70_005, 7_003, "/create"))
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

    await dispatcher.feed_update(bot, message_update(70_011, 7_003, "/admin"))
    await dispatcher.feed_update(bot, message_update(70_012, 7_004, "/admin"))
    await dispatcher.feed_update(bot, callback_update(70_013, 7_004, "nav:admin:invite"))
    await dispatcher.feed_update(bot, message_update(70_014, 7_001, "/admin"))
    await dispatcher.feed_update(bot, callback_update(70_015, 7_001, "nav:admin:invite"))
    await dispatcher.feed_update(bot, callback_update(70_015, 7_001, "nav:admin:invite"))
    await dispatcher.feed_update(bot, callback_update(70_016, 7_001, "nav:admin:registrations"))
    await dispatcher.feed_update(bot, callback_update(70_017, 7_001, "nav:admin:moderation"))

    async with sessions() as db_session:
        assignment_count = await db_session.scalar(
            select(func.count()).select_from(AssignmentModel)
        )
        invite_count = await db_session.scalar(select(func.count()).select_from(InvitationModel))
        performer_draft = await db_session.scalar(
            select(TaskCreationDraftModel).where(TaskCreationDraftModel.creator_id == performer.id)
        )
    assert assignment_count == 1
    assert invite_count == 1
    assert performer_draft is not None
    assert performer_draft.template_id == UUID(hex=create_callback.removeprefix("nav:create:"))
    assert performer_draft.current_step == "deadline"
    assert sum("Административное меню недоступно." in text for text in session.texts) == 2
    assert any("Баланс: 5 кредитов" in text for text in session.texts)
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
