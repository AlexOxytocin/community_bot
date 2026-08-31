"""PostgreSQL tests for the complete MVP moderation slice."""

# ruff: noqa: FBT003, PT018

from __future__ import annotations

import asyncio
import datetime
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.moderation import (
    IssueSanctionCommand,
    ModerateKarmaCommand,
    ModerationService,
    OpenFraudCaseCommand,
    RequestAppealCommand,
    ResolveCaseCommand,
    ReviewAlertCommand,
    RevokeSanctionCommand,
)
from community_bot.domain.economy import InsufficientBalanceError
from community_bot.domain.members import MemberRole, MemberStatus
from community_bot.domain.moderation import (
    AlertOutcome,
    ModerationError,
    ResolutionCode,
    RestrictedAction,
    SanctionType,
)
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AssignmentDisputeModel,
    AssignmentModel,
    AuditEventModel,
    DisputeResolutionModel,
    InteractionAlertModel,
    KarmaVoteModel,
    MemberModel,
    MemberSanctionModel,
    ModerationCaseModel,
    ModerationRiskSignalModel,
    ProcessedTelegramUpdateModel,
    ReliabilityEventModel,
    SanctionEventModel,
    TaskCategoryModel,
    TaskModel,
    TaskTemplateModel,
)
from tests.integration.test_reputation import add_member, add_paid_interaction, prepare_config

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
PROJECT_ROOT = Path(__file__).resolve().parents[2]


async def test_paid_fraud_reversal_is_admin_only_atomic_and_replayable(
    database_url: str,
) -> None:
    """A paid assignment reaches fraud through the explicit case-open command."""
    database = Database(database_url)
    admin = await add_member(
        database,
        13_001,
        role=MemberRole.ADMINISTRATOR,
        permissions=["karma_review", "member_read", "interaction_review"],
    )
    await prepare_config(database, admin.id)
    creator = await add_member(database, 13_002)
    performer = await add_member(database, 13_003)
    assignment_id = await add_paid_interaction(database, creator, performer)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        performer_row = await session.get(MemberModel, performer.id)
        assignment = await session.get(AssignmentModel, assignment_id)
        assert performer_row is not None and assignment is not None
        performer_row.credit_balance_cached = 2
        performer_row.experience_total_cached = 2
        assignment.slot_ever_paid = True
    service = ModerationService(database.unit_of_work)
    open_command = OpenFraudCaseCommand(
        130_001, admin.telegram_user_id, assignment_id, uuid4(), "Confirmed payout fraud."
    )
    case = await service.open_fraud_case(open_command)
    replay = await service.open_fraud_case(open_command)
    assert replay.id == case.id
    with pytest.raises(ModerationError, match="conflicts with stored payload"):
        await service.open_fraud_case(
            OpenFraudCaseCommand(
                open_command.update_id + 1,
                admin.telegram_user_id,
                assignment_id,
                open_command.command_id,
                "A conflicting reason under the same command identity.",
            )
        )
    resolved = await service.resolve(
        ResolveCaseCommand(
            130_002,
            admin.telegram_user_id,
            case.id,
            uuid4(),
            case.revision,
            ResolutionCode.FRAUD,
            "Reverse the fraudulent payout.",
        )
    )
    assert resolved.current_code is ResolutionCode.FRAUD
    async with sessions() as session:
        assignment = await session.get(AssignmentModel, assignment_id)
        task = None if assignment is None else await session.get(TaskModel, assignment.task_id)
        performer_row = await session.get(MemberModel, performer.id)
        reversals = (
            await session.scalars(
                select(AccountTransactionModel).where(
                    AccountTransactionModel.assignment_id == assignment_id,
                    AccountTransactionModel.transaction_type == "fraud_reversal",
                )
            )
        ).all()
        assert assignment is not None and assignment.status == "rejected"
        assert task is not None and task.status == "expired"
        assert assignment.slot_ever_paid is True
        assert performer_row is not None and performer_row.credit_balance_cached == 0
        assert performer_row.experience_total_cached == 0
        assert len(reversals) == 1
    await database.dispose()


