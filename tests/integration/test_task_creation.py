from __future__ import annotations

import asyncio
import datetime
import os
from dataclasses import replace
from pathlib import Path
from typing import TypeVar
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.assignments import (
    AcceptAssignmentCommand,
    AssignmentService,
    DecideAssignmentCommand,
    SubmitResultCommand,
)
from community_bot.application.economy import (
    EconomyService,
    ProductConfigActivationCommand,
    ProductConfigBootstrapCoordinator,
    ProductConfigService,
)
from community_bot.application.identity import ActorContext
from community_bot.application.tasks import (
    AdvanceDraftCommand,
    PublishedTask,
    PublishTaskCommand,
    SaveWebTaskDraftCommand,
    TaskService,
)
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.domain.assignments import AssignmentDecision
from community_bot.domain.catalog import TaskFormat
from community_bot.domain.economy import (
    AdministrativeContext,
    InsufficientBalanceError,
    admin_adjustment,
    starting_grant,
)
from community_bot.domain.members import MemberRole, MemberStatus
from community_bot.domain.tasks import (
    StaleTaskDraftError,
    TaskDraftStep,
    TaskError,
    TaskKind,
    TaskStatus,
    TaskTimeSize,
)
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AssignmentModel,
    AuditEventModel,
    MemberModel,
    OutboxEventModel,
    ProcessedTelegramUpdateModel,
    TaskCancellationResponseModel,
    TaskCategoryModel,
    TaskCreationDraftModel,
    TaskModel,
    TaskTemplateModel,
)
from community_bot.infrastructure.db.models import TestRunModel as DbTestRunModel
from community_bot.infrastructure.db.models import (
    TestRunParticipantModel as DbTestRunParticipantModel,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
CONFIG_PATH = Path(__file__).parents[2] / "config" / "product-config.v1.json"


def actor_context(member: MemberModel) -> ActorContext:
    return ActorContext(member.id, "telegram", datetime.datetime.now(datetime.UTC))


TelegramType = TypeVar("TelegramType")


async def add_member(
    database: Database,
    *,
    telegram_user_id: int,
    role: MemberRole = MemberRole.MEMBER,
    status: MemberStatus = MemberStatus.ACTIVE,
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
            level_number=9,
        )
        session.add(member)
    return member


async def prepare_config(database: Database, admin: MemberModel) -> None:
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=uuid4(),
    )


async def template_id(database: Database, code: str) -> UUID:
    async with database.engine.connect() as connection:
        value = await connection.scalar(
            select(TaskTemplateModel.id).where(TaskTemplateModel.code == code)
        )
    assert value is not None
    return value


async def prepare_member(database: Database, *, telegram_user_id: int) -> MemberModel:
    admin = await add_member(
        database,
        telegram_user_id=telegram_user_id + 1000,
        role=MemberRole.ADMINISTRATOR,
    )
    member = await add_member(database, telegram_user_id=telegram_user_id)
    await prepare_config(database, admin)
    await EconomyService(database.unit_of_work).apply_one(starting_grant(member.id))
    return member


async def complete_preview(
    service: TaskService,
    *,
    member: MemberModel,
    selected_template_id: UUID,
    update_base: int,
    performer_slots: int = 1,
) -> tuple[UUID, int]:
    draft = await service.start(
        update_id=update_base,
        actor_telegram_user_id=member.telegram_user_id,
        template_id=selected_template_id,
    )
    assert draft is not None
    values: list[object] = [
        {
            "context": "Need a detailed and practical review.",
            "materials": "https://example.com/item",
            "constraints": "Do not publish private information.",
        },
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1),
        (TaskFormat.ONLINE, None),
        {"url": "https://example.com/item"},
        performer_slots,
    ]
    steps = [
        TaskDraftStep.INPUT,
        TaskDraftStep.DEADLINE,
        TaskDraftStep.FORMAT,
        TaskDraftStep.MATERIALS,
        TaskDraftStep.SLOTS,
    ]
    current = draft
    for offset, (step, value) in enumerate(zip(steps, values, strict=True), start=1):
        current = await service.advance(
            AdvanceDraftCommand(
                update_base + offset,
                member.telegram_user_id,
                current.id,
                step,
                current.revision,
                value,
            )
        )
    preview = await service.preview(
        update_id=update_base + 6,
        actor_telegram_user_id=member.telegram_user_id,
        draft_id=current.id,
        expected_revision=current.revision,
    )
    assert preview.reserved_credit_total > 0
    return preview.draft.id, preview.draft.revision


async def category_id(database: Database, code: str) -> UUID:
    async with database.engine.connect() as connection:
        value = await connection.scalar(
            select(TaskCategoryModel.id).where(TaskCategoryModel.code == code)
        )
    assert value is not None
    return value


