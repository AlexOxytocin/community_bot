"""PostgreSQL tests for the complete task assignment exchange."""

# ruff: noqa: PLR0915, RUF001
from __future__ import annotations

import asyncio
import datetime
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.assignments import (
    AcceptAssignmentCommand,
    AssignmentService,
    DecideAssignmentCommand,
    SubmitResultCommand,
)
from community_bot.application.tasks import PublishTaskCommand, TaskService
from community_bot.domain.assignments import AssignmentDecision, AssignmentError, AssignmentStatus
from community_bot.domain.members import MemberRole
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AssignmentDisputeModel,
    AssignmentModel,
    AssignmentResultVersionModel,
    AssignmentSubmissionDraftModel,
    MemberModel,
    OutboxEventModel,
    ProcessedTelegramUpdateModel,
    TaskModel,
)
from community_bot.transport.telegram.assignments import build_assignment_router
from tests.integration.test_task_creation import (
    CapturingSession,
    add_member,
    complete_preview,
    prepare_member,
    template_id,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _published_task(database: Database, *, update_base: int, performer_slots: int = 1):  # noqa: ANN202
    author = await prepare_member(database, telegram_user_id=update_base)
    selected = await template_id(database, "repository_first_impression")
    service = TaskService(database.unit_of_work)
    draft_id, revision = await complete_preview(
        service,
        member=author,
        selected_template_id=selected,
        update_base=update_base * 10,
        performer_slots=performer_slots,
    )
    task = await service.publish(
        PublishTaskCommand(update_base * 10 + 10, author.telegram_user_id, draft_id, revision)
    )
    return author, task


async def _community_task(  # noqa: ANN202
    database: Database,
    *,
    update_base: int,
    performer_slots: int = 1,
    minimum_level: int | None = None,
    deadline_at: datetime.datetime | None = None,
):
    """Create a community snapshot alongside a bootstrapped member task."""
    _author, base = await _published_task(database, update_base=update_base)
    admin = await add_member(
        database,
        telegram_user_id=update_base + 50_000,
        role=MemberRole.ADMINISTRATOR,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        source = await session.get(TaskModel, base.id)
        assert source is not None
        model = TaskModel(
            origin="community",
            template_id=source.template_id,
            template_version=source.template_version,
            creator_id=None,
            author_display_name="Сообщество",
            category_id=source.category_id,
            title="Задание сообщества",
            description=source.description,
            completion_criteria=source.completion_criteria,
            materials_json=source.materials_json,
            input_payload_json=source.input_payload_json,
            credit_reward_per_performer=source.credit_reward_per_performer,
            performer_slots=performer_slots,
            reserved_credit_total=0,
            estimated_minutes=source.estimated_minutes,
            minimum_level=source.minimum_level if minimum_level is None else minimum_level,
            format=source.format,
            city=source.city,
            deadline_at=source.deadline_at if deadline_at is None else deadline_at,
            status="published",
            safety_snapshot_json=source.safety_snapshot_json,
            publish_command_id=uuid4(),
            published_at=(
                source.published_at
                if deadline_at is None
                else deadline_at - datetime.timedelta(days=1)
            ),
        )
        session.add(model)
        await session.flush()
        task_id = model.id
    return admin, task_id


async def test_full_exchange_is_atomic_and_exactly_once(database_url: str) -> None:
    """Accept, versioned submit, and full approval produce one correlated reward."""
    database = Database(database_url)
    author, task = await _published_task(database, update_base=3100)
    performer = await prepare_member(database, telegram_user_id=3200)
    service = AssignmentService(database.unit_of_work)
    assignment = await service.accept(
        AcceptAssignmentCommand(32_100, performer.telegram_user_id, task.id)
    )
    replay = await service.accept(
        AcceptAssignmentCommand(32_100, performer.telegram_user_id, task.id)
    )
    assert replay.id == assignment.id
    payload_v1 = {
        "summary": "A sufficiently detailed result summary.",
        "findings": ["Clear navigation"],
        "evidence": ["https://example.com/evidence"],
    }
    payload_v2 = {**payload_v1, "findings": ["Clear navigation", "Useful README"]}
    submitted = await asyncio.gather(
        service.submit(
            SubmitResultCommand(
                32_101, performer.telegram_user_id, assignment.id, uuid4(), payload_v1
            )
        ),
        service.submit(
            SubmitResultCommand(
                32_102, performer.telegram_user_id, assignment.id, uuid4(), payload_v2
            )
        ),
    )
    assert sorted(item.version for item in submitted) == [1, 2]
    decision_id = uuid4()
    approved = await service.decide(
        DecideAssignmentCommand(
            32_103,
            author.telegram_user_id,
            assignment.id,
            decision_id,
            AssignmentDecision.FULL,
        )
    )
    replayed = await service.decide(
        DecideAssignmentCommand(
            32_103,
            author.telegram_user_id,
            assignment.id,
            decision_id,
            AssignmentDecision.FULL,
        )
    )
    assert approved.status is AssignmentStatus.APPROVED
    assert replayed.id == approved.id
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        rewards = await session.scalar(
            select(func.count(AccountTransactionModel.id)).where(
                AccountTransactionModel.assignment_id == assignment.id,
                AccountTransactionModel.transaction_type == "task_reward_earned",
            )
        )
        versions = await session.scalar(
            select(func.count(AssignmentResultVersionModel.id)).where(
                AssignmentResultVersionModel.assignment_id == assignment.id
            )
        )
        receipts = await session.scalar(
            select(func.count(ProcessedTelegramUpdateModel.update_id)).where(
                ProcessedTelegramUpdateModel.update_id.in_((32_100, 32_101, 32_102, 32_103))
            )
        )
    assert rewards == 1
    assert versions == 2
    assert receipts == 4
    with pytest.raises(DBAPIError):
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE assignment_result_versions SET payload_json = '{}' "
                    "WHERE assignment_id = :id"
                ),
                {"id": assignment.id},
            )
    await database.dispose()