async def test_dispute_resolution_matrix_writes_ledger_reliability_and_audit(
    database_url: str,
) -> None:
    """Full, partial, and refund outcomes share one deterministic transaction."""
    database = Database(database_url)
    admin = await add_member(database, 13_101, role=MemberRole.ADMINISTRATOR)
    await prepare_config(database, admin.id)
    moderator = await add_member(database, 13_102, role=MemberRole.MODERATOR)
    creator = await add_member(database, 13_103)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    service = ModerationService(database.unit_of_work)
    expectations = (
        (ResolutionCode.FULL_PAYMENT, "approved", 2, "completed"),
        (ResolutionCode.PARTIAL_PAYMENT, "partially_approved", 1, "completed"),
        (ResolutionCode.FULL_REFUND, "rejected", 0, "expired"),
        (ResolutionCode.CANCEL_WITHOUT_FAULT, "cancelled", 0, "expired"),
    )
    for index, (code, expected_status, expected_credit, expected_task_status) in enumerate(
        expectations,
        start=1,
    ):
        performer = await add_member(database, 13_110 + index)
        case = await _open_dispute_fixture(database, creator, performer)
        result = await service.resolve(
            ResolveCaseCommand(
                131_000 + index,
                moderator.telegram_user_id,
                case.id,
                uuid4(),
                0,
                code,
                f"Resolution {code.value}.",
            )
        )
        assert result.current_code is code
        async with sessions() as session:
            assignment = await session.get(AssignmentModel, case.assignment_id)
            task = None if assignment is None else await session.get(TaskModel, assignment.task_id)
            performer_row = await session.get(MemberModel, performer.id)
            roots = int(
                await session.scalar(
                    select(func.count(ReliabilityEventModel.id)).where(
                        ReliabilityEventModel.assignment_id == case.assignment_id,
                        ReliabilityEventModel.event_type != "accepted",
                    )
                )
                or 0
            )
            assert assignment is not None and assignment.status == expected_status
            assert task is not None and task.status == expected_task_status
            assert (
                performer_row is not None and performer_row.credit_balance_cached == expected_credit
            )
            assert roots == 1
            if code is ResolutionCode.CANCEL_WITHOUT_FAULT:
                assert assignment.slot_ever_paid is False
                replacement = await add_member(database, 13_120 + index)
                async with sessions.begin() as write_session:
                    write_session.add(
                        AssignmentModel(
                            id=uuid4(),
                            task_id=assignment.task_id,
                            performer_id=replacement.id,
                            slot_number=assignment.slot_number,
                            status="accepted",
                        )
                    )
    async with sessions() as session:
        assert int(await session.scalar(select(func.count(AuditEventModel.id))) or 0) >= 3
        assert (
            int(
                await session.scalar(select(func.count(ProcessedTelegramUpdateModel.update_id)))
                or 0
            )
            == 4
        )
    await database.dispose()


async def test_migration_repairs_stale_moderated_task_aggregate(database_url: str) -> None:
    """Migration 0030 repairs already resolved cases without runtime replay."""
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "downgrade", "0029"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
    )
    database = Database(database_url)
    creator = await add_member(database, 13_181)
    performer = await add_member(database, 13_182)
    case = await _open_dispute_fixture(
        database,
        creator,
        performer,
        legacy_assignment_schema=True,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        stored_case = await session.get(ModerationCaseModel, case.id)
        task_id = await session.scalar(
            text("SELECT task_id FROM assignments WHERE id = :assignment_id"),
            {"assignment_id": case.assignment_id},
        )
        assert task_id is not None and stored_case is not None
        await session.execute(
            text(
                """
                UPDATE assignments
                SET status = 'rejected',
                    terminal_outcome = 'fraud',
                    reviewed_at = :reviewed_at
                WHERE id = :assignment_id
                """
            ),
            {
                "assignment_id": case.assignment_id,
                "reviewed_at": datetime.datetime.now(datetime.UTC),
            },
        )
        stored_case.status = "resolved"
        stored_case.resolved_at = datetime.datetime.now(datetime.UTC)
    await database.dispose()

    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
    )
    repaired = Database(database_url)
    repaired_sessions = async_sessionmaker(repaired.engine, expire_on_commit=False)
    async with repaired_sessions() as session:
        task = await session.get(TaskModel, task_id)
        assert task is not None and task.status == "expired"
    await repaired.dispose()


