"""Transport-free regressions for backend workflows formerly proved through Telegram."""

# ruff: noqa: PLR0915, PT018

from __future__ import annotations

import asyncio
import datetime
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.assignments import (
    AcceptAssignmentCommand,
    AssignmentService,
    DecideAssignmentCommand,
    SubmitResultCommand,
)
from community_bot.application.economy import EconomyService
from community_bot.application.identity import ActorContext
from community_bot.application.moderation import ModerationService, ResolveCaseCommand
from community_bot.application.reputation import ReputationError, ReputationService
from community_bot.application.tasks import PublishTaskCommand, TaskService
from community_bot.domain.assignments import AssignmentDecision
from community_bot.domain.economy import starting_grant
from community_bot.domain.members import MemberRole
from community_bot.domain.moderation import ResolutionCode
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AssignmentDisputeModel,
    AssignmentModel,
    AuditEventModel,
    DisputeResolutionModel,
    KarmaVoteHistoryModel,
    KarmaVoteModel,
    MemberModel,
    ModerationCaseModel,
    OutboxEventModel,
    ProcessedTelegramUpdateModel,
    ReliabilityEventModel,
    TaskCancellationResponseModel,
    TaskModel,
    TaskTemplateModel,
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
    add_member,
    complete_preview,
    prepare_config,
)


def actor_context(member: MemberModel) -> ActorContext:
    return ActorContext(member.id, "telegram", datetime.datetime.now(datetime.UTC))


pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_cancellation_replay_remains_application_owned(database_url: str) -> None:
    """Every performer must consent before a multislot cancellation settles once."""
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=91_601, role=MemberRole.ADMINISTRATOR)
    author = await add_member(database, telegram_user_id=91_602)
    first = await add_member(database, telegram_user_id=91_603)
    second = await add_member(database, telegram_user_id=91_604)
    await prepare_config(database, admin)
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
            code=f"core-multislot-{uuid4().hex}",
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
    draft_id, revision = await complete_preview(
        tasks,
        member=author,
        selected_template_id=template_id,
        update_base=916_100,
        performer_slots=2,
    )
    task = await tasks.publish(
        PublishTaskCommand(916_110, author.telegram_user_id, draft_id, revision)
    )
    assignments = AssignmentService(database.unit_of_work)
    await assignments.accept(AcceptAssignmentCommand(916_120, first.telegram_user_id, task.id))
    await assignments.accept(AcceptAssignmentCommand(916_121, second.telegram_user_id, task.id))
    request = await tasks.request_cancellation(
        update_id=916_122,
        actor_telegram_user_id=author.telegram_user_id,
        task_id=task.id,
    )
    assert (
        await tasks.request_cancellation(
            update_id=916_122,
            actor_telegram_user_id=author.telegram_user_id,
            task_id=task.id,
        )
        == request
    )
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
        update_id=916_123,
        actor_telegram_user_id=first.telegram_user_id,
        response_id=responses[first.id],
        accepted=True,
    )
    assert partial.status == "pending"
    assert (
        await tasks.respond_cancellation(
            update_id=916_123,
            actor_telegram_user_id=first.telegram_user_id,
            response_id=responses[first.id],
            accepted=True,
        )
        == partial
    )
    async with sessions() as session:
        before_final = await session.get(TaskModel, task.id)
        active_before_final = await session.scalar(
            select(func.count())
            .select_from(AssignmentModel)
            .where(AssignmentModel.task_id == task.id, AssignmentModel.status == "accepted")
        )
    assert before_final is not None and before_final.status == "closed_for_new_performers"
    assert active_before_final == 1
    final = await tasks.respond_cancellation(
        update_id=916_124,
        actor_telegram_user_id=second.telegram_user_id,
        response_id=responses[second.id],
        accepted=True,
    )
    assert final.status == "cancelled"
    assert (
        await tasks.respond_cancellation(
            update_id=916_124,
            actor_telegram_user_id=second.telegram_user_id,
            response_id=responses[second.id],
            accepted=True,
        )
        == final
    )
    async with sessions() as session:
        cancelled = await session.scalar(
            select(func.count())
            .select_from(AssignmentModel)
            .where(AssignmentModel.task_id == task.id, AssignmentModel.status == "cancelled")
        )
        creator_events = (
            await session.scalars(
                select(ReliabilityEventModel).where(
                    ReliabilityEventModel.event_type == "cancelled_creator",
                    ReliabilityEventModel.assignment_id.in_(
                        select(AssignmentModel.id).where(AssignmentModel.task_id == task.id)
                    ),
                )
            )
        ).all()
    assert cancelled == 2
    assert len(creator_events) == 2
    assert {event.actor_member_id for event in creator_events} == {author.id}
    await database.dispose()


