"""PostgreSQL tests for the complete MVP reputation slice."""

from __future__ import annotations

import asyncio
import datetime
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from community_bot.application.economy import ProductConfigBootstrapCoordinator
from community_bot.application.identity import ActorContext
from community_bot.application.reputation import ReputationService
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.domain.members import MemberRole, MemberStatus
from community_bot.domain.reputation import ProfileUnavailableError
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AssignmentModel,
    AuditEventModel,
    ConversationStateModel,
    KarmaVoteHistoryModel,
    KarmaVoteModel,
    MemberModel,
    OutboxEventModel,
    ProcessedTelegramUpdateModel,
    ReliabilityEventModel,
    TaskCategoryModel,
    TaskModel,
    TaskTemplateModel,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
PROJECT_ROOT = Path(__file__).parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "product-config.v1.json"


def actor_context(member: MemberModel) -> ActorContext:
    return ActorContext(member.id, "telegram", datetime.datetime.now(datetime.UTC))


async def add_member(  # noqa: PLR0913 - fixture exposes independent member axes.
    database: Database,
    telegram_user_id: int,
    *,
    telegram_username: str | None = None,
    display_name: str | None = None,
    role: MemberRole = MemberRole.MEMBER,
    status: MemberStatus = MemberStatus.ACTIVE,
    permissions: list[str] | None = None,
) -> MemberModel:
    """Insert one member without creating unrelated registration state."""
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        model = MemberModel(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            display_name=display_name or f"Member {telegram_user_id}",
            timezone="UTC",
            role=role.value,
            status=status.value,
            permissions_json=permissions or [],
        )
        session.add(model)
        await session.flush()
        return model


async def prepare_config(database: Database, actor_id: UUID) -> None:
    """Activate the canonical product config required by level-aware views."""
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        actor = await session.get(MemberModel, actor_id)
        assert actor is not None
        original_role = actor.role
        actor.role = MemberRole.ADMINISTRATOR.value
    coordinator = ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    )
    await coordinator.prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=actor_id,
        activation_command_id=uuid4(),
        reason="Initial reputation test configuration.",
    )
    async with sessions.begin() as session:
        actor = await session.get(MemberModel, actor_id)
        assert actor is not None
        actor.role = original_role


async def add_paid_interaction(  # noqa: PLR0913 - fixture exposes the tested outcome axes.
    database: Database,
    creator: MemberModel,
    performer: MemberModel,
    *,
    partial: bool = False,
    origin: str = "member",
    terminal: str | None = None,
) -> UUID:
    """Insert the durable minimum that proves a paid member-origin assignment."""
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        category = await session.scalar(select(TaskCategoryModel).limit(1))
        template = await session.scalar(select(TaskTemplateModel).limit(1))
        assert category is not None
        assert template is not None
        now = datetime.datetime.now(datetime.UTC)
        task = TaskModel(
            id=uuid4(),
            origin=origin,
            template_id=template.id,
            template_version=template.version,
            creator_id=creator.id if origin == "member" else None,
            author_display_name=creator.display_name if origin == "member" else "Community",
            category_id=category.id,
            title="Paid interaction",
            description="A complete paid interaction fixture.",
            completion_criteria="The result is accepted.",
            materials_json={},
            input_payload_json={},
            credit_reward_per_performer=2,
            performer_slots=1,
            reserved_credit_total=2 if origin == "member" else 0,
            estimated_minutes=10,
            minimum_level=1,
            format="online",
            deadline_at=now + datetime.timedelta(days=1),
            status="completed",
            safety_snapshot_json={},
            publish_command_id=uuid4(),
            published_at=now,
        )
        terminal = terminal or ("partially_approved" if partial else "approved")
        assignment_status = {
            "cancelled_performer": "cancelled",
            "cancelled_creator": "cancelled",
            "no_show": "no_show",
        }.get(terminal, terminal)
        assignment = AssignmentModel(
            id=uuid4(),
            task_id=task.id,
            performer_id=performer.id,
            slot_number=1,
            status=assignment_status,
        )
        session.add(task)
        await session.flush()
        session.add(assignment)
        await session.flush()
        effects: list[Any] = [
            ReliabilityEventModel(id=uuid4(), assignment_id=assignment.id, event_type="accepted"),
            ReliabilityEventModel(id=uuid4(), assignment_id=assignment.id, event_type=terminal),
        ]
        if terminal in {"approved", "partially_approved"}:
            is_partial = terminal == "partially_approved"
            effects.append(
                AccountTransactionModel(
                    id=uuid4(),
                    member_id=performer.id,
                    credit_delta=1 if is_partial else 2,
                    experience_delta=1 if is_partial else 2,
                    transaction_type=(
                        "partial_task_reward"
                        if is_partial
                        else "community_task_reward"
                        if origin == "community"
                        else "task_reward_earned"
                    ),
                    idempotency_key=f"paid:{assignment.id}",
                    payload_hash="0" * 64,
                    task_id=task.id,
                    assignment_id=assignment.id,
                )
            )
        session.add_all(effects)
        return assignment.id