async def test_suspension_expires_on_read_without_worker_and_preserves_history(
    database_url: str,
) -> None:
    """Effective status is correct even when the delivery worker never ran."""
    database = Database(database_url)
    admin = await add_member(database, 13_201, role=MemberRole.ADMINISTRATOR)
    target = await add_member(database, 13_202)
    service = ModerationService(database.unit_of_work)
    sanction = await service.issue_sanction(
        IssueSanctionCommand(
            132_001,
            admin.telegram_user_id,
            target.id,
            uuid4(),
            SanctionType.SUSPENSION,
            "Temporary investigation hold.",
            ends_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
        )
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        model = await session.get(MemberSanctionModel, sanction.id)
        assert model is not None
        model.ends_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1)
    async with database.unit_of_work() as uow:
        effective = await uow.get_member(target.id)
        await uow.commit()
    assert effective is not None and effective.status is MemberStatus.ACTIVE
    async with sessions() as session:
        model = await session.get(MemberSanctionModel, sanction.id)
        member = await session.get(MemberModel, target.id)
        events = (
            await session.scalars(
                select(SanctionEventModel).where(SanctionEventModel.sanction_id == sanction.id)
            )
        ).all()
        assert model is not None and model.state == "expired"
        assert member is not None and member.status == "active"
        assert [item.event_type for item in events] == ["issued", "expired"]
    await database.dispose()


async def test_karma_signal_and_exact_revision_exclusion_never_auto_sanction(
    database_url: str,
) -> None:
    """A negative burst creates one signal and an administrator can exclude/restore."""
    database = Database(database_url)
    admin = await add_member(
        database, 13_301, role=MemberRole.ADMINISTRATOR, permissions=["karma_review"]
    )
    target = await add_member(database, 13_302)
    raters = [await add_member(database, 13_310 + index) for index in range(3)]
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    vote_id = uuid4()
    async with sessions.begin() as session:
        for index, rater in enumerate(raters):
            session.add(
                KarmaVoteModel(
                    id=vote_id if index == 2 else uuid4(),
                    rater_id=rater.id,
                    target_id=target.id,
                    value=-1,
                    comment="Repeated negative pattern",
                    revision=1,
                    last_command_id=uuid4(),
                )
            )
    async with database.unit_of_work() as uow:
        await uow.generate_karma_signals(vote_id)
        await uow.commit()
    service = ModerationService(database.unit_of_work)
    await service.moderate_karma(
        ModerateKarmaCommand(
            133_001, admin.telegram_user_id, vote_id, 1, uuid4(), True, "Review burst."
        )
    )
    await service.moderate_karma(
        ModerateKarmaCommand(
            133_002, admin.telegram_user_id, vote_id, 1, uuid4(), False, "Vote is valid."
        )
    )
    async with sessions() as session:
        assert int(await session.scalar(select(func.count(ModerationRiskSignalModel.id))) or 0) == 2
        assert int(await session.scalar(select(func.count(MemberSanctionModel.id))) or 0) == 0
    await database.dispose()


async def test_fourth_paid_interaction_opens_one_non_blocking_alert(
    database_url: str,
) -> None:
    """The configured 3→4 crossing creates one private review episode."""
    database = Database(database_url)
    admin = await add_member(database, 13_401, role=MemberRole.ADMINISTRATOR)
    await prepare_config(database, admin.id)
    creator = await add_member(database, 13_402)
    performer = await add_member(database, 13_403)
    assignment_ids = [await add_paid_interaction(database, creator, performer) for _ in range(4)]
    async with database.unit_of_work() as uow:
        await uow.recompute_interaction_alert(assignment_ids[-1])
        await uow.commit()
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        alerts = (await session.scalars(select(InteractionAlertModel))).all()
        assert len(alerts) == 1
        assert alerts[0].interaction_count == 4
        assert alerts[0].state == "open"
        creator_row = await session.get(MemberModel, creator.id)
        performer_row = await session.get(MemberModel, performer.id)
        assert creator_row is not None and creator_row.status == "active"
        assert performer_row is not None and performer_row.status == "active"
    await database.dispose()


