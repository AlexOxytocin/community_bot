from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.economy import (
    EconomyQueryService,
    EconomyService,
    ProductConfigActivationCommand,
    ProductConfigBootstrapCoordinator,
    ProductConfigService,
)
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.bootstrap.product_config_cli import _bootstrap as bootstrap_product_config
from community_bot.domain.economy import (
    AdministrativeContext,
    IdempotencyConflictError,
    InsufficientBalanceError,
    ReversalCommand,
    admin_adjustment,
    apply_penalty,
    earn_reward,
    reserve_reward,
    starting_grant,
)
from community_bot.domain.members import AuthorizationError, MemberRole, MemberStatus
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    ActiveProductConfigModel,
    AuditEventModel,
    LevelBackfillRunModel,
    MemberModel,
    ProductConfigActivationModel,
    ProductConfigVersionModel,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

CONFIG_PATH = Path(__file__).parents[2] / "config" / "product-config.v1.json"


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
            telegram_user_id=telegram_user_id,
            display_name=f"Member {telegram_user_id}",
            timezone="UTC",
            role=role.value,
            status=status.value,
            level_number=1,
        )
        session.add(member)
    return member


async def prepare_config(database: Database, admin_id: UUID) -> None:
    coordinator = ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    )
    await coordinator.prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin_id,
        activation_command_id=uuid4(),
        reason="Initial product configuration.",
    )


async def model_count(database: Database, model: type[object]) -> int:
    async with database.engine.connect() as connection:
        return int(await connection.scalar(select(func.count()).select_from(model)) or 0)


async def test_bootstrap_ingests_activates_backfills_and_replays(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=10, role=MemberRole.ADMINISTRATOR)
    member = await add_member(database, telegram_user_id=11)
    command_id = uuid4()
    coordinator = ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    )

    first = await coordinator.prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=command_id,
        reason="Initial product configuration.",
    )
    replay = await coordinator.prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=command_id,
        reason="Initial product configuration.",
    )

    assert replay == first
    assert first.version == 1
    assert len(first.levels) == 10
    assert await model_count(database, ProductConfigVersionModel) == 1
    assert await model_count(database, ProductConfigActivationModel) == 1
    assert await model_count(database, LevelBackfillRunModel) == 1
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        persisted = await session.get(MemberModel, member.id)
        assert persisted is not None
        assert persisted.level_config_version_id == first.id
    await database.dispose()


async def test_product_config_cli_bootstrap_requires_one_admin_and_replays(
    database_url: str,
) -> None:
    database = Database(database_url)
    with pytest.raises(AuthorizationError, match="exactly one active administrator"):
        await bootstrap_product_config(database_url, CONFIG_PATH)

    await add_member(database, telegram_user_id=12, role=MemberRole.ADMINISTRATOR)
    first = await bootstrap_product_config(database_url, CONFIG_PATH)
    await add_member(database, telegram_user_id=13, role=MemberRole.ADMINISTRATOR)
    replay = await bootstrap_product_config(database_url, CONFIG_PATH)

    assert first == replay == 1
    assert await model_count(database, ProductConfigVersionModel) == 1
    assert await model_count(database, ProductConfigActivationModel) == 1
    assert await model_count(database, LevelBackfillRunModel) == 1
    await database.dispose()


async def test_activation_uses_distinct_command_identity_for_rollback(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=20, role=MemberRole.ADMINISTRATOR)
    service = ProductConfigService(database.unit_of_work)
    first = load_product_config_candidate(CONFIG_PATH)
    await service.ingest(candidate=first, actor_member_id=admin.id)
    first_activation = await service.activate(
        ProductConfigActivationCommand(uuid4(), 1, admin.id, "Activate version 1.")
    )
    second = replace(first, config_version=2, interaction_alert_threshold=4)
    await service.ingest(candidate=second, actor_member_id=admin.id)
    await service.activate(
        ProductConfigActivationCommand(uuid4(), 2, admin.id, "Activate version 2.")
    )
    rollback = await service.activate(
        ProductConfigActivationCommand(uuid4(), 1, admin.id, "Rollback to version 1.")
    )

    assert rollback.target_config_id == first_activation.target_config_id
    assert rollback.outcome_code == "activated"
    async with database.engine.connect() as connection:
        active_version = await connection.scalar(
            select(ProductConfigVersionModel.version)
            .join(
                ActiveProductConfigModel,
                ActiveProductConfigModel.product_config_version_id == ProductConfigVersionModel.id,
            )
            .where(ActiveProductConfigModel.singleton_key)
        )
    assert active_version == 1
    await database.dispose()


async def test_config_identity_rejects_changed_payload_and_duplicate_hash(
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=30, role=MemberRole.ADMINISTRATOR)
    service = ProductConfigService(database.unit_of_work)
    candidate = load_product_config_candidate(CONFIG_PATH)
    await service.ingest(candidate=candidate, actor_member_id=admin.id)

    with pytest.raises(IdempotencyConflictError, match="another payload"):
        await service.ingest(
            candidate=replace(candidate, interaction_alert_threshold=4),
            actor_member_id=admin.id,
        )
    with pytest.raises(IdempotencyConflictError, match="same product config payload"):
        await service.ingest(
            candidate=replace(candidate, config_version=2), actor_member_id=admin.id
        )
    await database.dispose()


