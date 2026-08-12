# ruff: noqa: RUF001
"""Independent end-to-end pilot stories through the production Telegram dispatcher."""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.economy import (
    EconomyService,
    ProductConfigBootstrapCoordinator,
)
from community_bot.application.reputation import ReputationService
from community_bot.bootstrap.bot import _dispatcher
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.domain.economy import starting_grant
from community_bot.domain.members import MemberRole
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AssignmentDisputeModel,
    AssignmentModel,
    AssignmentSubmissionDraftModel,
    AuditEventModel,
    DisputeResolutionModel,
    KarmaVoteHistoryModel,
    KarmaVoteModel,
    MemberModel,
    ModerationCaseModel,
    OutboxEventModel,
    ProcessedTelegramUpdateModel,
    ReliabilityEventModel,
    TaskModel,
)
from tests.integration.test_assignments import _published_task
from tests.integration.test_reputation import (
    add_member as add_reputation_member,
)
from tests.integration.test_reputation import (
    add_paid_interaction,
)
from tests.integration.test_reputation import (
    prepare_config as prepare_reputation_config,
)
from tests.integration.test_task_creation import (
    CONFIG_PATH,
    CapturingSession,
    add_member,
    prepare_member,
    template_id,
)

pytestmark = pytest.mark.e2e
TOKEN_SECRET = "pilot-e2e-secret-key-with-32-bytes"  # noqa: S105
FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "pilot_e2e_seed.json"


class TelegramDriver:
    """Feed synthetic updates through the same dispatcher composition as production."""

    def __init__(self, database: Database) -> None:
        """Initialize a production-composed dispatcher with a fake Bot API session."""
        self.database = database
        self.capture = CapturingSession()
        self.bot = Bot(token=f"{123456}:{'T' * 35}", session=self.capture)
        self.dispatcher = _dispatcher(database, invite_token_secret=TOKEN_SECRET)

    def restart(self) -> None:
        """Rebuild all routers while retaining only durable PostgreSQL state."""
        self.dispatcher = _dispatcher(self.database, invite_token_secret=TOKEN_SECRET)

    async def message(self, update_id: int, user: User, value: str) -> None:
        """Feed one synthetic private text message."""
        await self.dispatcher.feed_update(
            self.bot,
            Update(
                update_id=update_id,
                message=Message(
                    message_id=update_id,
                    date=datetime.datetime.now(datetime.UTC),
                    chat=Chat(id=user.id, type="private"),
                    from_user=user,
                    text=value,
                ),
            ),
        )

    async def callback(self, update_id: int, user: User, value: str) -> None:
        """Feed one synthetic private callback query."""
        await self.dispatcher.feed_update(
            self.bot,
            Update(
                update_id=update_id,
                callback_query=CallbackQuery(
                    id=f"pilot-{update_id}",
                    from_user=user,
                    chat_instance="pilot",
                    data=value,
                    message=Message(
                        message_id=update_id,
                        date=datetime.datetime.now(datetime.UTC),
                        chat=Chat(id=user.id, type="private"),
                        from_user=user,
                        text="pilot callback",
                    ),
                ),
            ),
        )

    async def close(self) -> None:
        """Close the fake Bot API session."""
        await self.bot.session.close()


def actor(telegram_user_id: int, name: str) -> User:
    return User(id=telegram_user_id, is_bot=False, first_name=name)


async def activate_config(database: Database, admin_id: UUID) -> None:
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work,
        load_product_config_candidate,
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin_id,
        activation_command_id=uuid4(),
    )


async def registered_member(
    driver: TelegramDriver,
    *,
    admin: User,
    participant: User,
    update_base: int,
) -> MemberModel:
    """Create one-use invite, complete registration, and approve through Telegram."""
    before = len(driver.capture.texts)
    await driver.message(update_base, admin, "/invite_create 1 7")
    response = "\n".join(driver.capture.texts[before:])
    match = re.search(r"/start ([^`\s]+)", response)
    assert match is not None
    await driver.message(update_base + 1, participant, f"/start {match.group(1)}")
    await driver.callback(update_base + 2, participant, "registration:consent")
    answers = (
        f"Участник {participant.id}",
        "Москва",
        "Помогаю проверять цифровые продукты.",
        "Делать сообщество полезнее.",
        "Тестирование, продукты",
        "Python, исследования",
        "Два часа в неделю",
    )
    for offset, answer in enumerate(answers, start=3):
        before_answer = len(driver.capture.texts)
        await driver.message(update_base + offset, participant, answer)
        response_text = driver.capture.texts[before_answer:]
        assert not any("Не удалось сохранить" in value for value in response_text), (
            offset,
            response_text,
        )
    await driver.callback(update_base + 20, participant, "registration:submit")
    sessions = async_sessionmaker(driver.database.engine, expire_on_commit=False)
    async with sessions() as session:
        member = await session.scalar(
            select(MemberModel).where(MemberModel.telegram_user_id == participant.id)
        )
    assert member is not None
    await driver.callback(
        update_base + 21,
        admin,
        f"registration:approve:{member.id}",
    )
    await driver.callback(
        update_base + 21,
        admin,
        f"registration:approve:{member.id}",
    )
    return member