async def test_vote_flow_updates_one_row_history_and_anonymous_aggregate(
    database_url: str,
) -> None:
    """A paid pair can resume, confirm, and revise one current vote."""
    database = Database(database_url)
    creator = await add_member(database, 8101)
    await prepare_config(database, creator.id)
    performer = await add_member(database, 8102)
    await add_paid_interaction(database, creator, performer)
    service = ReputationService(database.unit_of_work)

    draft = await service.begin_vote(
        update_id=81_001, telegram_user_id=creator.telegram_user_id, target_id=performer.id
    )
    draft = await service.save_value(
        update_id=81_002,
        telegram_user_id=creator.telegram_user_id,
        expected_revision=draft.revision,
        value=1,
    )
    service = ReputationService(database.unit_of_work)
    draft = await service.save_comment(
        update_id=81_003,
        telegram_user_id=creator.telegram_user_id,
        expected_revision=draft.revision,
        comment="Очень полезная и аккуратная помощь.",
    )
    first = await service.confirm_vote(
        update_id=81_004,
        telegram_user_id=creator.telegram_user_id,
        expected_revision=draft.revision,
    )
    assert (first.aggregate_score, first.aggregate_count) == (1, 1)
    replay = await service.confirm_vote(
        update_id=81_004,
        telegram_user_id=creator.telegram_user_id,
        expected_revision=draft.revision,
    )
    assert replay.replayed

    draft = await service.begin_vote(
        update_id=81_005, telegram_user_id=creator.telegram_user_id, target_id=performer.id
    )
    draft = await service.save_value(
        update_id=81_006,
        telegram_user_id=creator.telegram_user_id,
        expected_revision=draft.revision,
        value=-1,
    )
    draft = await service.save_comment(
        update_id=81_007,
        telegram_user_id=creator.telegram_user_id,
        expected_revision=draft.revision,
        comment="Результат пришлось полностью переделать.",
    )
    second = await service.confirm_vote(
        update_id=81_008,
        telegram_user_id=creator.telegram_user_id,
        expected_revision=draft.revision,
    )
    assert (second.aggregate_score, second.aggregate_count, second.revision) == (-1, 1, 2)

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        assert await session.scalar(select(func.count(KarmaVoteModel.id))) == 1
        assert await session.scalar(select(func.count(KarmaVoteHistoryModel.id))) == 2
    profile = await service.profile(actor=actor_context(creator), target_id=performer.id)
    assert profile.karma.score == -1
    assert not hasattr(profile, "rater_id")
    await database.dispose()


async def test_ineligible_self_and_hidden_profiles_have_no_effects(database_url: str) -> None:
    """Denied votes and forged profile targets do not create observable state."""
    database = Database(database_url)
    actor = await add_member(database, 8201)
    await prepare_config(database, actor.id)
    stranger = await add_member(database, 8202)
    paused = await add_member(database, 8203, status=MemberStatus.PAUSED)
    service = ReputationService(database.unit_of_work)
    for target in (actor.id, stranger.id):
        with pytest.raises(PermissionError):
            await service.begin_vote(
                update_id=82_000 + target.int % 100,
                telegram_user_id=actor.telegram_user_id,
                target_id=target,
            )
    with pytest.raises(ProfileUnavailableError, match="Profile unavailable"):
        await service.profile(actor=actor_context(actor), target_id=paused.id)
    with pytest.raises(ProfileUnavailableError, match="Profile unavailable"):
        await service.profile(actor=actor_context(actor), target_id=uuid4())
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        assert await session.scalar(select(func.count(KarmaVoteModel.id))) == 0
    await database.dispose()


async def test_eligibility_is_bidirectional_and_survives_economy_reversal(
    database_url: str,
) -> None:
    """Full/partial paid work creates a permanent pair fact in both directions."""
    database = Database(database_url)
    first = await add_member(database, 8251)
    second = await add_member(database, 8252)
    assignment_id = await add_paid_interaction(database, second, first, partial=True)
    async with database.unit_of_work() as uow:
        assert await uow.karma_eligible(first.id, second.id)
        assert await uow.karma_eligible(second.id, first.id)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        source = await session.scalar(
            select(AccountTransactionModel).where(
                AccountTransactionModel.assignment_id == assignment_id
            )
        )
        assert source is not None
        session.add(
            AccountTransactionModel(
                id=uuid4(),
                member_id=first.id,
                credit_delta=-source.credit_delta,
                experience_delta=-source.experience_delta,
                transaction_type="fraud_reversal",
                idempotency_key="eligibility-reversal",
                payload_hash="2" * 64,
                reversed_transaction_id=source.id,
                assignment_id=assignment_id,
                task_id=source.task_id,
            )
        )
    async with database.unit_of_work() as uow:
        assert await uow.karma_eligible(first.id, second.id)
    await database.dispose()


