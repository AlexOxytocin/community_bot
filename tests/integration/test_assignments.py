"""PostgreSQL tests for the complete task assignment exchange."""

# ruff: noqa: PLR0915
from __future__ import annotations

import asyncio
import datetime
from uuid import uuid4

import pytest
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
    AuditEventModel,
    MemberModel,
    OutboxEventModel,
    ProcessedTelegramUpdateModel,
    ReliabilityEventModel,
    TaskModel,
)
from tests.integration.test_task_creation import (
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


async def test_web_actor_replay_and_natural_assignment_idempotency(
    database_url: str,
) -> None:
    database = Database(database_url)
    _author, task = await _published_task(database, update_base=3190)
    performer = await prepare_member(database, telegram_user_id=3191)
    other = await prepare_member(database, telegram_user_id=3192)
    service = AssignmentService(database.unit_of_work)

    first_command = AcceptAssignmentCommand(
        8_000_000_000_031_901,
        None,
        task.id,
        actor_member_id=performer.id,
    )
    first, replayed = await asyncio.gather(
        service.accept(first_command),
        service.accept(first_command),
    )
    assert first.id == replayed.id

    _race_author, race_task = await _published_task(database, update_base=3193)
    different_first, different_second = await asyncio.gather(
        service.accept(
            AcceptAssignmentCommand(
                8_000_000_000_031_902,
                None,
                race_task.id,
                actor_member_id=performer.id,
            )
        ),
        service.accept(
            AcceptAssignmentCommand(
                8_000_000_000_031_903,
                None,
                race_task.id,
                actor_member_id=performer.id,
            )
        ),
    )
    assert different_first.id == different_second.id
    replay = await service.accept(first_command)
    assert replay.id == first.id

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        stored_performer = await session.get(MemberModel, performer.id)
        assert stored_performer is not None
        stored_performer.status = "paused"
    status_changed_replay = await service.accept(first_command)
    assert status_changed_replay.id == first.id
    with pytest.raises(PermissionError):
        await service.accept(
            AcceptAssignmentCommand(
                8_000_000_000_031_904,
                None,
                task.id,
                actor_member_id=performer.id,
            )
        )
    async with sessions.begin() as session:
        stored_performer = await session.get(MemberModel, performer.id)
        assert stored_performer is not None
        stored_performer.status = "active"

    with pytest.raises(AssignmentError, match="another operation"):
        await service.accept(
            AcceptAssignmentCommand(8_000_000_000_031_901, None, task.id, actor_member_id=other.id)
        )

    _other_author, other_task = await _published_task(database, update_base=3250)
    with pytest.raises(AssignmentError, match="another operation"):
        await service.accept(
            AcceptAssignmentCommand(
                8_000_000_000_031_901,
                None,
                other_task.id,
                actor_member_id=performer.id,
            )
        )

    async with sessions.begin() as session:
        stored_assignment = await session.get(AssignmentModel, first.id)
        assert stored_assignment is not None
        stored_assignment.status = AssignmentStatus.CANCELLED.value
    with pytest.raises(AssignmentError, match="cannot be accepted again"):
        await service.accept(
            AcceptAssignmentCommand(
                8_000_000_000_031_905,
                None,
                task.id,
                actor_member_id=performer.id,
            )
        )

    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count(AssignmentModel.id)).where(
                    AssignmentModel.task_id.in_((task.id, race_task.id)),
                    AssignmentModel.performer_id == performer.id,
                )
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count(ReliabilityEventModel.id)).where(
                    ReliabilityEventModel.assignment_id.in_((first.id, different_first.id)),
                    ReliabilityEventModel.event_type == "accepted",
                )
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count(AuditEventModel.id)).where(
                    AuditEventModel.action == "assignment_accepted",
                    AuditEventModel.entity_id.in_((str(first.id), str(different_first.id))),
                )
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count(OutboxEventModel.id)).where(
                    OutboxEventModel.business_key.in_(
                        (
                            f"assignment:{first.id}:accepted",
                            f"assignment:{different_first.id}:accepted",
                        )
                    )
                )
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count(ProcessedTelegramUpdateModel.update_id)).where(
                    ProcessedTelegramUpdateModel.update_id.in_(
                        (
                            8_000_000_000_031_901,
                            8_000_000_000_031_902,
                            8_000_000_000_031_903,
                        )
                    )
                )
            )
            == 2
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