async def publish_task(
    driver: TelegramDriver,
    *,
    author: User,
    update_base: int,
) -> TaskModel:
    selected = await template_id(driver.database, "repository_first_impression")
    messages = (
        f"/task_create {selected}",
        (
            '{"context":"Need a detailed and practical review.",'
            '"materials":"https://example.com/item",'
            '"constraints":"Do not publish private information."}'
        ),
        (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)).isoformat(),
        "online",
        '{"url":"https://example.com/item"}',
        "1",
        "/task_preview",
    )
    before = len(driver.capture.callbacks)
    for offset, value in enumerate(messages):
        await driver.message(update_base + offset, author, value)
    callbacks = driver.capture.callbacks[before:]
    assert callbacks, driver.capture.texts[-10:]
    await driver.callback(update_base + 10, author, callbacks[-1])
    sessions = async_sessionmaker(driver.database.engine, expire_on_commit=False)
    async with sessions() as session:
        task = await session.scalar(
            select(TaskModel)
            .join(MemberModel, MemberModel.id == TaskModel.creator_id)
            .where(MemberModel.telegram_user_id == author.id)
            .order_by(TaskModel.published_at.desc())
        )
    assert task is not None
    return task


async def accept_and_submit(
    driver: TelegramDriver,
    *,
    performer: User,
    task_id: UUID,
    update_base: int,
) -> AssignmentModel:
    await driver.callback(update_base, performer, f"task:accept:{task_id}")
    sessions = async_sessionmaker(driver.database.engine, expire_on_commit=False)
    async with sessions() as session:
        assignment = await session.scalar(
            select(AssignmentModel).where(AssignmentModel.task_id == task_id)
        )
    assert assignment is not None, driver.capture.callback_answers[-1:]
    await driver.message(
        update_base + 1,
        performer,
        f"/assignment_submit {assignment.id}",
    )
    async with sessions() as session:
        draft = await session.scalar(
            select(AssignmentSubmissionDraftModel).where(
                AssignmentSubmissionDraftModel.assignment_id == assignment.id,
                AssignmentSubmissionDraftModel.submitted_result_id.is_(None),
            )
        )
    assert draft is not None
    before = len(driver.capture.callbacks)
    payload = (
        '{"summary":"A sufficiently detailed result summary.",'
        '"findings":["One concrete finding"],"evidence":[]}'
    )
    await driver.message(
        update_base + 2,
        performer,
        f"/assignment_result {draft.id} {draft.revision} {payload}",
    )
    callbacks = driver.capture.callbacks[before:]
    assert callbacks
    driver.restart()
    await driver.callback(update_base + 3, performer, callbacks[-1])
    return assignment


async def transaction_count(
    database: Database,
    *,
    assignment_id: UUID | None = None,
    transaction_type: str | None = None,
) -> int:
    statement = select(func.count(AccountTransactionModel.id))
    if assignment_id is not None:
        statement = statement.where(AccountTransactionModel.assignment_id == assignment_id)
    if transaction_type is not None:
        statement = statement.where(AccountTransactionModel.transaction_type == transaction_type)
    async with database.engine.connect() as connection:
        return int(await connection.scalar(statement) or 0)