async def complete_freeform_preview(  # noqa: PLR0913
    service: TaskService,
    *,
    member: MemberModel,
    selected_category_id: UUID,
    update_base: int,
    kind: TaskKind = TaskKind.SOLO,
    time_size: TaskTimeSize = TaskTimeSize.S,
    performer_slots: int = 1,
    reward: int = 3,
) -> tuple[UUID, int]:
    draft = await service.start(
        update_id=update_base,
        actor_telegram_user_id=member.telegram_user_id,
        template_id=None,
    )
    assert draft is not None
    steps: list[tuple[TaskDraftStep, object]] = [
        (TaskDraftStep.TASK_KIND, kind),
        (TaskDraftStep.CATEGORY, selected_category_id),
        (TaskDraftStep.TIME_SIZE, time_size),
    ]
    if kind is TaskKind.GROUP:
        steps.append((TaskDraftStep.SLOTS, performer_slots))
    steps.extend(
        [
            (TaskDraftStep.REWARD, reward),
            (TaskDraftStep.TITLE, "Проверить новый сценарий"),
            (
                TaskDraftStep.DESCRIPTION,
                "Нужно пройти сценарий и кратко описать понятные и сложные места.",
            ),
            (
                TaskDraftStep.COMPLETION_CRITERIA,
                "Есть конкретный список наблюдений и итоговый вывод.",
            ),
            (TaskDraftStep.MATERIALS, {"text": "Дополнительные материалы не требуются"}),
            (
                TaskDraftStep.DEADLINE,
                datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1),
            ),
            (TaskDraftStep.FORMAT, (TaskFormat.ONLINE, None)),
        ]
    )
    current = draft
    for offset, (step, value) in enumerate(steps, start=1):
        current = await service.advance(
            AdvanceDraftCommand(
                update_base + offset,
                member.telegram_user_id,
                current.id,
                step,
                current.revision,
                value,
            )
        )
    preview = await service.preview(
        update_id=update_base + len(steps) + 1,
        actor_telegram_user_id=member.telegram_user_id,
        draft_id=current.id,
        expected_revision=current.revision,
    )
    assert preview.reserved_credit_total == performer_slots * reward
    return preview.draft.id, preview.draft.revision


async def test_web_draft_scope_follows_public_active_and_stale_transitions(
    database_url: str,
) -> None:
    database = Database(database_url)
    member = await prepare_member(database, telegram_user_id=20_070)
    service = TaskService(database.unit_of_work)
    category = await category_id(database, "practical_help")
    selected_template = await template_id(database, "repository_first_impression")
    template_draft = await service.start(
        update_id=8_000_000_000_070_000,
        actor_telegram_user_id=member.telegram_user_id,
        template_id=selected_template,
    )
    assert template_draft is not None
    with pytest.raises(TaskError):
        await service.publish(
            PublishTaskCommand(
                8_000_000_000_070_006,
                None,
                template_draft.id,
                template_draft.revision,
                member.id,
                "hidden-template",
            )
        )

    public = await service.start(
        update_id=8_000_000_000_070_001,
        actor_telegram_user_id=None,
        template_id=None,
        actor_member_id=member.id,
        replay_fingerprint="public-start",
    )
    assert public is not None
    assert public.id != template_draft.id
    form = SaveWebTaskDraftCommand(
        8_000_000_000_070_002,
        member.id,
        public.id,
        0,
        category,
        TaskKind.SOLO,
        TaskTimeSize.S,
        "Публичный черновик",
        "Описание публичного черновика для проверки изоляции.",
        "Есть проверяемый результат.",
        3,
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=2),
        TaskFormat.ONLINE,
        None,
        {"url": "https://example.com/public"},
        1,
        "public-save",
    )
    await service.save_web(form)

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        run = DbTestRunModel(marker="TEST-CB70-DRAFT", started_by_member_id=member.id)
        session.add(run)
        await session.flush()
        session.add(DbTestRunParticipantModel(run_id=run.id, member_id=member.id))
    assert (await service.web_state(member.id))[1] is None
    with pytest.raises(PermissionError, match="test scope"):
        await service.save_web(replace(form, update_id=8_000_000_000_070_003))

    scoped = await service.start(
        update_id=8_000_000_000_070_004,
        actor_telegram_user_id=None,
        template_id=None,
        actor_member_id=member.id,
        replay_fingerprint="scoped-start",
    )
    replay = await service.start(
        update_id=8_000_000_000_070_004,
        actor_telegram_user_id=None,
        template_id=None,
        actor_member_id=member.id,
        replay_fingerprint="scoped-start",
    )
    assert scoped is not None
    assert replay is not None
    assert scoped.id == replay.id
    assert scoped.title is None
    assert scoped.test_run_id == run.id

    async with sessions.begin() as session:
        participant = await session.get(DbTestRunParticipantModel, (run.id, member.id))
        stored_run = await session.get(DbTestRunModel, run.id)
        assert participant is not None
        assert stored_run is not None
        participant.is_active = False
        stored_run.status = "completed"
        stored_run.ended_at = datetime.datetime.now(datetime.UTC)
    assert (await service.web_state(member.id))[1] is None
    restored = await service.start(
        update_id=8_000_000_000_070_005,
        actor_telegram_user_id=None,
        template_id=None,
        actor_member_id=member.id,
        replay_fingerprint="restored-start",
    )
    assert restored is not None
    assert restored.test_run_id is None
    assert restored.title is None
    assert restored.id not in {public.id, scoped.id}
    await database.dispose()


async def scalar_count(database: Database, model: type[object]) -> int:
    async with database.engine.connect() as connection:
        value = await connection.scalar(select(func.count()).select_from(model))
    return int(value or 0)