async def test_raw_karma_requires_permission_cross_product_and_audits(database_url: str) -> None:
    """Raw rows remain administrative and every successful view is audited."""
    database = Database(database_url)
    target = await add_member(database, 8301, status=MemberStatus.PAUSED)
    active_target = await add_member(database, 8304)
    review_admin = await add_member(
        database,
        8302,
        role=MemberRole.ADMINISTRATOR,
        permissions=["karma_review"],
    )
    both_admin = await add_member(
        database,
        8303,
        role=MemberRole.ADMINISTRATOR,
        permissions=["karma_review", "member_read"],
    )
    no_permission_admin = await add_member(database, 8305, role=MemberRole.ADMINISTRATOR)
    inactive_admin = await add_member(
        database,
        8306,
        role=MemberRole.ADMINISTRATOR,
        status=MemberStatus.PAUSED,
        permissions=["karma_review", "member_read"],
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        vote = KarmaVoteModel(
            rater_id=active_target.id,
            target_id=target.id,
            value=-1,
            comment="Текущая административная оценка.",
            revision=2,
            last_command_id=uuid4(),
        )
        session.add(vote)
        await session.flush()
        session.add_all(
            (
                KarmaVoteHistoryModel(
                    karma_vote_id=vote.id,
                    revision=1,
                    old_value=None,
                    new_value=1,
                    old_comment=None,
                    new_comment="Первая административная оценка.",
                    command_id=uuid4(),
                    actor_member_id=active_target.id,
                ),
                KarmaVoteHistoryModel(
                    karma_vote_id=vote.id,
                    revision=2,
                    old_value=1,
                    new_value=-1,
                    old_comment="Первая административная оценка.",
                    new_comment="Текущая административная оценка.",
                    command_id=vote.last_command_id,
                    actor_member_id=active_target.id,
                ),
            )
        )
    service = ReputationService(database.unit_of_work)
    with pytest.raises(ProfileUnavailableError):
        await service.raw_karma(
            update_id=83_001,
            telegram_user_id=review_admin.telegram_user_id,
            target_id=target.id,
        )
    for denied_admin in (no_permission_admin, inactive_admin):
        with pytest.raises((PermissionError, ProfileUnavailableError)):
            await service.raw_karma(
                update_id=83_010 + denied_admin.telegram_user_id,
                telegram_user_id=denied_admin.telegram_user_id,
                target_id=active_target.id,
            )
    active_rows = await service.raw_karma(
        update_id=83_007,
        telegram_user_id=review_admin.telegram_user_id,
        target_id=active_target.id,
    )
    assert active_rows == ()
    raw_rows = await service.raw_karma(
        update_id=83_002,
        telegram_user_id=both_admin.telegram_user_id,
        target_id=target.id,
    )
    assert len(raw_rows) == 1
    assert raw_rows[0].rater_id == active_target.id
    assert [item.revision for item in raw_rows[0].history] == [1, 2]
    assert raw_rows[0].history[0].new_comment == "Первая административная оценка."
    assert (
        await service.raw_karma(
            update_id=83_002,
            telegram_user_id=both_admin.telegram_user_id,
            target_id=target.id,
        )
        == raw_rows
    )
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count(AuditEventModel.id)).where(
                    AuditEventModel.action == "karma_raw_viewed"
                )
            )
            == 2
        )
    await database.dispose()


async def test_web_and_legacy_confirm_have_one_winner_and_preserve_other_flow(
    database_url: str,
) -> None:
    """Identity/state locks prevent duplicate confirms and cross-flow overwrite."""
    database = Database(database_url)
    creator = await add_member(database, 8351)
    performer = await add_member(database, 8352)
    await add_paid_interaction(database, creator, performer)
    service = ReputationService(database.unit_of_work)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        await session.execute(
            text(
                "INSERT INTO conversation_states "
                "(member_id, flow_type, current_step, payload_json, revision) "
                "VALUES (:member, 'profile_edit', 'city', '{}'::jsonb, 0)"
            ),
            {"member": creator.id},
        )
    with pytest.raises(ValueError, match="conversation"):
        await service.begin_vote(
            update_id=83_510,
            telegram_user_id=creator.telegram_user_id,
            target_id=performer.id,
        )
    async with sessions.begin() as session:
        flow = await session.scalar(
            text("SELECT flow_type FROM conversation_states WHERE member_id = :member"),
            {"member": creator.id},
        )
        assert flow == "profile_edit"
        await session.execute(
            text("DELETE FROM conversation_states WHERE member_id = :member"),
            {"member": creator.id},
        )
    draft = await service.begin_vote(
        update_id=83_511,
        telegram_user_id=creator.telegram_user_id,
        target_id=performer.id,
    )
    draft = await service.save_value(
        update_id=83_512,
        telegram_user_id=creator.telegram_user_id,
        expected_revision=draft.revision,
        value=1,
    )
    draft = await service.save_comment(
        update_id=83_513,
        telegram_user_id=creator.telegram_user_id,
        expected_revision=draft.revision,
        comment="Конкурентная проверка надёжной помощи.",
    )
    outcomes = await asyncio.gather(
        service.confirm_vote(
            update_id=83_514,
            telegram_user_id=creator.telegram_user_id,
            expected_revision=draft.revision,
        ),
        service.confirm_vote(
            update_id=83_515,
            actor_member_id=creator.id,
            target_id=performer.id,
            replay_fingerprint="mixed-confirm",
            expected_revision=draft.revision,
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(item, BaseException) for item in outcomes) == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count(KarmaVoteModel.id))) == 1
        assert await session.scalar(select(func.count(KarmaVoteHistoryModel.id))) == 1
    await database.dispose()