@pytest.mark.asyncio
async def test_full_exchange(database_url: str) -> None:
    database = Database(database_url)
    driver = TelegramDriver(database)
    admin_model = await add_member(
        database,
        telegram_user_id=9_900_001,
        role=MemberRole.ADMINISTRATOR,
    )
    await activate_config(database, admin_model.id)
    admin = actor(admin_model.telegram_user_id, "Admin")
    author_user = actor(9_900_002, "Author")
    performer_user = actor(9_900_003, "Performer")
    author_model = await registered_member(
        driver,
        admin=admin,
        participant=author_user,
        update_base=200_000,
    )
    performer_model = await registered_member(
        driver,
        admin=admin,
        participant=performer_user,
        update_base=201_000,
    )
    task = await publish_task(driver, author=author_user, update_base=202_000)
    assignment = await accept_and_submit(
        driver,
        performer=performer_user,
        task_id=task.id,
        update_base=203_000,
    )
    review = f"assign:review:{assignment.id.hex}:full"
    await driver.callback(204_000, author_user, review)
    await driver.callback(204_000, author_user, review)

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        author_stored = await session.get(MemberModel, author_model.id)
        performer_stored = await session.get(MemberModel, performer_model.id)
        assignment_stored = await session.get(AssignmentModel, assignment.id)
        task_stored = await session.get(TaskModel, task.id)
        author_ledger = await session.scalar(
            select(func.coalesce(func.sum(AccountTransactionModel.credit_delta), 0)).where(
                AccountTransactionModel.member_id == author_model.id
            )
        )
        performer_ledger = await session.scalar(
            select(func.coalesce(func.sum(AccountTransactionModel.credit_delta), 0)).where(
                AccountTransactionModel.member_id == performer_model.id
            )
        )
        outbox_count = await session.scalar(
            select(func.count(OutboxEventModel.id)).where(
                OutboxEventModel.aggregate_id == assignment.id
            )
        )
    assert author_stored is not None
    assert performer_stored is not None
    assert assignment_stored is not None
    assert assignment_stored.status == "approved"
    assert task_stored is not None
    assert task_stored.status == "completed"
    assert (author_stored.credit_balance_cached, author_ledger) == (3, 3)
    assert (performer_stored.credit_balance_cached, performer_ledger) == (7, 7)
    assert performer_stored.experience_total_cached == 2
    assert await transaction_count(database, assignment_id=assignment.id) == 1
    assert int(outbox_count or 0) >= 1
    reputation = ReputationService(database.unit_of_work)
    leaderboard = await reputation.leaderboard(telegram_user_id=author_user.id)
    assert leaderboard.items[0].member_id == performer_model.id
    async with database.unit_of_work() as unit_of_work:
        assert await unit_of_work.karma_eligible(author_model.id, performer_model.id)
        assert await unit_of_work.karma_eligible(performer_model.id, author_model.id)
    await driver.close()
    await database.dispose()


@pytest.mark.asyncio
async def test_unaccepted_task_cancellation(database_url: str) -> None:
    database = Database(database_url)
    member = await prepare_member(database, telegram_user_id=9_900_011)
    driver = TelegramDriver(database)
    author_user = actor(member.telegram_user_id, "Author")
    task = await publish_task(driver, author=author_user, update_base=210_000)
    await driver.message(211_000, author_user, f"/task_cancel {task.id}")
    await driver.message(211_000, author_user, f"/task_cancel {task.id}")
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        stored = await session.get(TaskModel, task.id)
        assignments = await session.scalar(
            select(func.count(AssignmentModel.id)).where(AssignmentModel.task_id == task.id)
        )
        experience = await session.scalar(
            select(func.coalesce(func.sum(AccountTransactionModel.experience_delta), 0)).where(
                AccountTransactionModel.task_id == task.id
            )
        )
    assert stored is not None
    assert stored.status == "cancelled"
    assert int(assignments or 0) == 0
    assert int(experience or 0) == 0
    assert (
        await transaction_count(
            database,
            transaction_type="task_reward_refunded",
        )
        == 1
    )
    await driver.close()
    await database.dispose()