async def test_freeform_task_publishes_without_template_and_reserves_full_budget(
    database_url: str,
) -> None:
    database = Database(database_url)
    member = await prepare_member(database, telegram_user_id=19_500)
    service = TaskService(database.unit_of_work)
    selected_category = await category_id(database, "evaluation_testing")

    categories = await service.task_categories(member.telegram_user_id)
    assert "evaluation_testing" in {item.code for item in categories}
    assert "community_development" not in {item.code for item in categories}

    draft_id, revision = await complete_freeform_preview(
        service,
        member=member,
        selected_category_id=selected_category,
        update_base=19_500,
        kind=TaskKind.GROUP,
        time_size=TaskTimeSize.M,
        performer_slots=2,
        reward=4,
    )
    task = await service.publish(
        PublishTaskCommand(19_600, member.telegram_user_id, draft_id, revision)
    )
    replay = await service.publish(
        PublishTaskCommand(19_600, member.telegram_user_id, draft_id, revision)
    )

    assert isinstance(task, PublishedTask)
    assert isinstance(replay, PublishedTask)
    assert replay.id == task.id
    assert task.template_id is None
    assert task.template_version is None
    assert task.category_name == "Оценка и тестирование"
    assert task.time_size is TaskTimeSize.M
    assert task.performer_slots == 2
    assert task.credit_reward_per_performer == 4
    assert task.reserved_credit_total == 8
    async with async_sessionmaker(database.engine, expire_on_commit=False)() as session:
        persisted = await session.get(MemberModel, member.id)
    assert persisted is not None
    assert persisted.credit_balance_cached == 2
    await database.dispose()


async def test_template_draft_edits_return_directly_to_preview(database_url: str) -> None:
    database = Database(database_url)
    member = await prepare_member(database, telegram_user_id=19_650)
    service = TaskService(database.unit_of_work)
    selected_template = await template_id(database, "repository_first_impression")
    draft_id, original_revision = await complete_preview(
        service,
        member=member,
        selected_template_id=selected_template,
        update_base=19_650,
    )
    changes: tuple[tuple[TaskDraftStep, object], ...] = (
        (
            TaskDraftStep.INPUT,
            {
                "context": "Updated practical review context.",
                "materials": "https://example.com/updated-item",
                "constraints": "Keep private information private.",
            },
        ),
        (TaskDraftStep.MATERIALS, {"url": "https://example.com/updated-item"}),
        (
            TaskDraftStep.DEADLINE,
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=2),
        ),
        (TaskDraftStep.FORMAT, (TaskFormat.ONLINE, None)),
        (TaskDraftStep.SLOTS, 1),
    )
    next_update = 19_670
    for step, value in changes:
        editing = await service.edit_draft_step(
            update_id=next_update,
            actor_telegram_user_id=member.telegram_user_id,
            draft_id=draft_id,
            expected_revision=original_revision,
            step=step,
        )
        next_update += 1
        assert editing.current_step is step
        updated = await service.advance(
            AdvanceDraftCommand(
                next_update,
                member.telegram_user_id,
                draft_id,
                step,
                editing.revision,
                value,
            )
        )
        next_update += 1
        assert updated.current_step is TaskDraftStep.PREVIEW
    await database.dispose()


async def test_group_intake_close_blocks_new_accepts_and_keeps_submission_right(
    database_url: str,
) -> None:
    database = Database(database_url)
    author = await prepare_member(database, telegram_user_id=19_700)
    performer = await prepare_member(database, telegram_user_id=19_701)
    stranger = await prepare_member(database, telegram_user_id=19_702)
    task_service = TaskService(database.unit_of_work)
    assignment_service = AssignmentService(database.unit_of_work)
    selected_category = await category_id(database, "promotion")
    draft_id, revision = await complete_freeform_preview(
        task_service,
        member=author,
        selected_category_id=selected_category,
        update_base=19_700,
        kind=TaskKind.GROUP,
        time_size=TaskTimeSize.S,
        performer_slots=3,
        reward=2,
    )
    task = await task_service.publish(
        PublishTaskCommand(19_800, author.telegram_user_id, draft_id, revision)
    )
    assignment = await assignment_service.accept(
        AcceptAssignmentCommand(19_801, performer.telegram_user_id, task.id)
    )

    outcome = await task_service.request_cancellation(
        update_id=19_802,
        actor_telegram_user_id=author.telegram_user_id,
        task_id=task.id,
    )

    assert outcome.status == "pending"
    assert outcome.task.status is TaskStatus.CLOSED_FOR_NEW_PERFORMERS
    available_to_stranger = await task_service.list_available(actor=actor_context(stranger))
    assert not available_to_stranger.items
    async with async_sessionmaker(database.engine, expire_on_commit=False)() as session:
        response_id = await session.scalar(select(TaskCancellationResponseModel.id))
        persisted_author = await session.get(MemberModel, author.id)
    assert response_id is not None
    assert persisted_author is not None
    assert persisted_author.credit_balance_cached == 8

    decline = await task_service.respond_cancellation(
        update_id=19_803,
        actor_telegram_user_id=performer.telegram_user_id,
        response_id=response_id,
        accepted=False,
    )
    assert decline.status == "declined"
    assert decline.task.status is TaskStatus.CLOSED_FOR_NEW_PERFORMERS
    result = await assignment_service.submit(
        SubmitResultCommand(
            19_804,
            performer.telegram_user_id,
            assignment.id,
            uuid4(),
            {"result": "Подробно описал выполненную работу и приложил вывод."},
        )
    )
    assert result.version == 1
    async with async_sessionmaker(database.engine, expire_on_commit=False)() as session:
        stored_assignment = await session.get(AssignmentModel, assignment.id)
    assert stored_assignment is not None
    assert stored_assignment.status == "submitted"
    await database.dispose()