async def test_reciprocal_web_votes_share_pair_lock_without_deadlock(
    database_url: str,
) -> None:
    """Reciprocal Web begin and confirm serialize before sanction/member row locks."""
    database = Database(database_url)
    first = await add_member(database, 8356)
    second = await add_member(database, 8357)
    await prepare_config(database, first.id)
    await add_paid_interaction(database, first, second)
    service = ReputationService(database.unit_of_work)

    first_draft, second_draft = await asyncio.gather(
        service.begin_vote(
            update_id=83_560,
            actor_member_id=first.id,
            target_id=second.id,
            replay_fingerprint="reciprocal-first-begin",
        ),
        service.begin_vote(
            update_id=83_570,
            actor_member_id=second.id,
            target_id=first.id,
            replay_fingerprint="reciprocal-second-begin",
        ),
    )

    async def complete_draft(
        *, actor_id: UUID, target_id: UUID, draft_revision: int, update_base: int
    ) -> int:
        valued = await service.save_value(
            update_id=update_base,
            actor_member_id=actor_id,
            target_id=target_id,
            replay_fingerprint=f"reciprocal-{update_base}-value",
            expected_revision=draft_revision,
            value=1,
        )
        commented = await service.save_comment(
            update_id=update_base + 1,
            actor_member_id=actor_id,
            target_id=target_id,
            replay_fingerprint=f"reciprocal-{update_base}-comment",
            expected_revision=valued.revision,
            comment="Взаимная проверка совместной оплаченной работы.",
        )
        return commented.revision

    first_revision, second_revision = await asyncio.gather(
        complete_draft(
            actor_id=first.id,
            target_id=second.id,
            draft_revision=first_draft.revision,
            update_base=83_561,
        ),
        complete_draft(
            actor_id=second.id,
            target_id=first.id,
            draft_revision=second_draft.revision,
            update_base=83_571,
        ),
    )
    results = await asyncio.gather(
        service.confirm_vote(
            update_id=83_563,
            actor_member_id=first.id,
            target_id=second.id,
            replay_fingerprint="reciprocal-first-confirm",
            expected_revision=first_revision,
        ),
        service.confirm_vote(
            update_id=83_573,
            actor_member_id=second.id,
            target_id=first.id,
            replay_fingerprint="reciprocal-second-confirm",
            expected_revision=second_revision,
        ),
    )
    assert len(results) == 2
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        assert await session.scalar(select(func.count(KarmaVoteModel.id))) == 2
        assert await session.scalar(select(func.count(KarmaVoteHistoryModel.id))) == 2
        assert await session.scalar(select(func.count(ConversationStateModel.member_id))) == 0
    await database.dispose()


async def test_begin_vote_preserves_every_foreign_text_flow(database_url: str) -> None:
    """Karma begin rejects every foreign owner without changing its exact state."""
    database = Database(database_url)
    target = await add_member(database, 8353)
    await prepare_config(database, target.id)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    flows = ("task", "assignment_result", "assignment_dispute", "profile_edit")
    for offset, flow_type in enumerate(flows, start=1):
        actor = await add_member(database, 8353 + offset)
        await add_paid_interaction(database, actor, target)
        reference_id = uuid4()
        payload = {"reference_id": str(reference_id), "private": f"keep-{flow_type}"}
        async with sessions.begin() as session:
            session.add(
                ConversationStateModel(
                    member_id=actor.id,
                    flow_type=flow_type,
                    current_step="text",
                    payload_json=payload,
                    revision=7,
                )
            )
        with pytest.raises(ValueError, match="conversation"):
            await ReputationService(database.unit_of_work).begin_vote(
                update_id=83_520 + offset,
                telegram_user_id=actor.telegram_user_id,
                target_id=target.id,
            )
        async with sessions() as session:
            stored = await session.get(ConversationStateModel, actor.id)
            assert stored is not None
            stored_state = (
                stored.flow_type,
                stored.current_step,
                stored.payload_json,
                stored.revision,
            )
            assert stored_state == (
                flow_type,
                "text",
                payload,
                7,
            )
            assert await session.get(ProcessedTelegramUpdateModel, 83_520 + offset) is None
    await database.dispose()