@pytest.mark.asyncio
async def test_dispute_partial_resolution(database_url: str) -> None:
    database = Database(database_url)
    author_model, task = await _published_task(database, update_base=22_000)
    performer_model = await add_member(database, telegram_user_id=9_900_021)
    await EconomyService(database.unit_of_work).apply_one(starting_grant(performer_model.id))
    moderator_model = await add_member(
        database,
        telegram_user_id=9_900_022,
        role=MemberRole.MODERATOR,
    )
    driver = TelegramDriver(database)
    author_user = actor(author_model.telegram_user_id, "Author")
    performer_user = actor(performer_model.telegram_user_id, "Performer")
    moderator_user = actor(moderator_model.telegram_user_id, "Moderator")
    assignment = await accept_and_submit(
        driver,
        performer=performer_user,
        task_id=task.id,
        update_base=222_000,
    )
    await driver.callback(
        221_000,
        author_user,
        f"assign:review:{assignment.id.hex}:reject",
    )
    private_comment = "Результат соответствует условиям, прошу независимую проверку."
    await driver.message(
        221_001,
        performer_user,
        f"/assignment_dispute {assignment.id} {private_comment}",
    )
    await driver.message(
        221_001,
        performer_user,
        f"/assignment_dispute {assignment.id} {private_comment}",
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        case = await session.scalar(
            select(ModerationCaseModel).where(ModerationCaseModel.assignment_id == assignment.id)
        )
    assert case is not None
    before = len(driver.capture.callbacks)
    await driver.message(
        221_010,
        moderator_user,
        f"/mod_resolve {case.id} 0 partial_payment Evidence reviewed.",
    )
    callbacks = driver.capture.callbacks[before:]
    assert callbacks
    driver.restart()
    await driver.callback(221_011, moderator_user, callbacks[-1])
    await driver.callback(221_011, moderator_user, callbacks[-1])
    async with sessions() as session:
        stored = await session.get(AssignmentModel, assignment.id)
        dispute_count = await session.scalar(
            select(func.count(AssignmentDisputeModel.id)).where(
                AssignmentDisputeModel.assignment_id == assignment.id
            )
        )
        resolutions = await session.scalar(
            select(func.count(DisputeResolutionModel.id)).where(
                DisputeResolutionModel.case_id == case.id
            )
        )
        reliability = await session.scalar(
            select(func.count(ReliabilityEventModel.id)).where(
                ReliabilityEventModel.assignment_id == assignment.id
            )
        )
        payloads = (
            await session.scalars(
                select(OutboxEventModel.payload_json).where(
                    OutboxEventModel.aggregate_id == assignment.id
                )
            )
        ).all()
    assert stored is not None
    assert stored.status == "partially_approved"
    assert int(dispute_count or 0) == 1
    assert int(resolutions or 0) == 1
    assert int(reliability or 0) >= 2
    assert await transaction_count(database, assignment_id=assignment.id) == 2
    assert all(private_comment not in str(payload) for payload in payloads)
    await driver.close()
    await database.dispose()


@pytest.mark.asyncio
async def test_karma_after_paid_interaction(database_url: str) -> None:
    database = Database(database_url)
    rater = await add_reputation_member(database, 9_900_031)
    await prepare_reputation_config(database, rater.id)
    target = await add_reputation_member(database, 9_900_032)
    await add_paid_interaction(database, rater, target)
    admin = await add_reputation_member(
        database,
        9_900_033,
        role=MemberRole.ADMINISTRATOR,
        permissions=["karma_review"],
    )
    outsider = await add_reputation_member(database, 9_900_034)
    driver = TelegramDriver(database)
    rater_user = actor(rater.telegram_user_id, "Rater")
    outsider_user = actor(outsider.telegram_user_id, "Outsider")

    before = len(driver.capture.callbacks)
    await driver.message(230_000, rater_user, f"/karma {target.id}")
    value_callbacks = driver.capture.callbacks[before:]
    positive = next(value for value in value_callbacks if value.endswith(":1"))
    await driver.callback(230_001, rater_user, positive)
    before = len(driver.capture.callbacks)
    await driver.message(
        230_002,
        rater_user,
        "Очень полезная и аккуратная помощь.",
    )
    confirm = driver.capture.callbacks[before:][-1]
    await driver.callback(230_003, outsider_user, confirm)
    await driver.callback(230_004, rater_user, confirm)
    before = len(driver.capture.callbacks)
    await driver.message(230_005, rater_user, f"/karma {target.id}")
    value_callbacks = driver.capture.callbacks[before:]
    negative = next(value for value in value_callbacks if value.endswith(":-1"))
    await driver.callback(230_006, rater_user, negative)
    before = len(driver.capture.callbacks)
    await driver.message(
        230_007,
        rater_user,
        "Результат пришлось полностью переделать.",
    )
    confirm = driver.capture.callbacks[before:][-1]
    await driver.callback(230_008, rater_user, confirm)

    reputation = ReputationService(database.unit_of_work)
    profile = await reputation.profile(
        telegram_user_id=outsider.telegram_user_id,
        target_id=target.id,
    )
    raw = await reputation.raw_karma(
        update_id=230_009,
        telegram_user_id=admin.telegram_user_id,
        target_id=target.id,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        vote_count = await session.scalar(select(func.count(KarmaVoteModel.id)))
        history_count = await session.scalar(select(func.count(KarmaVoteHistoryModel.id)))
        raw_audit = await session.scalar(
            select(func.count(AuditEventModel.id)).where(
                AuditEventModel.action == "karma_raw_viewed"
            )
        )
        outsider_receipt = await session.get(ProcessedTelegramUpdateModel, 230_003)
    assert (profile.karma.score, profile.karma.count) == (-1, 1)
    assert int(vote_count or 0) == 1
    assert int(history_count or 0) == 2
    assert len(raw) == 1
    assert [row.revision for row in raw[0].history] == [1, 2]
    assert int(raw_audit or 0) == 1
    assert outsider_receipt is None
    await driver.close()
    await database.dispose()


def test_e2e_fixture_contains_only_reserved_synthetic_ids() -> None:
    payload = FIXTURE_PATH.read_text(encoding="utf-8")
    assert "9900001" in payload
    assert not re.search(r"(?:BOT_TOKEN|DATABASE_URL|INVITE_TOKEN_SECRET)\s*[=:]", payload)
