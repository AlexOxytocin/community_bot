from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast, override
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.catalog import (
    CatalogQuery,
    CatalogService,
    CatalogTemplate,
    PublishTemplateVersionCommand,
)
from community_bot.application.economy import ProductConfigBootstrapCoordinator
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.domain.catalog import CatalogError, PayloadValidationError, TaskFormat
from community_bot.domain.members import MemberRole, MemberStatus
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AuditEventModel,
    MemberModel,
    ProcessedTelegramUpdateModel,
    TaskCategoryModel,
    TaskTemplateModel,
)
from community_bot.transport.telegram.catalog import build_catalog_router

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping

    from aiogram.methods import TelegramMethod

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
CONFIG_PATH = Path(__file__).parents[2] / "config" / "product-config.v1.json"
TelegramType = TypeVar("TelegramType")


async def add_member(
    database: Database,
    *,
    telegram_user_id: int,
    role: MemberRole = MemberRole.MEMBER,
    status: MemberStatus = MemberStatus.ACTIVE,
    experience: int = 0,
) -> MemberModel:
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        member = MemberModel(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            display_name=f"Member {telegram_user_id}",
            timezone="UTC",
            role=role.value,
            status=status.value,
            level_number=1,
            experience_total_cached=experience,
        )
        session.add(member)
    return member


async def prepare_config(database: Database, admin: MemberModel) -> None:
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work,
        load_product_config_candidate,
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )


async def count(database: Database, model: type[object]) -> int:
    async with database.engine.connect() as connection:
        value = await connection.scalar(select(func.count()).select_from(model))
    return int(value or 0)


async def insert_cross_category_version(database: Database) -> None:
    """Attempt the direct SQL-equivalent invariant violation."""
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        original = await session.scalar(
            select(TaskTemplateModel).where(TaskTemplateModel.code == "repository_first_impression")
        )
        career = await session.scalar(
            select(TaskCategoryModel).where(TaskCategoryModel.code == "career")
        )
        assert original is not None
        assert career is not None
        session.add(
            TaskTemplateModel(
                id=uuid4(),
                category_id=career.id,
                code=original.code,
                version=2,
                name=original.name,
                description=original.description,
                creator_instructions=original.creator_instructions,
                performer_instructions=original.performer_instructions,
                completion_criteria=original.completion_criteria,
                input_schema_json=original.input_schema_json,
                result_schema_json=original.result_schema_json,
                credit_reward=original.credit_reward,
                estimated_minutes=original.estimated_minutes,
                format=original.format,
                minimum_level=original.minimum_level,
                maximum_performers=original.maximum_performers,
                moderation_required=original.moderation_required,
                is_active=False,
            )
        )
        await session.flush()


async def test_seed_level_filters_and_payload_boundary(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=900,
        role=MemberRole.ADMINISTRATOR,
    )
    level_one = await add_member(database, telegram_user_id=901)
    level_two = await add_member(database, telegram_user_id=902, experience=10)
    await prepare_config(database, admin)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        stale = await session.get(MemberModel, level_two.id)
        assert stale is not None
        stale.level_number = 1
    catalog = CatalogService(database.unit_of_work)

    first = await catalog.browse(CatalogQuery(level_one.telegram_user_id, limit=20))
    second = await catalog.browse(CatalogQuery(level_two.telegram_user_id, limit=20))
    assert len(first.items) == 7
    assert len(second.items) == 8
    assert "linkedin_audit" not in {item.code for item in first.items}
    linkedin = next(item for item in second.items if item.code == "linkedin_audit")

    filtered = await catalog.browse(
        CatalogQuery(
            level_two.telegram_user_id,
            category_code="networking",
            format=TaskFormat.ONLINE,
            limit=20,
        )
    )
    assert [item.code for item in filtered.items] == ["linkedin_audit"]
    payload = {
        "context": "Need a professional profile review.",
        "materials": "https://example.com/profile",
        "constraints": "No public endorsement.",
    }
    downstream_calls: list[dict[str, object]] = []

    async def invoke_creation(
        input_payload: Mapping[str, object],
    ) -> tuple[CatalogTemplate, dict[str, object]]:
        exact_template, validated_payload = await catalog.for_creation(
            actor_telegram_user_id=level_two.telegram_user_id,
            template_id=linkedin.id,
            input_payload=input_payload,
        )
        downstream_calls.append(validated_payload)
        return exact_template, validated_payload

    exact, validated = await invoke_creation(payload)
    assert exact.id == linkedin.id
    assert validated == payload
    with pytest.raises(PayloadValidationError):
        await invoke_creation({**payload, "materials": 123})
    assert downstream_calls == [payload]
    await catalog.change_reward(
        update_id=9_020,
        actor_telegram_user_id=admin.telegram_user_id,
        code=linkedin.code,
        credit_reward=3,
    )
    result_payload = {
        "summary": "The profile has a clear professional direction.",
        "findings": ["Clarify the headline"],
        "evidence": ["The headline mixes two roles"],
    }
    assert await catalog.validate_result(template_id=linkedin.id, payload=result_payload) == (
        result_payload
    )
    with pytest.raises(PayloadValidationError):
        await catalog.validate_result(
            template_id=linkedin.id,
            payload={**result_payload, "unexpected": "value"},
        )
    await database.dispose()