async def test_appeal_reverses_previous_outcome_and_keeps_paid_slot_occupied(
    database_url: str,
) -> None:
    """One appeal changes money and reliability without reopening a paid slot."""
    database = Database(database_url)
    admin = await add_member(database, 13_501, role=MemberRole.ADMINISTRATOR)
    second_admin = await add_member(database, 13_502, role=MemberRole.ADMINISTRATOR)
    moderator = await add_member(database, 13_503, role=MemberRole.MODERATOR)
    await prepare_config(database, admin.id)
    creator = await add_member(database, 13_504)
    performer = await add_member(database, 13_505)
    case = await _open_dispute_fixture(database, creator, performer)
    service = ModerationService(database.unit_of_work)
    await service.resolve(
        ResolveCaseCommand(
            135_001,
            moderator.telegram_user_id,
            case.id,
            uuid4(),
            0,
            ResolutionCode.FULL_PAYMENT,
            "Initial full payment.",
        )
    )
    appealed = await service.appeal(
        RequestAppealCommand(
            135_002,
            performer.telegram_user_id,
            case.id,
            uuid4(),
            "The task should be cancelled without fault.",
        )
    )
    assert appealed.status == "appealed"
    with pytest.raises(ModerationError, match="Only a resolved case"):
        await service.appeal(
            RequestAppealCommand(
                135_005,
                creator.telegram_user_id,
                case.id,
                uuid4(),
                "A second appeal must not be accepted.",
            )
        )
    with pytest.raises(ModerationError, match="already has an active"):
        await service.open_fraud_case(
            OpenFraudCaseCommand(
                135_004,
                admin.telegram_user_id,
                case.assignment_id,
                uuid4(),
                "A second active case must be rejected.",
            )
        )
    final = await service.resolve(
        ResolveCaseCommand(
            135_003,
            second_admin.telegram_user_id,
            case.id,
            uuid4(),
            appealed.revision,
            ResolutionCode.CANCEL_WITHOUT_FAULT,
            "Appeal accepted after evidence review.",
        )
    )
    assert final.current_code is ResolutionCode.CANCEL_WITHOUT_FAULT
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        assignment = await session.get(AssignmentModel, case.assignment_id)
        performer_row = await session.get(MemberModel, performer.id)
        creator_row = await session.get(MemberModel, creator.id)
        assert assignment is not None and assignment.status == "cancelled"
        assert assignment.slot_ever_paid is True
        assert performer_row is not None and performer_row.credit_balance_cached == 0
        assert creator_row is not None and creator_row.credit_balance_cached == 2
        assert (
            int(
                await session.scalar(
                    select(func.count(DisputeResolutionModel.id)).where(
                        DisputeResolutionModel.case_id == case.id
                    )
                )
                or 0
            )
            == 2
        )
    async with sessions.begin() as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                update(DisputeResolutionModel)
                .where(DisputeResolutionModel.case_id == case.id)
                .values(reason="History must stay immutable.")
            )
    await database.dispose()


async def test_insufficient_fraud_reversal_does_not_open_case_or_receipt(
    database_url: str,
) -> None:
    """Fraud opening validates the exact reversal before persisting any effects."""
    database = Database(database_url)
    admin = await add_member(database, 13_551, role=MemberRole.ADMINISTRATOR)
    await prepare_config(database, admin.id)
    creator = await add_member(database, 13_552)
    performer = await add_member(database, 13_553)
    assignment_id = await add_paid_interaction(database, creator, performer)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        performer_row = await session.get(MemberModel, performer.id)
        assignment = await session.get(AssignmentModel, assignment_id)
        assert performer_row is not None and assignment is not None
        performer_row.credit_balance_cached = 0
        performer_row.experience_total_cached = 0
        assignment.slot_ever_paid = True
    service = ModerationService(database.unit_of_work)
    with pytest.raises(InsufficientBalanceError):
        await service.open_fraud_case(
            OpenFraudCaseCommand(
                135_500,
                admin.telegram_user_id,
                assignment_id,
                uuid4(),
                "The payout can no longer be reversed safely.",
            )
        )
    async with sessions() as session:
        assert (
            await session.scalar(
                select(ModerationCaseModel).where(
                    ModerationCaseModel.assignment_id == assignment_id
                )
            )
            is None
        )
        assert await session.get(ProcessedTelegramUpdateModel, 135_500) is None
    await database.dispose()