async def test_cancelled_slot_accepts_one_replacement(database_url: str) -> None:
    """Cancellation keeps history while the physical slot becomes reusable."""
    database = Database(database_url)
    _author, task = await _published_task(database, update_base=3300)
    first = await prepare_member(database, telegram_user_id=3400)
    second = await prepare_member(database, telegram_user_id=3500)
    third = await prepare_member(database, telegram_user_id=3550)
    service = AssignmentService(database.unit_of_work)
    original = await service.accept(
        AcceptAssignmentCommand(34_100, first.telegram_user_id, task.id)
    )
    cancelled = await service.cancel(
        update_id=34_101,
        actor_telegram_user_id=first.telegram_user_id,
        assignment_id=original.id,
        reason="Cannot complete before the deadline",
    )
    replacements = await asyncio.gather(
        service.accept(AcceptAssignmentCommand(35_100, second.telegram_user_id, task.id)),
        service.accept(AcceptAssignmentCommand(35_500, third.telegram_user_id, task.id)),
        return_exceptions=True,
    )
    replacement = next(item for item in replacements if not isinstance(item, BaseException))
    assert not isinstance(replacement, BaseException)
    assert sum(not isinstance(item, BaseException) for item in replacements) == 1
    assert cancelled.status is AssignmentStatus.CANCELLED
    assert replacement.slot_number == original.slot_number
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        count = await session.scalar(
            select(func.count(AssignmentModel.id)).where(AssignmentModel.task_id == task.id)
        )
        outbox_payloads = (
            await session.scalars(
                select(OutboxEventModel.payload_json).where(
                    OutboxEventModel.aggregate_type == "assignment"
                )
            )
        ).all()
    assert count == 2
    assert all("comment" not in payload for payload in outbox_payloads)
    await database.dispose()