async def test_cancel_is_idempotent_and_delegates_foreign_flow(database_url: str) -> None:
    """Karma cancel has one receipt/audit while another flow remains untouched."""
    database = Database(database_url)
    creator = await add_member(database, 8361)
    performer = await add_member(database, 8362)
    await add_paid_interaction(database, creator, performer)
    service = ReputationService(database.unit_of_work)
    await service.begin_vote(
        update_id=83_611,
        telegram_user_id=creator.telegram_user_id,
        target_id=performer.id,
    )
    assert await service.cancel_vote(update_id=83_612, telegram_user_id=creator.telegram_user_id)
    assert await service.cancel_vote(update_id=83_612, telegram_user_id=creator.telegram_user_id)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        assert await session.get(ConversationStateModel, creator.id) is None
        receipt_count = await session.scalar(
            select(func.count(ProcessedTelegramUpdateModel.update_id)).where(
                ProcessedTelegramUpdateModel.update_id == 83_612
            )
        )
        audit_count = await session.scalar(
            select(func.count(AuditEventModel.id)).where(
                AuditEventModel.action == "karma_cancelled"
            )
        )
        assert receipt_count == 1
        assert audit_count == 1
        session.add(
            ConversationStateModel(
                member_id=creator.id,
                flow_type="profile_edit",
                current_step="city",
                payload_json={"city": "Rosario"},
                revision=3,
            )
        )
    assert not await service.cancel_vote(
        update_id=83_613, telegram_user_id=creator.telegram_user_id
    )
    async with sessions() as session:
        foreign_flow = await session.get(ConversationStateModel, creator.id)
        assert foreign_flow is not None
        assert foreign_flow.flow_type == "profile_edit"
        assert await session.get(ProcessedTelegramUpdateModel, 83_613) is None
    await database.dispose()


async def test_command_payload_conflict_is_rejected_without_a_revision(database_url: str) -> None:
    """One immutable command identity cannot be reused for another vote payload."""
    database = Database(database_url)
    first = await add_member(database, 8371)
    second = await add_member(database, 8372)
    command_id = uuid4()
    async with database.unit_of_work() as uow:
        await uow.acquire_reputation_pair_gate(first.id, second.id)
        await uow.upsert_karma_vote(
            rater_id=first.id,
            target_id=second.id,
            value=1,
            comment="Один и тот же подтверждённый payload.",
            command_id=command_id,
        )
        await uow.commit()

    async def conflicting_vote() -> None:
        async with database.unit_of_work() as uow:
            await uow.acquire_reputation_pair_gate(first.id, second.id)
            await uow.upsert_karma_vote(
                rater_id=first.id,
                target_id=second.id,
                value=-1,
                comment="Другой payload под тем же command ID.",
                command_id=command_id,
            )

    with pytest.raises(ValueError, match="conflicts"):
        await conflicting_vote()
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        assert await session.scalar(select(func.count(KarmaVoteHistoryModel.id))) == 1
    await database.dispose()


async def test_vote_fault_rolls_back_every_persistent_effect(database_url: str) -> None:
    """A failure before commit leaves no vote, history, receipt, audit, or outbox."""
    database = Database(database_url)
    first = await add_member(database, 8375)
    second = await add_member(database, 8376)

    async def fail_before_commit() -> None:
        async with database.unit_of_work() as uow:
            await uow.acquire_reputation_pair_gate(first.id, second.id)
            await uow.upsert_karma_vote(
                rater_id=first.id,
                target_id=second.id,
                value=1,
                comment="Эта оценка должна полностью откатиться.",
                command_id=uuid4(),
            )
            message = "injected fault before commit"
            raise RuntimeError(message)

    with pytest.raises(RuntimeError, match="injected"):
        await fail_before_commit()
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        assert await session.scalar(select(func.count(KarmaVoteModel.id))) == 0
        assert await session.scalar(select(func.count(KarmaVoteHistoryModel.id))) == 0
        assert await session.scalar(select(func.count(AuditEventModel.id))) == 0
        assert await session.scalar(select(func.count(OutboxEventModel.id))) == 0
        assert await session.scalar(select(func.count(ProcessedTelegramUpdateModel.update_id))) == 0
    await database.dispose()