async def test_resolution_fault_rolls_back_ledger_case_audit_and_receipt(
    database_url: str,
) -> None:
    """A failure after ledger flush leaves the complete moderation UoW unchanged."""
    database = Database(database_url)
    admin = await add_member(database, 13_561, role=MemberRole.ADMINISTRATOR)
    await prepare_config(database, admin.id)
    moderator = await add_member(database, 13_562, role=MemberRole.MODERATOR)
    creator = await add_member(database, 13_563)
    performer = await add_member(database, 13_564)
    case = await _open_dispute_fixture(database, creator, performer)

    def fail_after_ledger() -> None:
        message = "injected moderation fault"
        raise RuntimeError(message)

    service = ModerationService(
        lambda: database.unit_of_work(after_ledger_flushed=fail_after_ledger)
    )
    with pytest.raises(RuntimeError, match="injected moderation fault"):
        await service.resolve(
            ResolveCaseCommand(
                135_600,
                moderator.telegram_user_id,
                case.id,
                uuid4(),
                0,
                ResolutionCode.FULL_PAYMENT,
                "This transaction must roll back.",
            )
        )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        stored_case = await session.get(ModerationCaseModel, case.id)
        assignment = await session.get(AssignmentModel, case.assignment_id)
        performer_row = await session.get(MemberModel, performer.id)
        assert stored_case is not None and stored_case.status == "open"
        assert assignment is not None and assignment.status == "disputed"
        assert performer_row is not None and performer_row.credit_balance_cached == 0
        assert await session.get(ProcessedTelegramUpdateModel, 135_600) is None
        assert (
            int(
                await session.scalar(
                    select(func.count(DisputeResolutionModel.id)).where(
                        DisputeResolutionModel.case_id == case.id
                    )
                )
                or 0
            )
            == 0
        )
    await database.dispose()


async def test_case_party_cannot_resolve_own_dispute(
    database_url: str,
) -> None:
    """Server-side conflict checks reject a staff member who is also a case party."""
    database = Database(database_url)
    admin = await add_member(database, 13_566, role=MemberRole.ADMINISTRATOR)
    await prepare_config(database, admin.id)
    creator = await add_member(database, 13_567, role=MemberRole.MODERATOR)
    performer = await add_member(database, 13_568)
    case = await _open_dispute_fixture(database, creator, performer)
    service = ModerationService(database.unit_of_work)
    with pytest.raises(PermissionError, match="conflict"):
        await service.resolve(
            ResolveCaseCommand(
                135_650,
                creator.telegram_user_id,
                case.id,
                uuid4(),
                0,
                ResolutionCode.FULL_PAYMENT,
                "A case party cannot decide their own case.",
            )
        )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        assert await session.get(ProcessedTelegramUpdateModel, 135_650) is None
        assert (
            int(
                await session.scalar(
                    select(func.count(DisputeResolutionModel.id)).where(
                        DisputeResolutionModel.case_id == case.id
                    )
                )
                or 0
            )
            == 0
        )
    await database.dispose()