async def test_reject_then_dispute_persists_private_handoff(database_url: str) -> None:
    """A timely dispute freezes settlement and never leaks its private comment."""
    database = Database(database_url)
    author, task = await _published_task(database, update_base=3600)
    performer = await prepare_member(database, telegram_user_id=3700)
    service = AssignmentService(database.unit_of_work)
    assignment = await service.accept(
        AcceptAssignmentCommand(37_100, performer.telegram_user_id, task.id)
    )
    payload = {
        "summary": "A sufficiently detailed result summary.",
        "findings": ["One concrete finding"],
        "evidence": [],
    }
    await service.submit(
        SubmitResultCommand(37_101, performer.telegram_user_id, assignment.id, uuid4(), payload)
    )
    rejected = await service.decide(
        DecideAssignmentCommand(
            37_102,
            author.telegram_user_id,
            assignment.id,
            uuid4(),
            AssignmentDecision.REJECT,
        )
    )
    assert rejected.status is AssignmentStatus.REJECTED_PENDING_DISPUTE
    private_comment = "The evidence was supplied and should be reviewed again."
    disputed = await service.dispute(
        update_id=37_103,
        actor_telegram_user_id=performer.telegram_user_id,
        assignment_id=assignment.id,
        command_id=uuid4(),
        comment=private_comment,
    )
    assert disputed.status is AssignmentStatus.DISPUTED
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        stored = await session.scalar(
            select(AssignmentDisputeModel).where(
                AssignmentDisputeModel.assignment_id == assignment.id
            )
        )
        payloads = (
            await session.scalars(
                select(OutboxEventModel.payload_json).where(
                    OutboxEventModel.aggregate_id == assignment.id
                )
            )
        ).all()
        correlated = await session.scalar(
            select(func.count(AccountTransactionModel.id)).where(
                AccountTransactionModel.assignment_id == assignment.id
            )
        )
    assert stored is not None
    assert stored.comment == private_comment
    assert all(private_comment not in str(payload) for payload in payloads)
    assert correlated == 0
    with pytest.raises(DBAPIError):
        async with database.engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM assignment_disputes WHERE assignment_id = :id"),
                {"id": assignment.id},
            )
    await database.dispose()


async def test_review_and_deadline_finalizers_are_idempotent(database_url: str) -> None:
    """Scheduler boundaries settle submitted and no-show slots exactly once."""
    database = Database(database_url)
    _author, task = await _published_task(database, update_base=3800)
    performer = await prepare_member(database, telegram_user_id=3900)
    service = AssignmentService(database.unit_of_work)
    assignment = await service.accept(
        AcceptAssignmentCommand(39_100, performer.telegram_user_id, task.id)
    )
    payload = {
        "summary": "A sufficiently detailed result summary.",
        "findings": ["One concrete finding"],
        "evidence": [],
    }
    await service.submit(
        SubmitResultCommand(39_101, performer.telegram_user_id, assignment.id, uuid4(), payload)
    )
    stored = (await service.list_owned(performer.telegram_user_id))[0]
    assert stored.review_deadline_at is not None
    command_id = uuid4()
    approved = await service.finalize_review(
        assignment_id=assignment.id,
        command_id=command_id,
        now=stored.review_deadline_at,
    )
    replay = await service.finalize_review(
        assignment_id=assignment.id,
        command_id=command_id,
        now=stored.review_deadline_at,
    )
    assert approved.status is AssignmentStatus.APPROVED
    assert replay.status is AssignmentStatus.APPROVED

    _other_author, other_task = await _published_task(database, update_base=4000)
    other = await prepare_member(database, telegram_user_id=4100)
    pending = await service.accept(
        AcceptAssignmentCommand(41_100, other.telegram_user_id, other_task.id)
    )
    no_show = await service.finalize_deadline(
        task_id=other_task.id,
        command_id=uuid4(),
        now=other_task.deadline_at,
    )
    replay_no_show = await service.finalize_deadline(
        task_id=other_task.id,
        command_id=uuid4(),
        now=other_task.deadline_at,
    )
    assert [item.id for item in no_show] == [pending.id]
    assert replay_no_show == ()
    await database.dispose()