async def test_safe_catalog_own_paused_profile_and_ledger_pagination(  # noqa: PLR0915
    database_url: str,
) -> None:
    """Catalog hides non-active members and leaderboard keyset has no duplicates."""
    database = Database(database_url)
    actor = await add_member(database, 8381, telegram_username="same_actor")
    await prepare_config(database, actor.id)
    paused = await add_member(database, 8382, status=MemberStatus.PAUSED)
    second = await add_member(database, 8383, telegram_username="beta_match")
    hidden_members = [
        await add_member(
            database,
            8384 + index,
            telegram_username="beta_hidden" if index == 0 else None,
            display_name="Hidden beta" if index == 0 else None,
            status=status,
        )
        for index, status in enumerate(
            (
                MemberStatus.PENDING,
                MemberStatus.RESTRICTED,
                MemberStatus.SUSPENDED,
                MemberStatus.LEFT,
                MemberStatus.BANNED,
            )
        )
    ]
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        stored_actor = await session.get(MemberModel, actor.id)
        stored_second = await session.get(MemberModel, second.id)
        assert stored_actor is not None
        assert stored_second is not None
        stored_actor.display_name = "Same name"
        stored_second.display_name = "same name"
        session.add_all(
            (
                AccountTransactionModel(
                    id=uuid4(),
                    member_id=actor.id,
                    credit_delta=50,
                    experience_delta=0,
                    transaction_type="admin_adjustment",
                    idempotency_key="credits-do-not-rank",
                    payload_hash="3" * 64,
                ),
                AccountTransactionModel(
                    id=uuid4(),
                    member_id=second.id,
                    credit_delta=2,
                    experience_delta=2,
                    transaction_type="admin_adjustment",
                    idempotency_key="experience-ranks",
                    payload_hash="4" * 64,
                ),
            )
        )
    service = ReputationService(database.unit_of_work)
    catalog = await service.members(actor=actor_context(actor))
    ids = {item.member_id for item in catalog.items}
    assert actor.id in ids
    assert second.id in ids
    assert paused.id not in ids
    username_search = await service.members(
        actor=actor_context(actor),
        query="@beta",
    )
    assert [item.member_id for item in username_search.items] == [second.id]
    assert username_search.items[0].telegram_username == "beta_match"
    display_name_search = await service.members(
        actor=actor_context(actor),
        limit=1,
        query="same",
    )
    assert display_name_search.next_cursor is not None
    display_name_next_page = await service.members(
        actor=actor_context(actor),
        limit=10,
        cursor=display_name_search.next_cursor,
        query="same",
    )
    assert display_name_search.items[0].member_id not in {
        item.member_id for item in display_name_next_page.items
    }
    async with sessions.begin() as session:
        stored_second = await session.get(MemberModel, second.id)
        assert stored_second is not None
        stored_second.display_name = "Анна"
    one_character_search = await service.members(
        actor=actor_context(actor),
        query=" \u0430 ",
    )
    assert [item.member_id for item in one_character_search.items] == [second.id]
    whitespace_search = await service.members(actor=actor_context(actor), query="   ")
    assert {item.member_id for item in whitespace_search.items} == {actor.id, second.id}
    assert (await service.profile(actor=actor_context(paused))).member_id == paused.id
    for hidden in hidden_members:
        with pytest.raises(ProfileUnavailableError):
            await service.profile(actor=actor_context(hidden))
    first_catalog_page = await service.members(actor=actor_context(actor), limit=1)
    assert first_catalog_page.next_cursor is not None
    async with sessions.begin() as session:
        stored_second = await session.get(MemberModel, second.id)
        assert stored_second is not None
        stored_second.status = "paused"
    second_catalog_page = await service.members(
        actor=actor_context(actor),
        limit=10,
        cursor=first_catalog_page.next_cursor,
    )
    assert second.id not in {item.member_id for item in second_catalog_page.items}
    async with sessions.begin() as session:
        stored_second = await session.get(MemberModel, second.id)
        assert stored_second is not None
        stored_second.status = "active"
    first_page = await service.leaderboard(actor=actor_context(actor), limit=1)
    assert first_page.items[0].member_id == second.id
    assert first_page.next_cursor is not None
    second_page = await service.leaderboard(
        actor=actor_context(actor),
        limit=10,
        cursor=first_page.next_cursor,
    )
    assert second.id not in {item.member_id for item in second_page.items}
    await database.dispose()


async def test_leaderboard_periods_reuse_ledger_history(database_url: str) -> None:
    """Week, month, and all-time rank the same ledger with bounded cutoffs."""
    database = Database(database_url)
    actor = await add_member(database, 8390)
    await prepare_config(database, actor.id)
    recent = await add_member(database, 8391)
    monthly = await add_member(database, 8392)
    historic = await add_member(database, 8393)
    now = datetime.datetime.now(datetime.UTC)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add_all(
            AccountTransactionModel(
                id=uuid4(),
                member_id=member.id,
                credit_delta=experience,
                experience_delta=experience,
                transaction_type="admin_adjustment",
                idempotency_key=f"period-{label}",
                payload_hash=label * 64,
                created_at=created_at,
            )
            for member, experience, created_at, label in (
                (recent, 3, now - datetime.timedelta(days=1), "1"),
                (monthly, 6, now - datetime.timedelta(days=20), "2"),
                (historic, 9, now - datetime.timedelta(days=40), "3"),
            )
        )

    service = ReputationService(database.unit_of_work)
    week = await service.leaderboard(actor=actor_context(actor), period="week")
    month = await service.leaderboard(actor=actor_context(actor), period="month")
    all_time = await service.leaderboard(actor=actor_context(actor), period="all")

    assert (week.items[0].member_id, week.items[0].experience) == (recent.id, 3)
    assert (month.items[0].member_id, month.items[0].experience) == (monthly.id, 6)
    assert (all_time.items[0].member_id, all_time.items[0].experience) == (historic.id, 9)
    await database.dispose()