async def test_keyset_does_not_repeat_code_when_version_changes(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=910,
        role=MemberRole.ADMINISTRATOR,
    )
    member = await add_member(database, telegram_user_id=911, experience=10)
    await prepare_config(database, admin)
    catalog = CatalogService(database.unit_of_work)
    first = await catalog.browse(CatalogQuery(member.telegram_user_id, limit=2))
    assert first.next_cursor is not None
    shown_code = first.items[0].code
    shown = first.items[0]
    with pytest.raises(CatalogError, match="category is immutable"):
        await catalog.publish_version(
            PublishTemplateVersionCommand(
                update_id=9_099,
                actor_telegram_user_id=admin.telegram_user_id,
                draft=shown.draft(category_code="career"),
            )
        )
    await catalog.change_reward(
        update_id=9_100,
        actor_telegram_user_id=admin.telegram_user_id,
        code=shown_code,
        credit_reward=3,
    )

    codes = [item.code for item in first.items]
    cursor = first.next_cursor
    while cursor is not None:
        page = await catalog.browse(CatalogQuery(member.telegram_user_id, cursor=cursor, limit=2))
        codes.extend(item.code for item in page.items)
        cursor = page.next_cursor
    assert len(codes) == len(set(codes)) == 8
    assert codes.count(shown_code) == 1
    await database.dispose()