async def test_concurrent_accept_serializes_last_slot_and_active_limit(database_url: str) -> None:
    """Only one last-slot claimant and one fourth active assignment can commit."""
    database = Database(database_url)
    _author, last_slot_task = await _published_task(database, update_base=4200)
    first = await prepare_member(database, telegram_user_id=4300)
    second = await prepare_member(database, telegram_user_id=4400)
    service = AssignmentService(database.unit_of_work)
    claims = await asyncio.gather(
        service.accept(AcceptAssignmentCommand(43_100, first.telegram_user_id, last_slot_task.id)),
        service.accept(AcceptAssignmentCommand(44_100, second.telegram_user_id, last_slot_task.id)),
        return_exceptions=True,
    )
    assert sum(not isinstance(item, BaseException) for item in claims) == 1

    performer = await prepare_member(database, telegram_user_id=4500)
    tasks = [await _published_task(database, update_base=4600 + offset * 10) for offset in range(4)]
    for index in range(2):
        await service.accept(
            AcceptAssignmentCommand(45_100 + index, performer.telegram_user_id, tasks[index][1].id)
        )
    competing = await asyncio.gather(
        service.accept(AcceptAssignmentCommand(45_102, performer.telegram_user_id, tasks[2][1].id)),
        service.accept(AcceptAssignmentCommand(45_103, performer.telegram_user_id, tasks[3][1].id)),
        return_exceptions=True,
    )
    assert sum(not isinstance(item, BaseException) for item in competing) == 1
    assert len(await service.list_owned(performer.telegram_user_id)) == 3

    owner, cancellable = await _published_task(database, update_base=4900)
    contender = await prepare_member(database, telegram_user_id=4910)
    task_service = TaskService(database.unit_of_work)
    task_race = await asyncio.gather(
        service.accept(AcceptAssignmentCommand(49_200, contender.telegram_user_id, cancellable.id)),
        task_service.cancel(
            update_id=49_201,
            actor_telegram_user_id=owner.telegram_user_id,
            task_id=cancellable.id,
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(item, BaseException) for item in task_race) == 1
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        assignment_count = await session.scalar(
            select(func.count(AssignmentModel.id)).where(AssignmentModel.task_id == cancellable.id)
        )
        stored_task = await session.get(TaskModel, cancellable.id)
    assert stored_task is not None
    assert (assignment_count, stored_task.status) in {
        (0, "cancelled"),
        (1, "published"),
    }
    await database.dispose()


async def test_accept_rejections_leave_no_receipts_or_assignments(database_url: str) -> None:
    """Self, duplicate, paused, low-level, and expired accepts fail without effects."""
    database = Database(database_url)
    author, task = await _published_task(database, update_base=4950)
    service = AssignmentService(database.unit_of_work)
    with pytest.raises(PermissionError):
        await service.accept(AcceptAssignmentCommand(49_600, author.telegram_user_id, task.id))

    performer = await prepare_member(database, telegram_user_id=4960)
    await service.accept(AcceptAssignmentCommand(49_601, performer.telegram_user_id, task.id))
    with pytest.raises(AssignmentError):
        await service.accept(AcceptAssignmentCommand(49_602, performer.telegram_user_id, task.id))

    paused = await prepare_member(database, telegram_user_id=4970)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        paused_model = await session.get(MemberModel, paused.id)
        assert paused_model is not None
        paused_model.status = "paused"
    with pytest.raises(PermissionError):
        await service.accept(AcceptAssignmentCommand(49_603, paused.telegram_user_id, task.id))

    _admin, advanced_task_id = await _community_task(database, update_base=4980, minimum_level=9)
    beginner = await prepare_member(database, telegram_user_id=4985)
    with pytest.raises(PermissionError):
        await service.accept(
            AcceptAssignmentCommand(49_604, beginner.telegram_user_id, advanced_task_id)
        )

    expired_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    _admin, expired_task_id = await _community_task(
        database, update_base=4990, deadline_at=expired_at
    )
    late = await prepare_member(database, telegram_user_id=4995)
    with pytest.raises(AssignmentError, match="deadline"):
        await service.accept(
            AcceptAssignmentCommand(49_605, late.telegram_user_id, expired_task_id)
        )

    async with sessions() as session:
        rejected_receipts = await session.scalar(
            select(func.count(ProcessedTelegramUpdateModel.update_id)).where(
                ProcessedTelegramUpdateModel.update_id.in_((49_600, 49_602, 49_603, 49_604, 49_605))
            )
        )
    assert rejected_receipts == 0
    await database.dispose()


async def test_community_settlement_and_new_update_business_replay(database_url: str) -> None:
    """Community rewards need no reserve and a terminal decision replay stores a receipt."""
    database = Database(database_url)
    admin, task_id = await _community_task(database, update_base=5000, performer_slots=2)
    performer = await prepare_member(database, telegram_user_id=5100)
    service = AssignmentService(database.unit_of_work)
    assignment = await service.accept(
        AcceptAssignmentCommand(51_100, performer.telegram_user_id, task_id)
    )
    payload = {
        "summary": "A sufficiently detailed result summary.",
        "findings": ["One concrete finding"],
        "evidence": [],
    }
    await service.submit(
        SubmitResultCommand(51_101, performer.telegram_user_id, assignment.id, uuid4(), payload)
    )
    decision_id = uuid4()
    approved = await service.decide(
        DecideAssignmentCommand(
            51_102,
            admin.telegram_user_id,
            assignment.id,
            decision_id,
            AssignmentDecision.FULL,
        )
    )
    replay = await service.decide(
        DecideAssignmentCommand(
            51_103,
            admin.telegram_user_id,
            assignment.id,
            decision_id,
            AssignmentDecision.FULL,
        )
    )
    with pytest.raises(AssignmentError, match="another review outcome"):
        await service.decide(
            DecideAssignmentCommand(
                51_104,
                admin.telegram_user_id,
                assignment.id,
                uuid4(),
                AssignmentDecision.FULL,
            )
        )
    assert approved.status is AssignmentStatus.APPROVED
    assert replay.terminal_command_id == decision_id
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        reward_types = (
            await session.scalars(
                select(AccountTransactionModel.transaction_type).where(
                    AccountTransactionModel.assignment_id == assignment.id
                )
            )
        ).all()
        receipt = await session.get(ProcessedTelegramUpdateModel, 51_103)
        conflicting_receipt = await session.get(ProcessedTelegramUpdateModel, 51_104)
    assert reward_types == ["community_task_reward"]
    assert receipt is not None
    assert conflicting_receipt is None
    next_performer = await prepare_member(database, telegram_user_id=5110)
    next_assignment = await service.accept(
        AcceptAssignmentCommand(51_110, next_performer.telegram_user_id, task_id)
    )
    assert next_assignment.slot_number == 2

    outcomes = (
        (5010, 5120, AssignmentDecision.PARTIAL),
        (5020, 5130, AssignmentDecision.REJECT),
    )
    settled_ids = [assignment.id]
    for offset, (base, telegram_user_id, decision_kind) in enumerate(outcomes, start=1):
        reviewer, other_task_id = await _community_task(database, update_base=base)
        await prepare_member(database, telegram_user_id=telegram_user_id)
        other_assignment = await service.accept(
            AcceptAssignmentCommand(51_200 + offset * 10, telegram_user_id, other_task_id)
        )
        await service.submit(
            SubmitResultCommand(
                51_201 + offset * 10,
                telegram_user_id,
                other_assignment.id,
                uuid4(),
                payload,
            )
        )
        decided = await service.decide(
            DecideAssignmentCommand(
                51_202 + offset * 10,
                reviewer.telegram_user_id,
                other_assignment.id,
                uuid4(),
                decision_kind,
            )
        )
        if decision_kind is AssignmentDecision.REJECT:
            assert decided.reject_dispute_deadline_at is not None
            decided = await service.finalize_rejection(
                assignment_id=decided.id,
                command_id=uuid4(),
                now=decided.reject_dispute_deadline_at,
            )
            assert decided.status is AssignmentStatus.REJECTED
        else:
            assert decided.status is AssignmentStatus.PARTIALLY_APPROVED
        settled_ids.append(other_assignment.id)

    _reviewer, no_show_task_id = await _community_task(database, update_base=5030)
    no_show_performer = await prepare_member(database, telegram_user_id=5140)
    no_show_assignment = await service.accept(
        AcceptAssignmentCommand(51_240, no_show_performer.telegram_user_id, no_show_task_id)
    )
    async with sessions() as session:
        no_show_task = await session.get(TaskModel, no_show_task_id)
    assert no_show_task is not None
    finalized = await service.finalize_deadline(
        task_id=no_show_task_id, command_id=uuid4(), now=no_show_task.deadline_at
    )
    assert finalized[0].status is AssignmentStatus.NO_SHOW
    settled_ids.append(no_show_assignment.id)
    async with sessions() as session:
        refunds = await session.scalar(
            select(func.count(AccountTransactionModel.id)).where(
                AccountTransactionModel.assignment_id.in_(settled_ids),
                AccountTransactionModel.transaction_type == "task_reward_refunded",
            )
        )
    assert refunds == 0
    await database.dispose()


async def test_deadline_refunds_all_slots_and_history_is_sql_immutable(database_url: str) -> None:
    """Deadline returns occupied and unfilled reserve; history rejects direct mutation."""
    database = Database(database_url)
    author, task = await _published_task(database, update_base=5200)
    performer = await prepare_member(database, telegram_user_id=5300)
    service = AssignmentService(database.unit_of_work)
    assignment = await service.accept(
        AcceptAssignmentCommand(53_100, performer.telegram_user_id, task.id)
    )
    await service.cancel(
        update_id=53_101,
        actor_telegram_user_id=performer.telegram_user_id,
        assignment_id=assignment.id,
        reason="Cannot complete before the deadline",
    )
    await service.finalize_deadline(task_id=task.id, command_id=uuid4(), now=task.deadline_at)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        refunded = await session.scalar(
            select(func.sum(AccountTransactionModel.credit_delta)).where(
                AccountTransactionModel.task_id == task.id,
                AccountTransactionModel.transaction_type == "task_reward_refunded",
            )
        )
        reserve = await session.scalar(
            select(func.sum(AccountTransactionModel.credit_delta)).where(
                AccountTransactionModel.member_id == author.id,
                AccountTransactionModel.transaction_type == "task_reward_reserved",
            )
        )
    assert reserve is not None
    assert refunded == -reserve == task.reserved_credit_total

    with pytest.raises(DBAPIError):
        async with database.engine.begin() as connection:
            await connection.execute(
                text("UPDATE reliability_events SET reason = 'tampered' WHERE assignment_id = :id"),
                {"id": assignment.id},
            )
    await database.dispose()


async def test_decision_fault_rolls_back_and_retry_settles_once(database_url: str) -> None:
    """A fault after ledger flush rolls back result settlement and permits one retry."""
    database = Database(database_url)
    author, task = await _published_task(database, update_base=5400)
    performer = await prepare_member(database, telegram_user_id=5500)
    service = AssignmentService(database.unit_of_work)
    assignment = await service.accept(
        AcceptAssignmentCommand(55_100, performer.telegram_user_id, task.id)
    )
    payload = {
        "summary": "A sufficiently detailed result summary.",
        "findings": ["One concrete finding"],
        "evidence": [],
    }
    await service.submit(
        SubmitResultCommand(55_101, performer.telegram_user_id, assignment.id, uuid4(), payload)
    )

    def fail_after_ledger() -> None:
        message = "injected ledger fault"
        raise RuntimeError(message)

    failing = AssignmentService(
        lambda: database.unit_of_work(after_ledger_flushed=fail_after_ledger)
    )
    decision = DecideAssignmentCommand(
        55_102,
        author.telegram_user_id,
        assignment.id,
        uuid4(),
        AssignmentDecision.FULL,
    )
    with pytest.raises(RuntimeError, match="injected ledger fault"):
        await failing.decide(decision)
    stored = (await service.list_owned(performer.telegram_user_id))[0]
    assert stored.status is AssignmentStatus.SUBMITTED
    approved = await service.decide(decision)
    assert approved.status is AssignmentStatus.APPROVED
    await database.dispose()


@pytest.mark.parametrize("checkpoint", ["assignment", "result", "outbox", "receipt"])
async def test_assignment_fault_checkpoints_roll_back_and_retry(
    database_url: str, checkpoint: str
) -> None:
    """Every assignment staging boundary rolls back before a successful retry."""
    database = Database(database_url)
    _author, task = await _published_task(database, update_base=5800)
    performer = await prepare_member(database, telegram_user_id=5900)

    def fail() -> None:
        message = f"injected {checkpoint} fault"
        raise RuntimeError(message)

    def failing_uow():  # noqa: ANN202
        if checkpoint == "assignment":
            return database.unit_of_work(after_assignment_inserted=fail)
        if checkpoint == "result":
            return database.unit_of_work(after_assignment_result_staged=fail)
        if checkpoint == "outbox":
            return database.unit_of_work(after_assignment_outbox_staged=fail)
        return database.unit_of_work(after_assignment_receipt_staged=fail)

    failing = AssignmentService(failing_uow)
    regular = AssignmentService(database.unit_of_work)
    update_id = 59_100
    if checkpoint == "assignment":
        command = AcceptAssignmentCommand(update_id, performer.telegram_user_id, task.id)
        with pytest.raises(RuntimeError, match=checkpoint):
            await failing.accept(command)
        assignment = await regular.accept(command)
    else:
        assignment = await regular.accept(
            AcceptAssignmentCommand(59_099, performer.telegram_user_id, task.id)
        )
        payload = {
            "summary": "A sufficiently detailed result summary.",
            "findings": ["One concrete finding"],
            "evidence": [],
        }
        command = SubmitResultCommand(
            update_id, performer.telegram_user_id, assignment.id, uuid4(), payload
        )
        with pytest.raises(RuntimeError, match=checkpoint):
            await failing.submit(command)
        result = await regular.submit(command)
        assert result.version == 1

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        receipt = await session.get(ProcessedTelegramUpdateModel, update_id)
        assignment_count = await session.scalar(
            select(func.count(AssignmentModel.id)).where(AssignmentModel.task_id == task.id)
        )
    assert receipt is not None
    assert assignment_count == 1
    assert assignment.id is not None
    await database.dispose()


async def test_persistent_telegram_submission_survives_router_restart(database_url: str) -> None:
    """Synthetic accept, result v1/v2, restart, stale callback, and author full."""
    database = Database(database_url)
    author, task = await _published_task(database, update_base=5600)
    performer = await prepare_member(database, telegram_user_id=5700)
    service = AssignmentService(database.unit_of_work)
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    actor = User(id=performer.telegram_user_id, is_bot=False, first_name="Performer")
    author_actor = User(id=author.telegram_user_id, is_bot=False, first_name="Author")

    def message_update(update_id: int, value: str, user: User = actor) -> Update:
        return Update(
            update_id=update_id,
            message=Message(
                message_id=update_id,
                date=datetime.datetime.now(datetime.UTC),
                chat=Chat(id=user.id, type="private"),
                from_user=user,
                text=value,
            ),
        )

    def callback_update(update_id: int, data: str, user: User = actor) -> Update:
        return Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=f"assignment-{update_id}",
                from_user=user,
                chat_instance="assignments",
                data=data,
                message=Message(
                    message_id=update_id,
                    date=datetime.datetime.now(datetime.UTC),
                    chat=Chat(id=user.id, type="private"),
                    text="preview",
                ),
            ),
        )

    dispatcher = Dispatcher()
    dispatcher.include_router(build_assignment_router(service))
    await dispatcher.feed_update(bot, callback_update(57_100, f"task:accept:{task.id}"))
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        assignment = await session.scalar(
            select(AssignmentModel).where(AssignmentModel.task_id == task.id)
        )
    assert assignment is not None
    await dispatcher.feed_update(bot, message_update(57_101, f"/assignment_submit {assignment.id}"))
    async with sessions() as session:
        draft = await session.scalar(
            select(AssignmentSubmissionDraftModel).where(
                AssignmentSubmissionDraftModel.assignment_id == assignment.id,
                AssignmentSubmissionDraftModel.submitted_result_id.is_(None),
            )
        )
    assert draft is not None
    payload = (
        '{"summary":"A sufficiently detailed result summary.",'
        '"findings":["One concrete finding"],"evidence":[]}'
    )
    await dispatcher.feed_update(
        bot,
        message_update(57_102, f"/assignment_result {draft.id} {draft.revision} {payload}"),
    )
    callback_data = capture.callbacks[-1]
    assert len(callback_data.encode()) <= 64

    dispatcher = Dispatcher()
    dispatcher.include_router(build_assignment_router(AssignmentService(database.unit_of_work)))
    await dispatcher.feed_update(bot, callback_update(57_103, callback_data))
    await dispatcher.feed_update(bot, callback_update(57_103, callback_data))

    await dispatcher.feed_update(bot, message_update(57_104, f"/assignment_submit {assignment.id}"))
    async with sessions() as session:
        second_draft = await session.scalar(
            select(AssignmentSubmissionDraftModel).where(
                AssignmentSubmissionDraftModel.assignment_id == assignment.id,
                AssignmentSubmissionDraftModel.submitted_result_id.is_(None),
            )
        )
    assert second_draft is not None
    assert second_draft.id != draft.id
    payload_v2 = payload.replace("One concrete finding", "A corrected concrete finding")
    await dispatcher.feed_update(
        bot,
        message_update(
            57_105,
            f"/assignment_result {second_draft.id} {second_draft.revision} {payload_v2}",
        ),
    )
    callback_v2 = capture.callbacks[-1]
    prefix, _, revision = callback_v2.rpartition(":")
    await dispatcher.feed_update(bot, callback_update(57_106, f"{prefix}:{int(revision) + 1}"))
    await dispatcher.feed_update(bot, callback_update(57_107, callback_v2))
    await dispatcher.feed_update(
        bot,
        callback_update(
            57_108,
            f"assign:review:{assignment.id.hex}:full",
            author_actor,
        ),
    )
    async with sessions() as session:
        result_count = await session.scalar(
            select(func.count(AssignmentResultVersionModel.id)).where(
                AssignmentResultVersionModel.assignment_id == assignment.id
            )
        )
        receipt_count = await session.scalar(
            select(func.count(ProcessedTelegramUpdateModel.update_id)).where(
                ProcessedTelegramUpdateModel.update_id.in_(
                    (57_100, 57_101, 57_102, 57_103, 57_104, 57_105, 57_106, 57_107, 57_108)
                )
            )
        )
        stored = await session.get(AssignmentModel, assignment.id)
    assert result_count == 2
    assert receipt_count == 8
    assert stored is not None
    assert stored.status == AssignmentStatus.APPROVED.value
    assert sum("Результат отправлен" in value for value in capture.texts) == 3
    assert any("Не удалось отправить результат" in value for value in capture.texts)
    await bot.session.close()
    await database.dispose()