async def test_migration_backfills_only_active_administrators(database_url: str) -> None:
    """Upgrade permissions exactly match role/status and downgrade remains clean."""
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "downgrade", "0007"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
    )
    engine = create_async_engine(database_url)
    active_id, paused_id, member_id = uuid4(), uuid4(), uuid4()
    async with engine.begin() as connection:
        for identifier, telegram_id, role, status in (
            (active_id, 8391, "administrator", "active"),
            (paused_id, 8392, "administrator", "paused"),
            (member_id, 8393, "member", "active"),
        ):
            await connection.execute(
                text(
                    "INSERT INTO members "
                    "(id, telegram_user_id, display_name, timezone, role, status, "
                    "level_number, credit_balance_cached, experience_total_cached) "
                    "VALUES (:id, :telegram, 'Migration member', 'UTC', :role, :status, 1, 0, 0)"
                ),
                {"id": identifier, "telegram": telegram_id, "role": role, "status": status},
            )
    await engine.dispose()
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
    )
    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT id, permissions_json FROM members WHERE id IN (:active, :paused, :member)"
            ),
            {"active": active_id, "paused": paused_id, "member": member_id},
        )
        rows = {row[0]: row[1] for row in result}
    await engine.dispose()
    assert set(rows[active_id]) == {
        "interaction_review",
        "karma_review",
        "member_read",
        "superadministrator",
    }
    assert rows[paused_id] == []
    assert rows[member_id] == []


async def test_reliability_chain_and_leaderboard_are_ledger_authoritative(
    database_url: str,
) -> None:
    """Corrections exclude responsibility and stale level cache cannot reorder experience."""
    database = Database(database_url)
    creator = await add_member(database, 8401)
    await prepare_config(database, creator.id)
    performer = await add_member(database, 8402)
    other = await add_member(database, 8403)
    assignment_id = await add_paid_interaction(database, creator, performer, partial=True)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        root = await session.scalar(
            select(ReliabilityEventModel).where(
                ReliabilityEventModel.assignment_id == assignment_id,
                ReliabilityEventModel.event_type == "partially_approved",
            )
        )
        assert root is not None
        excused = ReliabilityEventModel(
            id=uuid4(),
            assignment_id=assignment_id,
            event_type="responsibility_excused",
            supersedes_event_id=root.id,
            reason="system fault",
        )
        session.add(excused)
        performer.level_config_version_id = uuid4()
        session.add(
            AccountTransactionModel(
                id=uuid4(),
                member_id=other.id,
                credit_delta=1,
                experience_delta=1,
                transaction_type="admin_adjustment",
                idempotency_key="other-experience",
                payload_hash="1" * 64,
            )
        )
    service = ReputationService(database.unit_of_work)
    stats = await service.statistics(performer.telegram_user_id)
    assert stats.reliability.accepted == 0
    async with sessions.begin() as session:
        session.add(
            ReliabilityEventModel(
                id=uuid4(),
                assignment_id=assignment_id,
                event_type="responsibility_restored",
                supersedes_event_id=excused.id,
                reason="responsibility confirmed",
            )
        )
    restored = await service.statistics(performer.telegram_user_id)
    assert restored.reliability.accepted == 1
    assert restored.reliability.approved_weight == pytest.approx(0.5)
    page = await service.leaderboard(actor=actor_context(creator))
    experience = {item.member_id: item.experience for item in page.items}
    assert experience[performer.id] == 1
    assert experience[other.id] == 1
    await database.dispose()


async def test_reliability_publishes_exact_partial_weight_at_five_assignments(
    database_url: str,
) -> None:
    """The public rate appears at five and includes one half-weight outcome."""
    database = Database(database_url)
    performer = await add_member(database, 8450)
    for index in range(5):
        creator = await add_member(database, 8451 + index)
        await add_paid_interaction(database, creator, performer, partial=index == 4)
    service = ReputationService(database.unit_of_work)
    stats = await service.statistics(performer.telegram_user_id)
    assert stats.reliability.accepted == 5
    assert float(stats.reliability.approved_weight) == 4.5
    assert float(stats.reliability.rate or 0) == 0.9
    await database.dispose()