async def test_community_data_survives_the_migration_cycle(database_url: str) -> None:
    """Community provenance and a paid exchange survive 0012→0011→0012 exactly."""
    database = Database(database_url)
    creator = await add_member(database, telegram_user_id=97_001, role=MemberRole.ADMINISTRATOR)
    reviewer = await add_member(database, telegram_user_id=97_002, role=MemberRole.ADMINISTRATOR)
    performer = await add_member(database, telegram_user_id=97_003)
    await prepare_config(database, creator)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        template = await session.scalar(
            select(TaskTemplateModel).where(TaskTemplateModel.code == "repository_first_impression")
        )
        assert template is not None
        now = datetime.datetime.now(datetime.UTC)
        task = TaskModel(
            origin="community",
            template_id=template.id,
            template_version=template.version,
            creator_id=None,
            created_by_admin_id=creator.id,
            reviewer_admin_id=reviewer.id,
            community_approved_by_admin_id=creator.id,
            author_display_name="Сообщество",
            category_id=template.category_id,
            title="Community migration proof",
            description="Preserve a paid community task across the exact migration cycle.",
            completion_criteria="The approved assignment and provenance are restored.",
            materials_json={},
            input_payload_json={"context": "migration proof"},
            credit_reward_per_performer=template.credit_reward,
            performer_slots=1,
            reserved_credit_total=0,
            estimated_minutes=template.estimated_minutes,
            minimum_level=template.minimum_level,
            format="online",
            deadline_at=now + datetime.timedelta(days=1),
            status="published",
            safety_snapshot_json={"public_input_keys": ["context"]},
            publish_command_id=uuid4(),
            published_at=now,
        )
        session.add(task)
        await session.flush()
        task_id = task.id
    assignments = AssignmentService(database.unit_of_work)
    assignment = await assignments.accept(
        AcceptAssignmentCommand(971_100, performer.telegram_user_id, task_id)
    )
    await assignments.submit(
        SubmitResultCommand(
            971_101,
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
    assignment = await assignments.decide(
        DecideAssignmentCommand(
            971_102,
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

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    configuration = Config("alembic.ini")
    try:
        await asyncio.to_thread(command.downgrade, configuration, "0011")
        legacy = Database(database_url)
        async with legacy.engine.connect() as connection:
            backup = await connection.scalar(
                select(TaskModel.safety_snapshot_json).where(TaskModel.id == task_id)
            )
        assert backup is not None
        assert backup["_community_created_by_admin_id"] == str(creator.id)
        assert backup["_community_reviewer_admin_id"] == str(reviewer.id)
        await legacy.dispose()

        await asyncio.to_thread(command.upgrade, configuration, "0012")
        restored = Database(database_url)
        restored_sessions = async_sessionmaker(restored.engine, expire_on_commit=False)
        async with restored.engine.connect() as connection:
            restored_task = (
                await connection.execute(
                    select(
                        TaskModel.created_by_admin_id,
                        TaskModel.reviewer_admin_id,
                        TaskModel.safety_snapshot_json,
                    ).where(TaskModel.id == task_id)
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
        assert restored_assignment is not None and restored_assignment.status == "approved"
        assert restored_transactions == transaction_ids
        await restored.dispose()
    finally:
        await asyncio.to_thread(command.upgrade, configuration, "head")
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


async def test_full_exchange_reconciles_ledger_exactly_once(database_url: str) -> None:
    """A paid exchange reconciles caches, ledger, task, outbox and reputation."""
    database = Database(database_url)
    author, task = await _published_task(database, update_base=98_100)
    performer = await add_member(database, telegram_user_id=98_200)
    await EconomyService(database.unit_of_work).apply_one(starting_grant(performer.id))
    assignments = AssignmentService(database.unit_of_work)
    assignment = await assignments.accept(
        AcceptAssignmentCommand(982_100, performer.telegram_user_id, task.id)
    )
    await assignments.submit(
        SubmitResultCommand(
            982_101,
            performer.telegram_user_id,
            assignment.id,
            uuid4(),
            {
                "summary": "A complete direct backend result.",
                "findings": ["The application flow is transport independent."],
                "evidence": [],
            },
        )
    )
    decision_id = uuid4()
    approved = await assignments.decide(
        DecideAssignmentCommand(
            982_102,
            author.telegram_user_id,
            assignment.id,
            decision_id,
            AssignmentDecision.FULL,
        )
    )
    replayed = await assignments.decide(
        DecideAssignmentCommand(
            982_102,
            author.telegram_user_id,
            assignment.id,
            decision_id,
            AssignmentDecision.FULL,
        )
    )
    assert replayed.id == approved.id
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        author_row = await session.get(MemberModel, author.id)
        performer_row = await session.get(MemberModel, performer.id)
        assignment_row = await session.get(AssignmentModel, assignment.id)
        task_row = await session.get(TaskModel, task.id)
        author_ledger = await session.scalar(
            select(func.coalesce(func.sum(AccountTransactionModel.credit_delta), 0)).where(
                AccountTransactionModel.member_id == author.id
            )
        )
        performer_ledger = await session.scalar(
            select(func.coalesce(func.sum(AccountTransactionModel.credit_delta), 0)).where(
                AccountTransactionModel.member_id == performer.id
            )
        )
        transaction_count = await session.scalar(
            select(func.count(AccountTransactionModel.id)).where(
                AccountTransactionModel.assignment_id == assignment.id
            )
        )
        outbox_count = await session.scalar(
            select(func.count(OutboxEventModel.id)).where(
                OutboxEventModel.aggregate_id == assignment.id
            )
        )
    assert author_row is not None and author_row.credit_balance_cached == author_ledger == 8
    assert (
        performer_row is not None and performer_row.credit_balance_cached == performer_ledger == 12
    )
    assert performer_row.experience_total_cached == 2
    assert assignment_row is not None and assignment_row.status == "approved"
    assert task_row is not None and task_row.status == "completed"
    assert transaction_count == 1
    assert int(outbox_count or 0) >= 1
    reputation = ReputationService(database.unit_of_work)
    leaderboard = await reputation.leaderboard(actor=actor_context(author))
    assert leaderboard.items[0].member_id == performer.id
    async with database.unit_of_work() as unit_of_work:
        assert await unit_of_work.karma_eligible(author.id, performer.id)
        assert await unit_of_work.karma_eligible(performer.id, author.id)
    await database.dispose()


async def test_dispute_resolution_preserves_ledger_and_audit(database_url: str) -> None:
    """A replay-safe partial resolution preserves counts and private dispute text."""
    database = Database(database_url)
    author, task = await _published_task(database, update_base=99_100)
    performer = await add_member(database, telegram_user_id=99_200)
    moderator = await add_member(database, telegram_user_id=99_300, role=MemberRole.MODERATOR)
    await EconomyService(database.unit_of_work).apply_one(starting_grant(performer.id))
    assignments = AssignmentService(database.unit_of_work)
    assignment = await assignments.accept(
        AcceptAssignmentCommand(992_100, performer.telegram_user_id, task.id)
    )
    await assignments.submit(
        SubmitResultCommand(
            992_101,
            performer.telegram_user_id,
            assignment.id,
            uuid4(),
            {
                "summary": "A result requiring independent moderation.",
                "findings": ["One disputed finding"],
                "evidence": [],
            },
        )
    )
    await assignments.decide(
        DecideAssignmentCommand(
            992_102,
            author.telegram_user_id,
            assignment.id,
            uuid4(),
            AssignmentDecision.REJECT,
        )
    )
    private_comment = "Результат соответствует условиям, прошу независимую проверку."
    await assignments.dispute(
        update_id=992_103,
        actor_telegram_user_id=performer.telegram_user_id,
        assignment_id=assignment.id,
        command_id=uuid4(),
        comment=private_comment,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        case = await session.scalar(
            select(ModerationCaseModel).where(ModerationCaseModel.assignment_id == assignment.id)
        )
    assert case is not None
    resolution_id = uuid4()
    moderation = ModerationService(database.unit_of_work)
    resolved = await moderation.resolve(
        ResolveCaseCommand(
            992_104,
            moderator.telegram_user_id,
            case.id,
            resolution_id,
            case.revision,
            ResolutionCode.PARTIAL_PAYMENT,
            "Evidence reviewed.",
        )
    )
    replayed = await moderation.resolve(
        ResolveCaseCommand(
            992_104,
            moderator.telegram_user_id,
            case.id,
            resolution_id,
            case.revision,
            ResolutionCode.PARTIAL_PAYMENT,
            "Evidence reviewed.",
        )
    )
    assert replayed.id == resolved.id
    async with sessions() as session:
        stored = await session.get(AssignmentModel, assignment.id)
        dispute_count = await session.scalar(
            select(func.count(AssignmentDisputeModel.id)).where(
                AssignmentDisputeModel.assignment_id == assignment.id
            )
        )
        resolution_count = await session.scalar(
            select(func.count(DisputeResolutionModel.id)).where(
                DisputeResolutionModel.case_id == case.id
            )
        )
        reliability_count = await session.scalar(
            select(func.count(ReliabilityEventModel.id)).where(
                ReliabilityEventModel.assignment_id == assignment.id
            )
        )
        transaction_count = await session.scalar(
            select(func.count(AccountTransactionModel.id)).where(
                AccountTransactionModel.assignment_id == assignment.id
            )
        )
        payloads = (
            await session.scalars(
                select(OutboxEventModel.payload_json).where(
                    OutboxEventModel.aggregate_id == assignment.id
                )
            )
        ).all()
        audit = (
            await session.scalars(
                select(AuditEventModel).where(
                    AuditEventModel.action == "moderation_case_resolved",
                    AuditEventModel.entity_type == "moderation_case",
                    AuditEventModel.entity_id == str(case.id),
                )
            )
        ).all()
    assert stored is not None and stored.status == "partially_approved"
    assert dispute_count == 1
    assert resolution_count == 1
    assert int(reliability_count or 0) >= 2
    assert transaction_count == 2
    assert len(audit) == 1 and audit[0].actor_member_id == moderator.id
    assert all(private_comment not in str(payload) for payload in payloads)
    await database.dispose()


async def test_raw_karma_access_remains_administrative_and_audited(
    database_url: str,
) -> None:
    """Paid vote replacement is exact and raw access stays administrative."""
    database = Database(database_url)
    rater = await add_reputation_member(database, 100_001)
    await prepare_reputation_config(database, rater.id)
    target = await add_reputation_member(database, 100_002)
    await add_paid_interaction(database, rater, target)
    admin = await add_reputation_member(
        database,
        100_003,
        role=MemberRole.ADMINISTRATOR,
        permissions=["karma_review"],
    )
    outsider = await add_reputation_member(database, 100_004)
    reputation = ReputationService(database.unit_of_work)
    draft = await reputation.begin_vote(
        update_id=1_000_001,
        telegram_user_id=rater.telegram_user_id,
        target_id=target.id,
    )
    draft = await reputation.save_value(
        update_id=1_000_002,
        telegram_user_id=rater.telegram_user_id,
        expected_revision=draft.revision,
        value=1,
    )
    draft = await reputation.save_comment(
        update_id=1_000_003,
        telegram_user_id=rater.telegram_user_id,
        expected_revision=draft.revision,
        comment="Очень полезная и аккуратная помощь.",
    )
    with pytest.raises(ReputationError, match="stale or incomplete"):
        await reputation.confirm_vote(
            update_id=1_000_004,
            telegram_user_id=outsider.telegram_user_id,
            expected_revision=draft.revision,
        )
    await reputation.confirm_vote(
        update_id=1_000_005,
        telegram_user_id=rater.telegram_user_id,
        expected_revision=draft.revision,
    )
    draft = await reputation.begin_vote(
        update_id=1_000_006,
        telegram_user_id=rater.telegram_user_id,
        target_id=target.id,
    )
    draft = await reputation.save_value(
        update_id=1_000_007,
        telegram_user_id=rater.telegram_user_id,
        expected_revision=draft.revision,
        value=-1,
    )
    draft = await reputation.save_comment(
        update_id=1_000_008,
        telegram_user_id=rater.telegram_user_id,
        expected_revision=draft.revision,
        comment="Результат пришлось полностью переделать.",
    )
    await reputation.confirm_vote(
        update_id=1_000_009,
        telegram_user_id=rater.telegram_user_id,
        expected_revision=draft.revision,
    )
    profile = await reputation.profile(
        actor=actor_context(outsider),
        target_id=target.id,
    )
    raw = await reputation.raw_karma(
        update_id=1_000_010,
        telegram_user_id=admin.telegram_user_id,
        target_id=target.id,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        vote_count = await session.scalar(select(func.count(KarmaVoteModel.id)))
        history_count = await session.scalar(select(func.count(KarmaVoteHistoryModel.id)))
        audit_count = await session.scalar(
            select(func.count(AuditEventModel.id)).where(
                AuditEventModel.action == "karma_raw_viewed"
            )
        )
        outsider_receipt = await session.get(ProcessedTelegramUpdateModel, 1_000_004)
    assert (profile.karma.score, profile.karma.count) == (-1, 1)
    assert vote_count == 1
    assert history_count == 2
    assert len(raw) == 1 and [row.revision for row in raw[0].history] == [1, 2]
    assert audit_count == 1
    assert outsider_receipt is None
    await database.dispose()