async def test_admin_toggles_versions_retry_and_history(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=920,
        role=MemberRole.ADMINISTRATOR,
    )
    member = await add_member(database, telegram_user_id=921, experience=10)
    moderator = await add_member(
        database,
        telegram_user_id=922,
        role=MemberRole.MODERATOR,
    )
    ordinary_member = await add_member(database, telegram_user_id=923)
    paused_admin = await add_member(
        database,
        telegram_user_id=924,
        role=MemberRole.ADMINISTRATOR,
        status=MemberStatus.PAUSED,
    )
    await prepare_config(database, admin)
    catalog = CatalogService(database.unit_of_work)

    receipts_before = await count(database, ProcessedTelegramUpdateModel)
    audit_before = await count(database, AuditEventModel)
    for offset, actor in enumerate((ordinary_member, moderator, paused_admin)):
        with pytest.raises(PermissionError):
            await catalog.set_category_active(
                update_id=9_190 + offset,
                actor_telegram_user_id=actor.telegram_user_id,
                code="development",
                enabled=False,
            )
    assert await count(database, ProcessedTelegramUpdateModel) == receipts_before
    assert await count(database, AuditEventModel) == audit_before
    await catalog.set_category_active(
        update_id=9_201,
        actor_telegram_user_id=admin.telegram_user_id,
        code="development",
        enabled=False,
    )
    hidden = await catalog.browse(CatalogQuery(member.telegram_user_id, limit=20))
    assert "repository_first_impression" not in {item.code for item in hidden.items}
    await catalog.set_category_active(
        update_id=9_202,
        actor_telegram_user_id=admin.telegram_user_id,
        code="development",
        enabled=True,
    )

    first, replay = await asyncio.gather(
        catalog.change_reward(
            update_id=9_203,
            actor_telegram_user_id=admin.telegram_user_id,
            code="resume_review",
            credit_reward=4,
        ),
        catalog.change_reward(
            update_id=9_203,
            actor_telegram_user_id=admin.telegram_user_id,
            code="resume_review",
            credit_reward=4,
        ),
    )
    assert first.id == replay.id
    assert first.version == replay.version == 2
    await catalog.set_template_active(
        update_id=9_204,
        actor_telegram_user_id=admin.telegram_user_id,
        code="resume_review",
        enabled=False,
    )
    await catalog.set_template_active(
        update_id=9_205,
        actor_telegram_user_id=admin.telegram_user_id,
        code="resume_review",
        enabled=True,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        versions = (
            await session.scalars(
                select(TaskTemplateModel)
                .where(TaskTemplateModel.code == "resume_review")
                .order_by(TaskTemplateModel.version)
            )
        ).all()
    assert [(item.version, item.credit_reward, item.is_active) for item in versions] == [
        (1, 3, False),
        (2, 4, True),
    ]
    assert await count(database, ProcessedTelegramUpdateModel) == receipts_before + 5
    assert await count(database, AuditEventModel) >= 5
    await database.dispose()


async def test_two_version_writers_are_serialized(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=930,
        role=MemberRole.ADMINISTRATOR,
    )
    await prepare_config(database, admin)
    catalog = CatalogService(database.unit_of_work)
    results = await asyncio.wait_for(
        asyncio.gather(
            catalog.change_reward(
                update_id=9_300,
                actor_telegram_user_id=admin.telegram_user_id,
                code="landing_review",
                credit_reward=3,
            ),
            catalog.change_reward(
                update_id=9_301,
                actor_telegram_user_id=admin.telegram_user_id,
                code="landing_review",
                credit_reward=4,
            ),
        ),
        timeout=10,
    )
    assert {item.version for item in results} == {2, 3}
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        active = (
            await session.scalars(
                select(TaskTemplateModel)
                .where(TaskTemplateModel.code == "landing_review")
                .where(TaskTemplateModel.is_active.is_(True))
            )
        ).all()
    assert len(active) == 1
    assert active[0].version == 3
    await database.dispose()


async def test_database_immutability_and_migration_cycle(database_url: str) -> None:
    database = Database(database_url)
    with pytest.raises(DBAPIError):
        async with database.engine.begin() as connection:
            await connection.execute(
                text("UPDATE task_templates SET credit_reward = 4 WHERE version = 1")
            )
    with pytest.raises(DBAPIError):
        async with database.engine.begin() as connection:
            await connection.execute(text("DELETE FROM task_categories"))
    with pytest.raises(DBAPIError):
        await insert_cross_category_version(database)
    await database.dispose()

    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    configuration = Config("alembic.ini")
    try:
        await asyncio.to_thread(command.downgrade, configuration, "0004")
        await asyncio.to_thread(command.upgrade, configuration, "head")
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
    restarted = Database(database_url)
    assert await count(restarted, TaskCategoryModel) == 8
    assert await count(restarted, TaskTemplateModel) == 8
    await restarted.dispose()


class CapturingSession(BaseSession):
    """Fake Bot API session for the catalog Telegram smoke."""

    def __init__(self) -> None:
        """Collect outgoing text and callback data."""
        super().__init__()
        self.texts: list[str] = []
        self.callbacks: list[str] = []

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
        markup = getattr(method, "reply_markup", None)
        if markup is not None:
            for row in markup.inline_keyboard:
                self.callbacks.extend(
                    button.callback_data for button in row if button.callback_data is not None
                )
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


async def test_catalog_synthetic_telegram_browse_page_and_admin(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=940,
        role=MemberRole.ADMINISTRATOR,
    )
    member = await add_member(database, telegram_user_id=941, experience=10)
    await prepare_config(database, admin)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_catalog_router(CatalogService(database.unit_of_work)))
    receipts_before = await count(database, ProcessedTelegramUpdateModel)
    audit_before = await count(database, AuditEventModel)
    session = CapturingSession()
    bot = Bot(token=f"{123456}:{'C' * 35}", session=session)
    member_user = User(id=member.telegram_user_id, is_bot=False, first_name="Member")
    admin_user = User(id=admin.telegram_user_id, is_bot=False, first_name="Admin")

    def message_update(update_id: int, actor: User, value: str) -> Update:
        return Update(
            update_id=update_id,
            message=Message(
                message_id=update_id,
                date=datetime.now(UTC),
                chat=Chat(id=actor.id, type="private"),
                from_user=actor,
                text=value,
            ),
        )

    await dispatcher.feed_update(bot, message_update(9_400, member_user, "/catalog"))
    assert session.callbacks
    assert max(len(value.encode()) for value in session.callbacks) <= 64
    callback_data = session.callbacks[-1]
    await dispatcher.feed_update(
        bot,
        Update(
            update_id=9_401,
            callback_query=CallbackQuery(
                id="catalog-page",
                from_user=member_user,
                chat_instance="catalog",
                data=callback_data,
                message=Message(
                    message_id=9_401,
                    date=datetime.now(UTC),
                    chat=Chat(id=member_user.id, type="private"),
                    text="catalog",
                ),
            ),
        ),
    )
    await dispatcher.feed_update(
        bot,
        message_update(
            9_402,
            member_user,
            "/catalog_template_reward resume_review 4",
        ),
    )
    await dispatcher.feed_update(
        bot,
        message_update(
            9_403,
            admin_user,
            "/catalog_template_reward resume_review not-a-number",
        ),
    )
    await dispatcher.feed_update(
        bot,
        message_update(
            9_404,
            admin_user,
            "/catalog_template_reward resume_review 4",
        ),
    )
    await dispatcher.feed_update(
        bot,
        message_update(
            9_404,
            admin_user,
            "/catalog_template_reward resume_review 4",
        ),
    )
    await dispatcher.feed_update(
        bot,
        message_update(9_405, member_user, "/catalog career online"),
    )
    assert any(
        "Следующая" not in value and "Первое впечатление" in value for value in session.texts
    )
    assert any("Опубликована версия 2" in value for value in session.texts)
    assert any("Проверка резюме" in value and "4 кредита" in value for value in session.texts)
    assert any("недоступно" in value for value in session.texts)
    assert any("Проверьте параметры" in value for value in session.texts)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as sql_session:
        resume_versions = (
            await sql_session.scalars(
                select(TaskTemplateModel).where(TaskTemplateModel.code == "resume_review")
            )
        ).all()
    assert sorted(item.version for item in resume_versions) == [1, 2]
    assert await count(database, ProcessedTelegramUpdateModel) == receipts_before + 1
    assert await count(database, AuditEventModel) == audit_before + 1
    await bot.session.close()
    await database.dispose()