async def test_sanction_role_matrix_keeps_ban_admin_only_and_reversible(
    database_url: str,
) -> None:
    """A moderator cannot ban; an administrator can issue and revoke with history."""
    database = Database(database_url)
    moderator = await add_member(database, 13_571, role=MemberRole.MODERATOR)
    admin = await add_member(
        database,
        13_572,
        role=MemberRole.ADMINISTRATOR,
        permissions=["member_blocking"],
    )
    target = await add_member(database, 13_573)
    service = ModerationService(database.unit_of_work)
    with pytest.raises(PermissionError, match="administrator"):
        await service.issue_sanction(
            IssueSanctionCommand(
                135_700,
                moderator.telegram_user_id,
                target.id,
                uuid4(),
                SanctionType.BAN,
                "A moderator must not issue a ban.",
            )
        )
    sanction = await service.issue_sanction(
        IssueSanctionCommand(
            135_701,
            admin.telegram_user_id,
            target.id,
            uuid4(),
            SanctionType.BAN,
            "Administrator-confirmed permanent ban.",
        )
    )
    await service.revoke_sanction(
        RevokeSanctionCommand(
            135_702,
            admin.telegram_user_id,
            sanction.id,
            uuid4(),
            "Administrator revoked the ban.",
        )
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        target_row = await session.get(MemberModel, target.id)
        assert target_row is not None and target_row.status == "active"
        assert (
            int(
                await session.scalar(
                    select(func.count(SanctionEventModel.id)).where(
                        SanctionEventModel.sanction_id == sanction.id
                    )
                )
                or 0
            )
            == 2
        )
        assert await session.get(ProcessedTelegramUpdateModel, 135_700) is None
    await database.dispose()


async def test_concurrent_resolution_has_one_winner_and_no_second_receipt(
    database_url: str,
) -> None:
    """The case gate serializes two moderators without duplicate effects."""
    database = Database(database_url)
    admin = await add_member(database, 13_601, role=MemberRole.ADMINISTRATOR)
    await prepare_config(database, admin.id)
    first = await add_member(database, 13_602, role=MemberRole.MODERATOR)
    second = await add_member(database, 13_603, role=MemberRole.MODERATOR)
    creator = await add_member(database, 13_604)
    performer = await add_member(database, 13_605)
    case = await _open_dispute_fixture(database, creator, performer)
    service = ModerationService(database.unit_of_work)
    results = await asyncio.gather(
        service.resolve(
            ResolveCaseCommand(
                136_001,
                first.telegram_user_id,
                case.id,
                uuid4(),
                0,
                ResolutionCode.FULL_PAYMENT,
                "First moderator decision.",
            )
        ),
        service.resolve(
            ResolveCaseCommand(
                136_002,
                second.telegram_user_id,
                case.id,
                uuid4(),
                0,
                ResolutionCode.FULL_REFUND,
                "Second moderator decision.",
            )
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(item, BaseException) for item in results) == 1
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        assert (
            int(
                await session.scalar(
                    select(func.count(DisputeResolutionModel.id)).where(
                        DisputeResolutionModel.case_id == case.id
                    )
                )
                or 0
            )
            == 1
        )
        assert (
            int(
                await session.scalar(
                    select(func.count(ProcessedTelegramUpdateModel.update_id)).where(
                        ProcessedTelegramUpdateModel.update_id.in_((136_001, 136_002))
                    )
                )
                or 0
            )
            == 1
        )
    await database.dispose()


async def test_restriction_blocks_exact_action_and_revoke_restores_it(
    database_url: str,
) -> None:
    """A bounded restriction affects only its named application action."""
    database = Database(database_url)
    moderator = await add_member(database, 13_701, role=MemberRole.MODERATOR)
    target = await add_member(database, 13_702)
    service = ModerationService(database.unit_of_work)
    sanction = await service.issue_sanction(
        IssueSanctionCommand(
            137_001,
            moderator.telegram_user_id,
            target.id,
            uuid4(),
            SanctionType.RESTRICTION,
            "Temporary acceptance restriction.",
            (RestrictedAction.ACCEPT_TASK,),
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2),
        )
    )
    async with database.unit_of_work() as uow:
        with pytest.raises(PermissionError):
            await uow.ensure_moderation_action_allowed(target.id, RestrictedAction.ACCEPT_TASK)
        await uow.ensure_moderation_action_allowed(target.id, RestrictedAction.CREATE_TASK)
    await service.revoke_sanction(
        RevokeSanctionCommand(
            137_002,
            moderator.telegram_user_id,
            sanction.id,
            uuid4(),
            "Restriction is no longer needed.",
        )
    )
    async with database.unit_of_work() as uow:
        await uow.ensure_moderation_action_allowed(target.id, RestrictedAction.ACCEPT_TASK)
    await database.dispose()


async def test_alert_penalty_is_bounded_and_closes_the_episode(
    database_url: str,
) -> None:
    """A reviewed alert can debit available credits but immutable history resists SQL edits."""
    database = Database(database_url)
    admin = await add_member(
        database,
        13_801,
        role=MemberRole.ADMINISTRATOR,
        permissions=["interaction_review"],
    )
    await prepare_config(database, admin.id)
    creator = await add_member(database, 13_802)
    performer = await add_member(database, 13_803)
    assignment_ids = [await add_paid_interaction(database, creator, performer) for _ in range(4)]
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        creator_row = await session.get(MemberModel, creator.id)
        assert creator_row is not None
        creator_row.credit_balance_cached = 2
    async with database.unit_of_work() as uow:
        await uow.recompute_interaction_alert(assignment_ids[-1])
        await uow.commit()
    async with sessions() as session:
        alert = await session.scalar(select(InteractionAlertModel))
        assert alert is not None
    service = ModerationService(database.unit_of_work)
    await service.review_alert(
        ReviewAlertCommand(
            138_001,
            admin.telegram_user_id,
            alert.id,
            uuid4(),
            AlertOutcome.PENALTY_RECOMMENDED,
            "Participants could not justify the repeated interactions.",
            ((creator.id, 1),),
        )
    )
    async with sessions() as session:
        creator_row = await session.get(MemberModel, creator.id)
        alert = await session.get(InteractionAlertModel, alert.id)
        assert creator_row is not None and creator_row.credit_balance_cached == 1
        assert alert is not None and alert.state == "closed"
    await database.dispose()


async def _open_dispute_fixture(
    database: Database,
    creator: MemberModel,
    performer: MemberModel,
    *,
    test_run_id: UUID | None = None,
    legacy_assignment_schema: bool = False,
) -> ModerationCaseModel:
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        category = await session.scalar(select(TaskCategoryModel).limit(1))
        template = await session.scalar(select(TaskTemplateModel).limit(1))
        assert category is not None and template is not None
        now = datetime.datetime.now(datetime.UTC)
        task = TaskModel(
            id=uuid4(),
            test_run_id=test_run_id,
            origin="member",
            template_id=template.id,
            template_version=template.version,
            creator_id=creator.id,
            author_display_name=creator.display_name,
            category_id=category.id,
            title="Disputed task",
            description="A task with a frozen disputed result.",
            completion_criteria="Moderator selects an outcome.",
            materials_json={},
            input_payload_json={},
            credit_reward_per_performer=2,
            performer_slots=1,
            reserved_credit_total=2,
            estimated_minutes=10,
            minimum_level=1,
            format="online",
            deadline_at=now + datetime.timedelta(days=1),
            status="settling",
            safety_snapshot_json={},
            publish_command_id=uuid4(),
            published_at=now,
        )
        assignment_id = uuid4()
        assignment = AssignmentModel(
            id=assignment_id,
            task_id=task.id,
            performer_id=performer.id,
            slot_number=1,
            status="disputed",
        )
        dispute = AssignmentDisputeModel(
            id=uuid4(),
            assignment_id=assignment_id,
            performer_id=performer.id,
            comment="The rejection is disputed.",
            open_command_id=uuid4(),
        )
        case = ModerationCaseModel(
            id=uuid4(),
            assignment_id=assignment_id,
            dispute_id=dispute.id,
            case_type="dispute",
            status="open",
            opened_by_member_id=performer.id,
            open_command_id=dispute.open_command_id,
            open_payload_hash="0" * 64,
            reason=dispute.comment,
        )
        session.add(task)
        await session.flush()
        if legacy_assignment_schema:
            await session.execute(
                text(
                    """
                    INSERT INTO assignments (
                        id, task_id, performer_id, slot_number, status, slot_ever_paid
                    ) VALUES (
                        :id, :task_id, :performer_id, :slot_number, :status, false
                    )
                    """
                ),
                {
                    "id": assignment_id,
                    "task_id": task.id,
                    "performer_id": performer.id,
                    "slot_number": 1,
                    "status": "disputed",
                },
            )
        else:
            session.add(assignment)
            await session.flush()
        session.add_all(
            (
                dispute,
                case,
                ReliabilityEventModel(
                    assignment_id=assignment_id,
                    event_type="accepted",
                    actor_member_id=performer.id,
                ),
            )
        )
        await session.flush()
        return case