async def test_starting_grant_is_persistent_replay_safe_and_singleton(database_url: str) -> None:
    database = Database(database_url)
    member = await add_member(database, telegram_user_id=40)
    service = EconomyService(database.unit_of_work)

    first = await service.apply_one(starting_grant(member.id))
    replay = await service.apply_one(starting_grant(member.id))

    assert replay.transaction_id == first.transaction_id
    assert replay.replayed
    assert await model_count(database, AccountTransactionModel) == 1
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        persisted = await session.get(MemberModel, member.id)
        assert persisted is not None
        assert persisted.credit_balance_cached == 10
    await database.dispose()


async def test_batch_is_all_new_or_all_stored_and_rolls_back_on_failure(database_url: str) -> None:
    database = Database(database_url)
    first_member = await add_member(database, telegram_user_id=50)
    second_member = await add_member(database, telegram_user_id=51)
    service = EconomyService(database.unit_of_work)
    commands = (starting_grant(first_member.id), starting_grant(second_member.id))

    created = await service.apply_batch(commands)
    replayed = await service.apply_batch(tuple(reversed(commands)))
    assert {item.transaction_id for item in replayed} == {item.transaction_id for item in created}
    assert all(item.replayed for item in replayed)

    third = await add_member(database, telegram_user_id=52)
    with pytest.raises(IdempotencyConflictError, match="mix"):
        await service.apply_batch((commands[0], starting_grant(third.id)))
    assert await model_count(database, AccountTransactionModel) == 2

    with pytest.raises(InsufficientBalanceError):
        await service.apply_batch(
            (
                reserve_reward(member_id=first_member.id, amount=3, idempotency_key="reserve:ok"),
                reserve_reward(
                    member_id=second_member.id,
                    amount=11,
                    idempotency_key="reserve:fail",
                ),
            )
        )
    assert await model_count(database, AccountTransactionModel) == 2
    await database.dispose()


async def test_rewards_update_experience_and_level_against_active_version(
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=60, role=MemberRole.ADMINISTRATOR)
    member = await add_member(database, telegram_user_id=61)
    await prepare_config(database, admin.id)
    service = EconomyService(database.unit_of_work)
    await service.apply_one(starting_grant(member.id))
    await service.apply_one(
        earn_reward(member_id=member.id, amount=10, idempotency_key="reward:10")
    )

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        persisted = await session.get(MemberModel, member.id)
        assert persisted is not None
        assert persisted.credit_balance_cached == 20
        assert persisted.experience_total_cached == 10
        assert persisted.level_number == 2
        assert persisted.level_config_version_id is not None
    await database.dispose()


async def test_admin_mutations_require_active_admin_and_append_audit(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=70, role=MemberRole.ADMINISTRATOR)
    ordinary = await add_member(database, telegram_user_id=71)
    target = await add_member(database, telegram_user_id=72)
    service = EconomyService(database.unit_of_work)
    await service.apply_one(starting_grant(target.id))

    with pytest.raises(AuthorizationError):
        await service.apply_one(
            apply_penalty(
                member_id=target.id,
                amount=1,
                idempotency_key="penalty:unauthorized",
                context=AdministrativeContext(ordinary.id, "Invalid actor."),
            )
        )
    penalty = await service.apply_one(
        apply_penalty(
            member_id=target.id,
            amount=2,
            idempotency_key="penalty:authorized",
            context=AdministrativeContext(admin.id, "Confirmed policy violation."),
        )
    )
    assert penalty.credit_delta == -2
    assert await model_count(database, AuditEventModel) == 1
    await database.dispose()


async def test_exact_reversal_is_single_and_restores_both_totals(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=80, role=MemberRole.ADMINISTRATOR)
    member = await add_member(database, telegram_user_id=81)
    await prepare_config(database, admin.id)
    service = EconomyService(database.unit_of_work)
    await service.apply_one(starting_grant(member.id))
    reward = await service.apply_one(
        earn_reward(member_id=member.id, amount=10, idempotency_key="reward:reverse")
    )
    reversal = await service.apply_one(
        ReversalCommand(
            reversed_transaction_id=reward.transaction_id,
            idempotency_key="reversal:1",
            actor_member_id=admin.id,
            reason="Fraud confirmed.",
        )
    )

    assert reversal.credit_delta == -10
    assert reversal.experience_delta == -10
    with pytest.raises(IdempotencyConflictError, match="exactly once"):
        await service.apply_one(
            ReversalCommand(
                reversed_transaction_id=reward.transaction_id,
                idempotency_key="reversal:2",
                actor_member_id=admin.id,
                reason="Duplicate reversal.",
            )
        )
    with pytest.raises(DBAPIError, match="cannot reverse another reversal"):
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO account_transactions "
                    "(id, member_id, credit_delta, experience_delta, transaction_type, "
                    "idempotency_key, payload_hash, created_by_member_id, reason, "
                    "reversed_transaction_id) VALUES "
                    "(:id, :member_id, 10, 10, 'fraud_reversal', :key, :hash, "
                    ":actor_id, 'Invalid chain.', :source_id)"
                ),
                {
                    "id": uuid4(),
                    "member_id": member.id,
                    "key": "reversal:chain",
                    "hash": "x" * 64,
                    "actor_id": admin.id,
                    "source_id": reversal.transaction_id,
                },
            )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        persisted = await session.get(MemberModel, member.id)
        assert persisted is not None
        assert persisted.credit_balance_cached == 10
        assert persisted.experience_total_cached == 0
    await database.dispose()