async def test_reliability_terminal_matrix_and_member_community_statistics(
    database_url: str,
) -> None:
    """All terminal outcomes, community work, and personal statistics share one oracle."""
    database = Database(database_url)
    performer = await add_member(database, 8460)
    creators = [await add_member(database, 8461 + index) for index in range(7)]
    for creator, terminal in zip(
        creators[:6],
        (
            "approved",
            "partially_approved",
            "rejected",
            "no_show",
            "cancelled_performer",
            "cancelled_creator",
        ),
        strict=True,
    ):
        await add_paid_interaction(database, creator, performer, terminal=terminal)
    await add_paid_interaction(
        database, creators[-1], performer, origin="community", terminal="approved"
    )
    service = ReputationService(database.unit_of_work)
    stats = await service.statistics(performer.telegram_user_id)
    assert stats.completed == 2
    assert stats.partially_completed == 1
    assert stats.experience_earned == 5
    assert stats.unique_recipients == 2
    assert len(stats.categories) == 1
    assert stats.no_show == 1
    assert stats.reliability.accepted == 6
    assert stats.reliability.approved_weight == Decimal("2.5")
    assert stats.reliability.rate == Decimal(5) / Decimal(12)
    await database.dispose()


async def test_database_constraints_protect_private_history_and_reliability(  # noqa: PLR0915
    database_url: str,
) -> None:
    """Direct SQL cannot mutate karma history or create invalid supersedes."""
    database = Database(database_url)
    first = await add_member(database, 8501)
    second = await add_member(database, 8502)
    await add_paid_interaction(database, first, second)
    service = ReputationService(database.unit_of_work)
    draft = await service.begin_vote(
        update_id=85_001, telegram_user_id=first.telegram_user_id, target_id=second.id
    )
    draft = await service.save_value(
        update_id=85_002,
        telegram_user_id=first.telegram_user_id,
        expected_revision=draft.revision,
        value=1,
    )
    draft = await service.save_comment(
        update_id=85_003,
        telegram_user_id=first.telegram_user_id,
        expected_revision=draft.revision,
        comment="Надёжная и полезная помощь участнику.",
    )
    await service.confirm_vote(
        update_id=85_004,
        telegram_user_id=first.telegram_user_id,
        expected_revision=draft.revision,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)

    async def insert_raw_vote(rater_id: UUID, target_id: UUID, value: int) -> None:
        async with sessions.begin() as session:
            session.add(
                KarmaVoteModel(
                    rater_id=rater_id,
                    target_id=target_id,
                    value=value,
                    comment="Invalid direct SQL fixture.",
                    revision=1,
                    last_command_id=uuid4(),
                )
            )

    with pytest.raises(DBAPIError):
        await insert_raw_vote(first.id, first.id, 1)
    with pytest.raises(DBAPIError):
        await insert_raw_vote(second.id, first.id, 2)
    with pytest.raises(DBAPIError):
        await insert_raw_vote(first.id, second.id, 0)

    async def update_history() -> None:
        async with sessions.begin() as session:
            await session.execute(text("UPDATE karma_vote_history SET new_value = -1"))

    with pytest.raises(DBAPIError):
        await update_history()

    async def delete_history() -> None:
        async with sessions.begin() as session:
            await session.execute(text("DELETE FROM karma_vote_history"))

    with pytest.raises(DBAPIError):
        await delete_history()
    other_assignment_id = await add_paid_interaction(database, first, second)
    async with sessions() as session:
        first_root = await session.scalar(
            select(ReliabilityEventModel).where(
                ReliabilityEventModel.assignment_id != other_assignment_id,
                ReliabilityEventModel.event_type == "approved",
            )
        )
        assert first_root is not None
    with pytest.raises(DBAPIError):
        async with sessions.begin() as session:
            session.add(
                ReliabilityEventModel(
                    id=uuid4(),
                    assignment_id=other_assignment_id,
                    event_type="responsibility_excused",
                    supersedes_event_id=first_root.id,
                    reason="invalid cross assignment correction",
                )
            )
    async with sessions.begin() as session:
        correction = ReliabilityEventModel(
            id=uuid4(),
            assignment_id=first_root.assignment_id,
            event_type="responsibility_excused",
            supersedes_event_id=first_root.id,
            reason="valid correction",
        )
        session.add(correction)

    async def duplicate_supersede() -> None:
        async with sessions.begin() as session:
            session.add(
                ReliabilityEventModel(
                    id=uuid4(),
                    assignment_id=first_root.assignment_id,
                    event_type="responsibility_restored",
                    supersedes_event_id=first_root.id,
                    reason="duplicate leaf",
                )
            )

    with pytest.raises(DBAPIError):
        await duplicate_supersede()

    async def cyclic_supersede() -> None:
        identifier = uuid4()
        async with sessions.begin() as session:
            session.add(
                ReliabilityEventModel(
                    id=identifier,
                    assignment_id=first_root.assignment_id,
                    event_type="responsibility_restored",
                    supersedes_event_id=identifier,
                    reason="self cycle",
                )
            )

    with pytest.raises(DBAPIError):
        await cyclic_supersede()
    await database.dispose()