async def test_partially_completed_group_can_release_its_free_slot_reserve(
    database_url: str,
) -> None:
    database = Database(database_url)
    author = await prepare_member(database, telegram_user_id=19_750)
    performer = await add_member(database, telegram_user_id=19_751)
    task_service = TaskService(database.unit_of_work)
    assignment_service = AssignmentService(database.unit_of_work)
    selected_category = await category_id(database, "promotion")
    draft_id, revision = await complete_freeform_preview(
        task_service,
        member=author,
        selected_category_id=selected_category,
        update_base=19_750,
        kind=TaskKind.GROUP,
        time_size=TaskTimeSize.S,
        performer_slots=2,
        reward=2,
    )
    task = await task_service.publish(
        PublishTaskCommand(19_850, author.telegram_user_id, draft_id, revision)
    )
    assignment = await assignment_service.accept(
        AcceptAssignmentCommand(19_851, performer.telegram_user_id, task.id)
    )
    await assignment_service.submit(
        SubmitResultCommand(
            19_852,
            performer.telegram_user_id,
            assignment.id,
            uuid4(),
            {"result": "Проверил сценарий и подробно описал наблюдения."},
        )
    )
    approved = await assignment_service.decide(
        DecideAssignmentCommand(
            19_853,
            author.telegram_user_id,
            assignment.id,
            uuid4(),
            AssignmentDecision.FULL,
        )
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        stored_task = await session.get(TaskModel, task.id)
        assert stored_task is not None
        # Preserve a legacy state produced by the old live-smoke workflow:
        # one slot was paid while another stayed reserved and unoccupied.
        stored_task.status = TaskStatus.PARTIALLY_COMPLETED.value

    outcome = await task_service.request_cancellation(
        update_id=19_854,
        actor_telegram_user_id=author.telegram_user_id,
        task_id=task.id,
    )

    assert outcome.status == "closed"
    assert outcome.task.status is TaskStatus.CLOSED_FOR_NEW_PERFORMERS
    async with sessions() as session:
        persisted_author = await session.get(MemberModel, author.id)
        persisted_performer = await session.get(MemberModel, performer.id)
        persisted_assignment = await session.get(AssignmentModel, assignment.id)
        refund = await session.scalar(
            select(AccountTransactionModel).where(
                AccountTransactionModel.idempotency_key == f"task_close:{task.id}:free_slots:refund"
            )
        )
    assert persisted_author is not None
    assert persisted_author.credit_balance_cached == 8
    assert persisted_performer is not None
    assert persisted_performer.credit_balance_cached == 2
    assert persisted_assignment is not None
    assert approved.id == persisted_assignment.id
    assert persisted_assignment.status == "approved"
    assert refund is not None
    assert refund.credit_delta == 2
    await database.dispose()


async def test_partially_completed_task_without_free_slots_cannot_be_reopened(
    database_url: str,
) -> None:
    database = Database(database_url)
    author = await prepare_member(database, telegram_user_id=19_760)
    first_performer = await add_member(database, telegram_user_id=19_761)
    second_performer = await add_member(database, telegram_user_id=19_762)
    task_service = TaskService(database.unit_of_work)
    assignment_service = AssignmentService(database.unit_of_work)
    selected_category = await category_id(database, "promotion")
    draft_id, revision = await complete_freeform_preview(
        task_service,
        member=author,
        selected_category_id=selected_category,
        update_base=19_760,
        kind=TaskKind.GROUP,
        time_size=TaskTimeSize.S,
        performer_slots=2,
        reward=2,
    )
    task = await task_service.publish(
        PublishTaskCommand(19_860, author.telegram_user_id, draft_id, revision)
    )
    assignments = [
        await assignment_service.accept(
            AcceptAssignmentCommand(19_861, first_performer.telegram_user_id, task.id)
        ),
        await assignment_service.accept(
            AcceptAssignmentCommand(19_862, second_performer.telegram_user_id, task.id)
        ),
    ]
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        stored_task = await session.get(TaskModel, task.id)
        assert stored_task is not None
        stored_task.status = TaskStatus.PARTIALLY_COMPLETED.value

    with pytest.raises(TaskError, match="no free performer slots"):
        await task_service.request_cancellation(
            update_id=19_863,
            actor_telegram_user_id=author.telegram_user_id,
            task_id=task.id,
        )

    async with sessions() as session:
        persisted_task = await session.get(TaskModel, task.id)
        persisted_author = await session.get(MemberModel, author.id)
        assignment_count = await session.scalar(
            select(func.count(AssignmentModel.id)).where(AssignmentModel.task_id == task.id)
        )
        free_slot_refund = await session.scalar(
            select(AccountTransactionModel).where(
                AccountTransactionModel.idempotency_key == f"task_close:{task.id}:free_slots:refund"
            )
        )
    assert len(assignments) == 2
    assert persisted_task is not None
    assert persisted_task.status == TaskStatus.PARTIALLY_COMPLETED.value
    assert persisted_author is not None
    assert persisted_author.credit_balance_cached == 6
    assert assignment_count == 2
    assert free_slot_refund is None
    await database.dispose()


async def test_persistent_preview_publish_replay_and_cancel(database_url: str) -> None:
    database = Database(database_url)
    member = await prepare_member(database, telegram_user_id=2000)
    selected = await template_id(database, "repository_first_impression")
    service = TaskService(database.unit_of_work)
    draft_id, revision = await complete_preview(
        service,
        member=member,
        selected_template_id=selected,
        update_base=20_000,
    )

    restarted = TaskService(database.unit_of_work)
    current = await restarted.start(
        update_id=20_010,
        actor_telegram_user_id=member.telegram_user_id,
        template_id=None,
    )
    assert current is not None
    assert current.id == draft_id
    before_ledger = await scalar_count(database, AccountTransactionModel)
    task = await restarted.publish(
        PublishTaskCommand(20_011, member.telegram_user_id, draft_id, revision)
    )
    replay = await restarted.publish(
        PublishTaskCommand(20_011, member.telegram_user_id, draft_id, revision)
    )
    assert replay.id == task.id
    assert await scalar_count(database, TaskModel) == 1
    assert await scalar_count(database, AccountTransactionModel) == before_ledger + 1
    assert await scalar_count(database, OutboxEventModel) == 1
    owned = await restarted.list_owned(actor_telegram_user_id=member.telegram_user_id)
    assert [item.id for item in owned] == [task.id]
    with pytest.raises(PermissionError):
        await restarted.validate_acceptance(
            task_id=task.id, actor_telegram_user_id=member.telegram_user_id
        )

    cancelled = await restarted.cancel(
        update_id=20_012,
        actor_telegram_user_id=member.telegram_user_id,
        task_id=task.id,
    )
    replay_cancel = await restarted.cancel(
        update_id=20_012,
        actor_telegram_user_id=member.telegram_user_id,
        task_id=task.id,
    )
    assert cancelled.status is replay_cancel.status is TaskStatus.CANCELLED
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        model = await session.get(MemberModel, member.id)
        transactions = (
            await session.scalars(
                select(AccountTransactionModel)
                .where(AccountTransactionModel.member_id == member.id)
                .order_by(AccountTransactionModel.created_at)
            )
        ).all()
    assert model is not None
    assert model.credit_balance_cached == 10
    assert transactions[-1].experience_delta == 0
    assert await scalar_count(database, OutboxEventModel) == 2
    await database.dispose()


async def test_two_public_drafts_compete_for_one_balance(database_url: str) -> None:
    database = Database(database_url)
    member = await prepare_member(database, telegram_user_id=2100)
    selected = await template_id(database, "resume_review")
    service = TaskService(database.unit_of_work)
    first_id, first_revision = await complete_preview(
        service,
        member=member,
        selected_template_id=selected,
        update_base=21_000,
    )
    second_id, second_revision = await complete_preview(
        service,
        member=member,
        selected_template_id=selected,
        update_base=21_100,
    )
    assert first_id != second_id
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        admin = await session.scalar(
            select(MemberModel).where(MemberModel.role == MemberRole.ADMINISTRATOR.value)
        )
    assert admin is not None
    await EconomyService(database.unit_of_work).apply_one(
        admin_adjustment(
            member_id=member.id,
            credit_delta=-5,
            experience_delta=0,
            idempotency_key="task-competing-drafts:balance-fixture",
            context=AdministrativeContext(admin.id, "Competing drafts balance fixture."),
        )
    )
    results = await asyncio.wait_for(
        asyncio.gather(
            service.publish(
                PublishTaskCommand(21_200, member.telegram_user_id, first_id, first_revision)
            ),
            service.publish(
                PublishTaskCommand(21_201, member.telegram_user_id, second_id, second_revision)
            ),
            return_exceptions=True,
        ),
        timeout=10,
    )
    assert sum(not isinstance(item, BaseException) for item in results) == 1
    assert sum(isinstance(item, BaseException) for item in results) == 1
    assert await scalar_count(database, TaskModel) == 1
    assert await scalar_count(database, OutboxEventModel) == 1
    async with sessions() as session:
        persisted = await session.get(MemberModel, member.id)
        receipts = (
            await session.scalars(
                select(ProcessedTelegramUpdateModel).where(
                    ProcessedTelegramUpdateModel.update_id.in_((21_200, 21_201))
                )
            )
        ).all()
    assert persisted is not None
    assert persisted.credit_balance_cached == 2
    assert len(receipts) == 1
    await database.dispose()


async def test_invalid_deadline_and_insufficient_balance_leave_no_publish_effects(
    database_url: str,
) -> None:
    database = Database(database_url)
    member = await add_member(database, telegram_user_id=2200)
    admin = await add_member(database, telegram_user_id=3200, role=MemberRole.ADMINISTRATOR)
    await prepare_config(database, admin)
    selected = await template_id(database, "repository_first_impression")
    service = TaskService(database.unit_of_work)
    draft = await service.start(
        update_id=22_000,
        actor_telegram_user_id=member.telegram_user_id,
        template_id=selected,
    )
    assert draft is not None
    input_draft = await service.advance(
        AdvanceDraftCommand(
            22_001,
            member.telegram_user_id,
            draft.id,
            TaskDraftStep.INPUT,
            draft.revision,
            {
                "context": "Need a detailed and practical review.",
                "materials": "https://example.com/item",
                "constraints": "Do not publish private information.",
            },
        )
    )
    with pytest.raises(TaskError):
        await service.advance(
            AdvanceDraftCommand(
                22_002,
                member.telegram_user_id,
                draft.id,
                TaskDraftStep.DEADLINE,
                input_draft.revision,
                datetime.datetime.now(datetime.UTC),
            )
        )
    assert await scalar_count(database, TaskModel) == 0

    full_id, revision = await complete_preview(
        service,
        member=member,
        selected_template_id=selected,
        update_base=22_100,
    )
    baseline_audit = await scalar_count(database, AuditEventModel)
    baseline_receipts = await scalar_count(database, ProcessedTelegramUpdateModel)
    with pytest.raises(InsufficientBalanceError):
        await service.publish(
            PublishTaskCommand(22_200, member.telegram_user_id, full_id, revision)
        )
    assert await scalar_count(database, TaskModel) == 0
    assert await scalar_count(database, OutboxEventModel) == 0
    assert await scalar_count(database, AuditEventModel) == baseline_audit
    assert await scalar_count(database, ProcessedTelegramUpdateModel) == baseline_receipts
    await database.dispose()


async def test_draft_replay_stale_revision_and_foreign_access(database_url: str) -> None:
    database = Database(database_url)
    owner = await prepare_member(database, telegram_user_id=2250)
    stranger = await add_member(database, telegram_user_id=2251)
    selected = await template_id(database, "repository_first_impression")
    restricted = await template_id(database, "linkedin_audit")
    service = TaskService(database.unit_of_work)
    with pytest.raises(PermissionError):
        await service.start(
            update_id=22_499,
            actor_telegram_user_id=owner.telegram_user_id,
            template_id=restricted,
        )
    draft = await service.start(
        update_id=22_500,
        actor_telegram_user_id=owner.telegram_user_id,
        template_id=selected,
    )
    assert draft is not None
    command_value = {
        "context": "Need a detailed and practical review.",
        "materials": "https://example.com/item",
        "constraints": "Do not publish private information.",
    }
    command = AdvanceDraftCommand(
        22_501,
        owner.telegram_user_id,
        draft.id,
        TaskDraftStep.INPUT,
        draft.revision,
        command_value,
    )
    advanced = await service.advance(command)
    replay = await service.advance(command)
    assert replay == advanced
    receipts_before = await scalar_count(database, ProcessedTelegramUpdateModel)
    with pytest.raises(StaleTaskDraftError):
        await service.advance(
            AdvanceDraftCommand(
                22_502,
                owner.telegram_user_id,
                draft.id,
                TaskDraftStep.INPUT,
                draft.revision,
                command_value,
            )
        )
    with pytest.raises(PermissionError):
        await service.cancel_draft(
            update_id=22_503,
            actor_telegram_user_id=stranger.telegram_user_id,
            draft_id=draft.id,
        )
    assert await scalar_count(database, ProcessedTelegramUpdateModel) == receipts_before
    persisted = await service.current(actor_telegram_user_id=owner.telegram_user_id)
    assert persisted == advanced
    await database.dispose()


async def test_publish_business_retry_concurrent_cancel_and_private_listing(  # noqa: PLR0915 - one transaction-identity matrix.
    database_url: str,
) -> None:
    database = Database(database_url)
    owner = await prepare_member(database, telegram_user_id=2260)
    stranger = await add_member(database, telegram_user_id=2261)
    selected = await template_id(database, "repository_first_impression")
    service = TaskService(database.unit_of_work)
    draft_id, revision = await complete_preview(
        service,
        member=owner,
        selected_template_id=selected,
        update_base=22_600,
    )
    task = await service.publish(
        PublishTaskCommand(22_610, owner.telegram_user_id, draft_id, revision)
    )
    ledger_after_publish = await scalar_count(database, AccountTransactionModel)
    business_retry = await service.publish(
        PublishTaskCommand(22_611, owner.telegram_user_id, draft_id, revision)
    )
    assert business_retry.id == task.id
    assert await scalar_count(database, AccountTransactionModel) == ledger_after_publish
    receipts_after_retry = await scalar_count(database, ProcessedTelegramUpdateModel)
    with pytest.raises(StaleTaskDraftError):
        await service.publish(
            PublishTaskCommand(22_615, owner.telegram_user_id, draft_id, revision + 1)
        )
    assert await scalar_count(database, ProcessedTelegramUpdateModel) == receipts_after_retry
    assert await service.list_owned(actor_telegram_user_id=stranger.telegram_user_id) == ()
    with pytest.raises(PermissionError):
        await service.cancel(
            update_id=22_612,
            actor_telegram_user_id=stranger.telegram_user_id,
            task_id=task.id,
        )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        stranger_model = await session.get(MemberModel, stranger.id)
        assert stranger_model is not None
        stranger_model.status = MemberStatus.PAUSED.value
    with pytest.raises(PermissionError):
        await service.list_owned(actor_telegram_user_id=stranger.telegram_user_id)
    receipts_before_cancel = await scalar_count(database, ProcessedTelegramUpdateModel)
    outcomes = await asyncio.wait_for(
        asyncio.gather(
            service.cancel(
                update_id=22_613,
                actor_telegram_user_id=owner.telegram_user_id,
                task_id=task.id,
            ),
            service.cancel(
                update_id=22_614,
                actor_telegram_user_id=owner.telegram_user_id,
                task_id=task.id,
            ),
            return_exceptions=True,
        ),
        timeout=10,
    )
    assert sum(not isinstance(item, BaseException) for item in outcomes) == 1
    assert sum(isinstance(item, TaskError) for item in outcomes) == 1
    assert await scalar_count(database, ProcessedTelegramUpdateModel) == (
        receipts_before_cancel + 1
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        refunds = (
            await session.scalars(
                select(AccountTransactionModel).where(
                    AccountTransactionModel.transaction_type == "task_reward_refunded"
                )
            )
        ).all()
        persisted_owner = await session.get(MemberModel, owner.id)
    assert len(refunds) == 1
    assert refunds[0].experience_delta == 0
    assert persisted_owner is not None
    assert persisted_owner.credit_balance_cached == 10
    audit_after_cancel = await scalar_count(database, AuditEventModel)
    outbox_after_cancel = await scalar_count(database, OutboxEventModel)
    receipts_after_cancel = await scalar_count(database, ProcessedTelegramUpdateModel)
    with pytest.raises(TaskError, match="already cancelled"):
        await service.cancel(
            update_id=22_616,
            actor_telegram_user_id=owner.telegram_user_id,
            task_id=task.id,
        )
    assert await scalar_count(database, AuditEventModel) == audit_after_cancel
    assert await scalar_count(database, OutboxEventModel) == outbox_after_cancel
    assert await scalar_count(database, ProcessedTelegramUpdateModel) == receipts_after_cancel

    second_draft_id, second_revision = await complete_preview(
        service,
        member=owner,
        selected_template_id=selected,
        update_base=22_620,
    )
    second_task = await service.publish(
        PublishTaskCommand(
            22_630,
            owner.telegram_user_id,
            second_draft_id,
            second_revision,
        )
    )
    first_page = await service.list_owned(
        actor_telegram_user_id=owner.telegram_user_id,
        limit=1,
    )
    assert [item.id for item in first_page] == [second_task.id]
    second_page = await service.list_owned(
        actor_telegram_user_id=owner.telegram_user_id,
        limit=1,
        cursor=(first_page[0].created_at, first_page[0].id),
    )
    assert [item.id for item in second_page] == [task.id]
    cancelled_page = await service.list_owned(
        actor_telegram_user_id=owner.telegram_user_id,
        status=TaskStatus.CANCELLED,
    )
    assert [item.id for item in cancelled_page] == [task.id]
    effects_before_paused_cancel = (
        await scalar_count(database, AccountTransactionModel),
        await scalar_count(database, AuditEventModel),
        await scalar_count(database, OutboxEventModel),
        await scalar_count(database, ProcessedTelegramUpdateModel),
    )
    async with sessions.begin() as session:
        owner_model = await session.get(MemberModel, owner.id)
        assert owner_model is not None
        owner_model.status = MemberStatus.PAUSED.value
    with pytest.raises(PermissionError):
        await service.cancel(
            update_id=22_631,
            actor_telegram_user_id=owner.telegram_user_id,
            task_id=second_task.id,
        )
    assert (
        await scalar_count(database, AccountTransactionModel),
        await scalar_count(database, AuditEventModel),
        await scalar_count(database, OutboxEventModel),
        await scalar_count(database, ProcessedTelegramUpdateModel),
    ) == effects_before_paused_cancel
    await database.dispose()


async def test_publish_fault_injection_rolls_back_every_staged_slice(
    database_url: str,
) -> None:
    database = Database(database_url)
    member = await prepare_member(database, telegram_user_id=2270)
    selected = await template_id(database, "repository_first_impression")

    def fail() -> None:
        message = "intentional task publication fault"
        raise RuntimeError(message)

    factories = (
        lambda: database.unit_of_work(after_ledger_flushed=fail),
        lambda: database.unit_of_work(after_task_inserted=fail),
        lambda: database.unit_of_work(after_task_outbox_staged=fail),
        lambda: database.unit_of_work(after_task_receipt_staged=fail),
    )
    normal = TaskService(database.unit_of_work)
    draft_id, revision = await complete_preview(
        normal,
        member=member,
        selected_template_id=selected,
        update_base=22_700,
    )
    counts_before = (
        await scalar_count(database, TaskModel),
        await scalar_count(database, AccountTransactionModel),
        await scalar_count(database, AuditEventModel),
        await scalar_count(database, OutboxEventModel),
        await scalar_count(database, ProcessedTelegramUpdateModel),
    )
    command_value = PublishTaskCommand(
        22_710,
        member.telegram_user_id,
        draft_id,
        revision,
    )
    for factory in factories:
        with pytest.raises(RuntimeError, match="intentional"):
            await TaskService(factory).publish(command_value)
        assert (
            await scalar_count(database, TaskModel),
            await scalar_count(database, AccountTransactionModel),
            await scalar_count(database, AuditEventModel),
            await scalar_count(database, OutboxEventModel),
            await scalar_count(database, ProcessedTelegramUpdateModel),
        ) == counts_before
    await normal.publish(command_value)
    assert await scalar_count(database, TaskModel) == 1
    await database.dispose()


async def test_catalog_mutation_and_publish_have_deterministic_gate_order(
    database_url: str,
) -> None:
    database = Database(database_url)
    member = await prepare_member(database, telegram_user_id=2280)
    selected = await template_id(database, "repository_first_impression")
    service = TaskService(database.unit_of_work)
    blocked_draft, blocked_revision = await complete_preview(
        service,
        member=member,
        selected_template_id=selected,
        update_base=22_800,
    )

    async with database.unit_of_work() as mutation:
        await mutation.acquire_catalog_mutation_gate()
        await mutation.set_catalog_template_active(
            code="repository_first_impression", enabled=False
        )
        blocked_publish = asyncio.create_task(
            service.publish(
                PublishTaskCommand(
                    22_810,
                    member.telegram_user_id,
                    blocked_draft,
                    blocked_revision,
                )
            )
        )
        await mutation.commit()
    with pytest.raises(PermissionError):
        await asyncio.wait_for(blocked_publish, timeout=10)
    assert await scalar_count(database, TaskModel) == 0

    async with database.unit_of_work() as mutation:
        await mutation.acquire_catalog_mutation_gate()
        await mutation.set_catalog_template_active(code="repository_first_impression", enabled=True)
        await mutation.commit()
    published_draft, published_revision = await complete_preview(
        service,
        member=member,
        selected_template_id=selected,
        update_base=22_820,
    )
    task_inserted = asyncio.Event()
    hooked_service = TaskService(
        lambda: database.unit_of_work(after_task_inserted=task_inserted.set)
    )
    publish_first = asyncio.create_task(
        hooked_service.publish(
            PublishTaskCommand(
                22_830,
                member.telegram_user_id,
                published_draft,
                published_revision,
            )
        )
    )
    await asyncio.wait_for(task_inserted.wait(), timeout=10)

    async def deactivate_after_publish() -> None:
        async with database.unit_of_work() as mutation:
            await mutation.acquire_catalog_mutation_gate()
            await mutation.set_catalog_template_active(
                code="repository_first_impression", enabled=False
            )
            await mutation.commit()

    published, _ = await asyncio.wait_for(
        asyncio.gather(publish_first, deactivate_after_publish()),
        timeout=10,
    )
    assert isinstance(published, PublishedTask)
    assert published.id is not None
    assert published.title == "Первое впечатление от репозитория"
    assert await scalar_count(database, TaskModel) == 1
    await database.dispose()


async def test_config_activation_and_publish_use_one_resolved_version(
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=3290,
        role=MemberRole.ADMINISTRATOR,
    )
    member = await add_member(database, telegram_user_id=2290)
    await prepare_config(database, admin)
    economy = EconomyService(database.unit_of_work)
    await economy.apply_one(starting_grant(member.id))
    await economy.apply_one(
        admin_adjustment(
            member_id=member.id,
            credit_delta=0,
            experience_delta=7,
            idempotency_key="task-config-race:experience",
            context=AdministrativeContext(admin.id, "Task config race fixture."),
        )
    )
    base = load_product_config_candidate(CONFIG_PATH)
    level_two = replace(base.levels[1], experience_required=5)
    candidate = replace(
        base,
        config_version=2,
        levels=(base.levels[0], level_two, *base.levels[2:]),
    )
    configs = ProductConfigService(database.unit_of_work)
    await configs.ingest(candidate=candidate, actor_member_id=admin.id)
    await configs.activate(
        ProductConfigActivationCommand(uuid4(), 2, admin.id, "Prepare level two draft.")
    )
    restricted = await template_id(database, "linkedin_audit")
    service = TaskService(database.unit_of_work)
    draft_id, revision = await complete_preview(
        service,
        member=member,
        selected_template_id=restricted,
        update_base=22_900,
    )
    await configs.activate(
        ProductConfigActivationCommand(uuid4(), 1, admin.id, "Restore version one.")
    )
    activation, publication = await asyncio.wait_for(
        asyncio.gather(
            configs.activate(
                ProductConfigActivationCommand(uuid4(), 2, admin.id, "Concurrent task publication.")
            ),
            service.publish(
                PublishTaskCommand(22_910, member.telegram_user_id, draft_id, revision)
            ),
            return_exceptions=True,
        ),
        timeout=10,
    )
    assert not isinstance(activation, BaseException)
    if isinstance(publication, BaseException):
        assert isinstance(publication, PermissionError)
        publication = await service.publish(
            PublishTaskCommand(22_910, member.telegram_user_id, draft_id, revision)
        )
    assert isinstance(publication, PublishedTask)
    active = await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(candidate_path=None, actor_member_id=None, activation_command_id=None)
    assert active.version == 2
    assert publication.minimum_level == 2
    assert await scalar_count(database, TaskModel) == 1
    await database.dispose()


async def test_task_snapshot_db_guard_and_migration_cycle(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=3300, role=MemberRole.ADMINISTRATOR)
    member = await add_member(database, telegram_user_id=2300)
    await prepare_config(database, admin)
    await EconomyService(database.unit_of_work).apply_one(
        admin_adjustment(
            member_id=member.id,
            credit_delta=10,
            experience_delta=0,
            idempotency_key="task-migration-cycle:balance-fixture",
            context=AdministrativeContext(admin.id, "Task migration cycle balance fixture."),
        )
    )
    selected = await template_id(database, "repository_first_impression")
    service = TaskService(database.unit_of_work)
    draft_id, revision = await complete_preview(
        service,
        member=member,
        selected_template_id=selected,
        update_base=23_000,
    )
    task = await service.publish(
        PublishTaskCommand(23_010, member.telegram_user_id, draft_id, revision)
    )
    with pytest.raises(DBAPIError):
        async with database.engine.begin() as connection:
            await connection.execute(
                text("UPDATE tasks SET title = 'changed' WHERE id = :task_id"),
                {"task_id": task.id},
            )
    with pytest.raises(DBAPIError):
        async with database.engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM tasks WHERE id = :task_id"), {"task_id": task.id}
            )
    with pytest.raises(DBAPIError):
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO tasks (
                        id, origin, template_id, template_version, creator_id,
                        author_display_name, category_id, title, description,
                        completion_criteria, materials_json, input_payload_json,
                        credit_reward_per_performer, performer_slots,
                        reserved_credit_total, estimated_minutes, minimum_level,
                        format, city, deadline_at, status, safety_snapshot_json,
                        publish_command_id, published_at, cancelled_at,
                        created_at, updated_at
                    )
                    SELECT
                        gen_random_uuid(), origin, template_id, template_version,
                        creator_id, author_display_name, category_id, title,
                        description, completion_criteria, materials_json,
                        input_payload_json, credit_reward_per_performer,
                        performer_slots, 0, estimated_minutes, minimum_level,
                        format, city, deadline_at, status, safety_snapshot_json,
                        gen_random_uuid(), published_at, cancelled_at,
                        created_at, updated_at
                    FROM tasks WHERE id = :task_id
                    """
                ),
                {"task_id": task.id},
            )
    with pytest.raises(DBAPIError):
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO outbox_events (
                        id, event_type, aggregate_type, aggregate_id,
                        payload_json, business_key, created_at, published_at
                    )
                    SELECT
                        gen_random_uuid(), event_type, aggregate_type,
                        aggregate_id, payload_json, business_key,
                        created_at, published_at
                    FROM outbox_events WHERE aggregate_id = :task_id
                    """
                ),
                {"task_id": task.id},
            )
    await database.dispose()

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    configuration = Config("alembic.ini")
    try:
        await asyncio.to_thread(command.downgrade, configuration, "0005")
        await asyncio.to_thread(command.upgrade, configuration, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    restarted = Database(database_url)
    assert await scalar_count(restarted, TaskCreationDraftModel) == 0
    await restarted.dispose()