async def test_concurrent_mutations_serialize_without_lost_updates(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=90, role=MemberRole.ADMINISTRATOR)
    member = await add_member(database, telegram_user_id=91)
    await prepare_config(database, admin.id)
    service = EconomyService(database.unit_of_work)

    await asyncio.wait_for(
        asyncio.gather(
            service.apply_one(
                earn_reward(member_id=member.id, amount=3, idempotency_key="concurrent:1")
            ),
            service.apply_one(
                earn_reward(member_id=member.id, amount=4, idempotency_key="concurrent:2")
            ),
        ),
        timeout=10,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        persisted = await session.get(MemberModel, member.id)
        assert persisted is not None
        assert persisted.credit_balance_cached == 7
        assert persisted.experience_total_cached == 7
    await database.dispose()


async def test_history_authorization_pagination_and_reconciliation(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=100, role=MemberRole.ADMINISTRATOR)
    member = await add_member(database, telegram_user_id=101)
    stranger = await add_member(database, telegram_user_id=102)
    service = EconomyService(database.unit_of_work)
    await service.apply_one(starting_grant(member.id))
    await service.apply_one(
        admin_adjustment(
            member_id=member.id,
            credit_delta=1,
            experience_delta=0,
            idempotency_key="history:adjustment",
            context=AdministrativeContext(admin.id, "History fixture."),
        )
    )
    queries = EconomyQueryService(database.unit_of_work)

    first = await queries.history(
        telegram_user_id=member.telegram_user_id, target_member_id=member.id, limit=1
    )
    second = await queries.history(
        telegram_user_id=member.telegram_user_id,
        target_member_id=member.id,
        limit=1,
        cursor=first.next_cursor,
    )
    assert len(first.items) == len(second.items) == 1
    assert first.items[0].transaction_id != second.items[0].transaction_id
    with pytest.raises(AuthorizationError):
        await queries.history(
            telegram_user_id=stranger.telegram_user_id, target_member_id=member.id
        )

    async with database.engine.begin() as connection:
        await connection.execute(
            text("UPDATE members SET credit_balance_cached = 999 WHERE id = :member_id"),
            {"member_id": member.id},
        )
    mismatches = await queries.reconcile(actor_member_id=admin.id)
    assert len(mismatches) == 1
    assert mismatches[0].member_id == member.id
    assert mismatches[0].expected_credit_balance == 11
    assert mismatches[0].actual_credit_balance == 999

    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE members SET credit_balance_cached = 11, "
                "experience_total_cached = 9 WHERE id = :member_id"
            ),
            {"member_id": member.id},
        )
    experience_mismatch = await queries.reconcile(actor_member_id=admin.id)
    assert len(experience_mismatch) == 1
    assert experience_mismatch[0].expected_credit_balance == 11
    assert experience_mismatch[0].actual_credit_balance == 11
    assert experience_mismatch[0].expected_experience_total == 0
    assert experience_mismatch[0].actual_experience_total == 9

    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE members SET credit_balance_cached = 998, "
                "experience_total_cached = 8 WHERE id = :member_id"
            ),
            {"member_id": member.id},
        )
    both_mismatch = await queries.reconcile(actor_member_id=admin.id)
    assert len(both_mismatch) == 1
    assert both_mismatch[0].actual_credit_balance == 998
    assert both_mismatch[0].actual_experience_total == 8
    assert await model_count(database, AccountTransactionModel) == 2
    await database.dispose()


async def test_append_only_triggers_reject_direct_update_and_delete(database_url: str) -> None:
    database = Database(database_url)
    member = await add_member(database, telegram_user_id=110)
    transaction = await EconomyService(database.unit_of_work).apply_one(starting_grant(member.id))

    with pytest.raises(DBAPIError):
        async with database.engine.begin() as connection:
            await connection.execute(
                text("UPDATE account_transactions SET credit_delta = 6 WHERE id = :id"),
                {"id": transaction.transaction_id},
            )
    with pytest.raises(DBAPIError):
        async with database.engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM account_transactions WHERE id = :id"),
                {"id": transaction.transaction_id},
            )
    assert await model_count(database, AccountTransactionModel) == 1
    await database.dispose()
