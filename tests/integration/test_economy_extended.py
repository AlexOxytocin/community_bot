from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from community_bot.application.economy import (
    EconomyQueryService,
    EconomyService,
    ProductConfigActivationCommand,
    ProductConfigBootstrapCoordinator,
    ProductConfigService,
)
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.domain.economy import (
    AdministrativeContext,
    EconomyError,
    IdempotencyConflictError,
    InsufficientBalanceError,
    ProductConfigError,
    ReversalCommand,
    TransactionType,
    admin_adjustment,
    apply_penalty,
    earn_community_reward,
    earn_partial_reward,
    earn_reward,
    refund_reward,
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

if TYPE_CHECKING:
    from community_bot.domain.economy import EconomyMutationCommand

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

CONFIG_PATH = Path(__file__).parents[2] / "config" / "product-config.v1.json"


async def add_member(
    database: Database,
    *,
    telegram_user_id: int,
    role: MemberRole = MemberRole.MEMBER,
    status: MemberStatus = MemberStatus.ACTIVE,
    member_id: UUID | None = None,
) -> MemberModel:
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        member = MemberModel(
            id=member_id or uuid4(),
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
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin_id,
        activation_command_id=uuid4(),
        reason="Initial configuration.",
    )


async def count(database: Database, model: type[Any]) -> int:
    async with database.engine.connect() as connection:
        return int(await connection.scalar(select(func.count()).select_from(model)) or 0)


def injected_failure() -> None:
    message = "Injected failure."
    raise RuntimeError(message)


async def assert_database_error(
    database: Database, statement: str, parameters: dict[str, object]
) -> None:
    with pytest.raises(DBAPIError):
        async with database.engine.begin() as connection:
            await connection.execute(text(statement), parameters)


async def apply_faulty_composition(
    database: Database, commands: tuple[EconomyMutationCommand, ...]
) -> None:
    async with database.unit_of_work() as unit_of_work:
        await unit_of_work.append_audit_event(
            actor_member_id=None,
            action="task_like_marker",
            entity_type="task_like",
            entity_id="rollback",
            reason="Composition rollback.",
        )
        await unit_of_work.economy.apply_batch(commands)
        injected_failure()


async def apply_composed_batch(
    database: Database,
    *,
    marker_id: str,
    commands: tuple[EconomyMutationCommand, ...],
) -> None:
    async with database.unit_of_work() as unit_of_work:
        await unit_of_work.append_audit_event(
            actor_member_id=None,
            action="task_like_marker",
            entity_type="task_like",
            entity_id=marker_id,
            reason="Composed economy batch.",
        )
        await unit_of_work.economy.apply_batch(commands)
        await unit_of_work.commit()


async def test_migration_uses_bigint_for_caches_and_ledger(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=201, role=MemberRole.ADMINISTRATOR)
    target = await add_member(database, telegram_user_id=202)
    large_value = 2**31 + 17
    await EconomyService(database.unit_of_work).apply_one(
        admin_adjustment(
            member_id=target.id,
            credit_delta=large_value,
            experience_delta=0,
            idempotency_key="large-credit",
            context=AdministrativeContext(admin.id, "BIGINT boundary."),
        )
    )
    async with database.engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = 'members' AND column_name IN "
                    "('credit_balance_cached', 'experience_total_cached')"
                )
            )
        ).all()
        types = {str(row[0]): str(row[1]) for row in rows}
        persisted = await connection.scalar(
            select(MemberModel.credit_balance_cached).where(MemberModel.id == target.id)
        )
        total = await connection.scalar(select(func.sum(AccountTransactionModel.credit_delta)))
    assert types == {
        "credit_balance_cached": "bigint",
        "experience_total_cached": "bigint",
    }
    assert persisted == total == large_value
    await database.dispose()

    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    configuration = Config("alembic.ini")
    try:
        with pytest.raises(DBAPIError, match="cannot be downgraded"):
            await asyncio.to_thread(alembic_command.downgrade, configuration, "0002")
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url


async def test_migration_rejects_untrusted_legacy_caches(database_url: str) -> None:
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    configuration = Config("alembic.ini")
    try:
        await asyncio.to_thread(alembic_command.downgrade, configuration, "0002")
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO members "
                    "(id, telegram_user_id, display_name, timezone, role, status, "
                    "level_number, credit_balance_cached, experience_total_cached) "
                    "VALUES (:id, 9999, 'Legacy', 'UTC', 'member', 'active', 1, 1, 0)"
                ),
                {"id": uuid4()},
            )
        await engine.dispose()
        with pytest.raises(DBAPIError, match="legacy member caches"):
            await asyncio.to_thread(alembic_command.upgrade, configuration, "head")
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url


async def test_database_constraints_reject_invalid_ledger_rows(database_url: str) -> None:
    database = Database(database_url)
    member = await add_member(database, telegram_user_id=210)
    other = await add_member(database, telegram_user_id=211)
    service = EconomyService(database.unit_of_work)
    grant = await service.apply_one(starting_grant(member.id))
    base = {
        "id": uuid4(),
        "member": member.id,
        "key": "invalid",
        "hash": "x" * 64,
    }
    invalid_rows = (
        ("unknown", 1, 0, None),
        ("task_reward_reserved", -1, 1, None),
        ("task_reward_refunded", 1, 1, None),
        ("task_reward_earned", 2, 1, None),
        ("partial_task_reward", 2, 1, None),
        ("community_task_reward", 2, 1, None),
        ("penalty", -1, 1, None),
        ("admin_adjustment", 0, 0, None),
        ("fraud_reversal", -5, 0, None),
        ("fraud_reversal", -4, 0, grant.transaction_id),
    )
    for index, (transaction_type, credit, experience, source) in enumerate(invalid_rows):
        await assert_database_error(
            database,
            "INSERT INTO account_transactions "
            "(id, member_id, credit_delta, experience_delta, transaction_type, "
            "idempotency_key, payload_hash, reversed_transaction_id) "
            "VALUES (:id, :member, :credit, :experience, :type, :key, :hash, :source)",
            {
                **base,
                "id": uuid4(),
                "key": f"invalid:{index}",
                "type": transaction_type,
                "credit": credit,
                "experience": experience,
                "source": source,
            },
        )
    await assert_database_error(
        database,
        "INSERT INTO account_transactions "
        "(id, member_id, credit_delta, experience_delta, transaction_type, "
        "idempotency_key, payload_hash) VALUES "
        "(:id, :member, 10, 0, 'starting_grant', :key, :hash)",
        {**base, "id": uuid4(), "key": "second-grant"},
    )
    await assert_database_error(
        database,
        "INSERT INTO account_transactions "
        "(id, member_id, credit_delta, experience_delta, transaction_type, "
        "idempotency_key, payload_hash, reversed_transaction_id) VALUES "
        "(:id, :other, -5, 0, 'fraud_reversal', :key, :hash, :source)",
        {
            **base,
            "id": uuid4(),
            "other": other.id,
            "key": "wrong-member-reversal",
            "source": grant.transaction_id,
        },
    )
    assert await count(database, AccountTransactionModel) == 1
    await database.dispose()


async def test_operation_matrix_keeps_cache_equal_to_ledger(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=220, role=MemberRole.ADMINISTRATOR)
    member = await add_member(database, telegram_user_id=221)
    await prepare_config(database, admin.id)
    service = EconomyService(database.unit_of_work)
    commands = (
        starting_grant(member.id),
        refund_reward(member_id=member.id, amount=10, idempotency_key="matrix:refund"),
        reserve_reward(member_id=member.id, amount=3, idempotency_key="matrix:reserve"),
        earn_reward(member_id=member.id, amount=4, idempotency_key="matrix:earned"),
        earn_partial_reward(member_id=member.id, amount=2, idempotency_key="matrix:partial"),
        earn_community_reward(member_id=member.id, amount=3, idempotency_key="matrix:community"),
        apply_penalty(
            member_id=member.id,
            amount=1,
            idempotency_key="matrix:penalty",
            context=AdministrativeContext(admin.id, "Matrix penalty."),
        ),
        admin_adjustment(
            member_id=member.id,
            credit_delta=2,
            experience_delta=-1,
            idempotency_key="matrix:adjustment",
            context=AdministrativeContext(admin.id, "Matrix correction."),
        ),
    )
    for command in commands:
        await service.apply_one(command)

    async with database.engine.connect() as connection:
        member_row = await connection.execute(
            select(
                MemberModel.credit_balance_cached,
                MemberModel.experience_total_cached,
            ).where(MemberModel.id == member.id)
        )
        cache = member_row.one()
        sums = (
            await connection.execute(
                select(
                    func.sum(AccountTransactionModel.credit_delta),
                    func.sum(AccountTransactionModel.experience_delta),
                ).where(AccountTransactionModel.member_id == member.id)
            )
        ).one()
    assert cache == sums == (27, 8)
    await database.dispose()


async def test_payload_conflicts_and_fault_rollback_have_no_partial_effect(
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=230, role=MemberRole.ADMINISTRATOR)
    member = await add_member(database, telegram_user_id=231)
    command = admin_adjustment(
        member_id=member.id,
        credit_delta=5,
        experience_delta=0,
        idempotency_key="canonical-command",
        context=AdministrativeContext(admin.id, "  Canonical reason.  ", "  Comment.  "),
    )
    service = EconomyService(database.unit_of_work)
    first = await service.apply_one(command)
    normalized_replay = await service.apply_one(
        replace(command, reason="Canonical reason.", comment="Comment.")
    )
    assert normalized_replay.transaction_id == first.transaction_id
    assert normalized_replay.replayed

    changes = (
        replace(command, credit_delta=6),
        replace(command, experience_delta=1),
        replace(command, member_id=admin.id),
        replace(command, actor_member_id=member.id),
        replace(command, reason="Another reason."),
        replace(command, comment="Another comment."),
    )
    for changed in changes:
        with pytest.raises(IdempotencyConflictError):
            await service.apply_one(changed)
    assert await count(database, AccountTransactionModel) == 1
    assert await count(database, AuditEventModel) == 1

    faulting = EconomyService(lambda: database.unit_of_work(after_ledger_flushed=injected_failure))
    fault_command = admin_adjustment(
        member_id=member.id,
        credit_delta=7,
        experience_delta=0,
        idempotency_key="fault-command",
        context=AdministrativeContext(admin.id, "Fault test."),
    )
    with pytest.raises(RuntimeError, match="Injected"):
        await faulting.apply_one(fault_command)
    assert await count(database, AccountTransactionModel) == 1
    retry = await service.apply_one(fault_command)
    assert not retry.replayed
    assert await count(database, AccountTransactionModel) == 2

    cache_fault_command = admin_adjustment(
        member_id=member.id,
        credit_delta=3,
        experience_delta=0,
        idempotency_key="cache-fault-command",
        context=AdministrativeContext(admin.id, "Cache fault test."),
    )
    cache_faulting = EconomyService(
        lambda: database.unit_of_work(after_economy_cache_flushed=injected_failure)
    )
    with pytest.raises(RuntimeError, match="Injected"):
        await cache_faulting.apply_one(cache_fault_command)
    assert await count(database, AccountTransactionModel) == 2
    assert await count(database, AuditEventModel) == 2
    cache_retry = await service.apply_one(cache_fault_command)
    assert not cache_retry.replayed
    assert await count(database, AccountTransactionModel) == 3
    await database.dispose()


async def test_idempotency_conflicts_include_transaction_type_and_reversal_source(
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=235, role=MemberRole.ADMINISTRATOR)
    member = await add_member(database, telegram_user_id=236)
    service = EconomyService(database.unit_of_work)
    base = admin_adjustment(
        member_id=member.id,
        credit_delta=10,
        experience_delta=0,
        idempotency_key="semantic:type",
        context=AdministrativeContext(admin.id, "Semantic type fixture."),
    )
    await service.apply_one(base)
    with pytest.raises(IdempotencyConflictError):
        await service.apply_one(
            replace(base, transaction_type=TransactionType.TASK_REWARD_REFUNDED)
        )

    first_source = await service.apply_one(
        refund_reward(member_id=member.id, amount=2, idempotency_key="source:first")
    )
    second_source = await service.apply_one(
        refund_reward(member_id=member.id, amount=2, idempotency_key="source:second")
    )
    reversal = ReversalCommand(
        reversed_transaction_id=first_source.transaction_id,
        idempotency_key="semantic:reversal-source",
        actor_member_id=admin.id,
        reason="Semantic source fixture.",
    )
    await service.apply_one(reversal)
    with pytest.raises(IdempotencyConflictError):
        await service.apply_one(
            replace(reversal, reversed_transaction_id=second_source.transaction_id)
        )
    assert await count(database, AccountTransactionModel) == 4
    await database.dispose()


async def test_concurrent_grant_and_reserve_never_lose_or_overdraw(database_url: str) -> None:
    database = Database(database_url)
    member = await add_member(database, telegram_user_id=240)
    service = EconomyService(database.unit_of_work)

    grants = await asyncio.wait_for(
        asyncio.gather(
            service.apply_one(starting_grant(member.id)),
            service.apply_one(starting_grant(member.id)),
        ),
        timeout=10,
    )
    assert grants[0].transaction_id == grants[1].transaction_id
    await service.apply_one(
        refund_reward(member_id=member.id, amount=5, idempotency_key="reserve:funding")
    )

    results = await asyncio.wait_for(
        asyncio.gather(
            service.apply_one(
                reserve_reward(member_id=member.id, amount=12, idempotency_key="reserve:12")
            ),
            service.apply_one(
                reserve_reward(member_id=member.id, amount=11, idempotency_key="reserve:11")
            ),
            return_exceptions=True,
        ),
        timeout=10,
    )
    assert sum(isinstance(result, InsufficientBalanceError) for result in results) == 1
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        persisted = await session.get(MemberModel, member.id)
        ledger_sum = await session.scalar(
            select(func.sum(AccountTransactionModel.credit_delta)).where(
                AccountTransactionModel.member_id == member.id
            )
        )
    assert persisted is not None
    assert persisted.credit_balance_cached == ledger_sum
    assert persisted.credit_balance_cached in {3, 4}
    assert persisted.experience_total_cached == 0

    small_results = await asyncio.wait_for(
        asyncio.gather(
            *(
                service.apply_one(
                    reserve_reward(
                        member_id=member.id,
                        amount=1,
                        idempotency_key=f"reserve:small:{index}",
                    )
                )
                for index in range(6)
            ),
            return_exceptions=True,
        ),
        timeout=10,
    )
    assert any(isinstance(result, InsufficientBalanceError) for result in small_results)
    async with sessions() as session:
        persisted = await session.get(MemberModel, member.id)
        ledger_sum = await session.scalar(
            select(func.sum(AccountTransactionModel.credit_delta)).where(
                AccountTransactionModel.member_id == member.id
            )
        )
    assert persisted is not None
    assert persisted.credit_balance_cached == ledger_sum == 0
    assert persisted.experience_total_cached == 0
    await database.dispose()


async def test_config_authorization_concurrency_activation_and_fault(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=250, role=MemberRole.ADMINISTRATOR)
    member = await add_member(database, telegram_user_id=251)
    moderator = await add_member(database, telegram_user_id=253, role=MemberRole.MODERATOR)
    inactive_admin = await add_member(
        database,
        telegram_user_id=252,
        role=MemberRole.ADMINISTRATOR,
        status=MemberStatus.PAUSED,
    )
    candidate = load_product_config_candidate(CONFIG_PATH)
    service = ProductConfigService(database.unit_of_work)
    for actor_id in (member.id, moderator.id, inactive_admin.id):
        with pytest.raises(AuthorizationError):
            await service.ingest(candidate=candidate, actor_member_id=actor_id)
    assert await count(database, ProductConfigVersionModel) == 0

    ingested = await asyncio.wait_for(
        asyncio.gather(
            service.ingest(candidate=candidate, actor_member_id=admin.id),
            service.ingest(candidate=candidate, actor_member_id=admin.id),
        ),
        timeout=10,
    )
    assert ingested[0].id == ingested[1].id
    collisions = await asyncio.wait_for(
        asyncio.gather(
            service.ingest(
                candidate=replace(candidate, interaction_alert_threshold=4),
                actor_member_id=admin.id,
            ),
            service.ingest(
                candidate=replace(candidate, config_version=2),
                actor_member_id=admin.id,
            ),
            return_exceptions=True,
        ),
        timeout=10,
    )
    assert all(isinstance(result, IdempotencyConflictError) for result in collisions)
    assert await count(database, ProductConfigVersionModel) == 1
    first_command = ProductConfigActivationCommand(uuid4(), 1, admin.id, "First activation.")
    activations = await asyncio.wait_for(
        asyncio.gather(service.activate(first_command), service.activate(first_command)),
        timeout=10,
    )
    assert activations[0].activation_id == activations[1].activation_id
    assert sum(result.replayed for result in activations) == 1

    noop = await service.activate(
        ProductConfigActivationCommand(uuid4(), 1, admin.id, "Already active check.")
    )
    assert noop.outcome_code == "already_active"
    assert await count(database, LevelBackfillRunModel) == 1
    for actor_id in (member.id, moderator.id, inactive_admin.id):
        with pytest.raises(AuthorizationError):
            await service.activate(
                ProductConfigActivationCommand(uuid4(), 1, actor_id, "Unauthorized.")
            )
    with pytest.raises(LookupError):
        await service.activate(
            ProductConfigActivationCommand(uuid4(), 999, admin.id, "Unknown target.")
        )

    second = replace(candidate, config_version=2, interaction_alert_window_days=8)
    await service.ingest(candidate=second, actor_member_id=admin.id)
    with pytest.raises(IdempotencyConflictError):
        await service.activate(replace(first_command, target_config_version=2))
    faulting = ProductConfigService(
        lambda: database.unit_of_work(after_product_config_pointer_switched=injected_failure)
    )
    with pytest.raises(RuntimeError, match="Injected"):
        await faulting.activate(
            ProductConfigActivationCommand(uuid4(), 2, admin.id, "Faulted activation.")
        )
    active = await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(candidate_path=None, actor_member_id=None, activation_command_id=None)
    assert active.version == 1
    assert await count(database, LevelBackfillRunModel) == 1
    await database.dispose()


async def test_concurrent_first_activation_serializes_different_targets(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=255, role=MemberRole.ADMINISTRATOR)
    candidate = load_product_config_candidate(CONFIG_PATH)
    service = ProductConfigService(database.unit_of_work)
    first_version = await service.ingest(candidate=candidate, actor_member_id=admin.id)
    second_version = await service.ingest(
        candidate=replace(candidate, config_version=2, interaction_alert_threshold=4),
        actor_member_id=admin.id,
    )

    results = await asyncio.wait_for(
        asyncio.gather(
            service.activate(
                ProductConfigActivationCommand(uuid4(), 1, admin.id, "Concurrent target 1.")
            ),
            service.activate(
                ProductConfigActivationCommand(uuid4(), 2, admin.id, "Concurrent target 2.")
            ),
        ),
        timeout=10,
    )
    assert {result.target_config_id for result in results} == {
        first_version.id,
        second_version.id,
    }
    assert await count(database, ProductConfigActivationModel) == 2
    assert await count(database, ActiveProductConfigModel) == 1
    await database.dispose()


async def test_admin_experience_correction_authorization_boundary_and_retry(
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=253, role=MemberRole.ADMINISTRATOR)
    moderator = await add_member(database, telegram_user_id=254, role=MemberRole.MODERATOR)
    inactive_admin = await add_member(
        database,
        telegram_user_id=255,
        role=MemberRole.ADMINISTRATOR,
        status=MemberStatus.PAUSED,
    )
    target = await add_member(database, telegram_user_id=256)
    await prepare_config(database, admin.id)
    command = admin_adjustment(
        member_id=target.id,
        credit_delta=0,
        experience_delta=15,
        idempotency_key="experience-correction",
        context=AdministrativeContext(admin.id, "Restore missed experience."),
    )
    service = EconomyService(database.unit_of_work)
    first = await service.apply_one(command)
    retry = await service.apply_one(command)
    assert retry.transaction_id == first.transaction_id
    assert retry.replayed
    for actor in (moderator, inactive_admin):
        with pytest.raises(AuthorizationError):
            await service.apply_one(
                replace(
                    command,
                    idempotency_key=f"unauthorized:{actor.telegram_user_id}",
                    actor_member_id=actor.id,
                )
            )
    with pytest.raises(InsufficientBalanceError):
        await service.apply_one(
            replace(
                command,
                idempotency_key="experience-below-zero",
                experience_delta=-16,
            )
        )
    resolved = await EconomyQueryService(database.unit_of_work).level(target_member_id=target.id)
    assert resolved.level_number == 2
    assert await count(database, AccountTransactionModel) == 1
    assert await count(database, AuditEventModel) == 3
    await database.dispose()


async def test_bootstrap_and_standalone_ingest_share_one_gate(
    database_url: str, tmp_path: Path
) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=257, role=MemberRole.ADMINISTRATOR)
    candidate = load_product_config_candidate(CONFIG_PATH)
    coordinator = ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    )
    service = ProductConfigService(database.unit_of_work)

    active, ingested = await asyncio.wait_for(
        asyncio.gather(
            coordinator.prepare(
                candidate_path=CONFIG_PATH,
                actor_member_id=admin.id,
                activation_command_id=uuid4(),
                reason="Concurrent bootstrap.",
            ),
            service.ingest(candidate=candidate, actor_member_id=admin.id),
        ),
        timeout=10,
    )
    assert active.id == ingested.id
    assert await count(database, ProductConfigVersionModel) == 1
    assert await count(database, ActiveProductConfigModel) == 1

    second_candidate = replace(
        candidate,
        config_version=2,
        interaction_alert_threshold=4,
        maximum_active_assignments=3,
        assignment_policy_in_payload=True,
    )
    second_path = tmp_path / "product-config.v2.json"
    second_path.write_text(
        json.dumps(second_candidate.payload(), ensure_ascii=False), encoding="utf-8"
    )
    await asyncio.wait_for(
        asyncio.gather(
            coordinator.prepare(
                candidate_path=second_path,
                actor_member_id=admin.id,
                activation_command_id=uuid4(),
                reason="Concurrent second bootstrap.",
            ),
            service.activate(
                ProductConfigActivationCommand(
                    uuid4(), 1, admin.id, "Concurrent standalone activation."
                )
            ),
        ),
        timeout=10,
    )
    assert await count(database, ProductConfigVersionModel) == 2
    assert await count(database, ProductConfigActivationModel) == 3
    assert await count(database, ActiveProductConfigModel) == 1
    await database.dispose()


async def test_query_authorization_matrix(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=256, role=MemberRole.ADMINISTRATOR)
    member = await add_member(database, telegram_user_id=257)
    moderator = await add_member(database, telegram_user_id=258, role=MemberRole.MODERATOR)
    inactive_admin = await add_member(
        database,
        telegram_user_id=259,
        role=MemberRole.ADMINISTRATOR,
        status=MemberStatus.PAUSED,
    )
    queries = EconomyQueryService(database.unit_of_work)

    assert not (
        await queries.history(telegram_user_id=member.telegram_user_id, target_member_id=member.id)
    ).items
    assert not (
        await queries.history(
            telegram_user_id=moderator.telegram_user_id, target_member_id=moderator.id
        )
    ).items
    assert not (
        await queries.history(telegram_user_id=admin.telegram_user_id, target_member_id=member.id)
    ).items
    for actor in (member, moderator):
        with pytest.raises(AuthorizationError):
            await queries.history(
                telegram_user_id=actor.telegram_user_id, target_member_id=admin.id
            )
    with pytest.raises(AuthorizationError):
        await queries.history(
            telegram_user_id=inactive_admin.telegram_user_id,
            target_member_id=inactive_admin.id,
        )
    with pytest.raises(AuthorizationError):
        await queries.reconcile(actor_member_id=inactive_admin.id)
    with pytest.raises(AuthorizationError):
        await queries.history(telegram_user_id=999_999, target_member_id=member.id)
    assert await queries.reconcile(actor_member_id=admin.id) == ()
    await database.dispose()


async def test_bootstrap_contract_and_restart_persistence(
    database_url: str, tmp_path: Path
) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=260, role=MemberRole.ADMINISTRATOR)
    member = await add_member(database, telegram_user_id=261)
    inactive_admin = await add_member(
        database,
        telegram_user_id=262,
        role=MemberRole.ADMINISTRATOR,
        status=MemberStatus.PAUSED,
    )
    coordinator = ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    )
    with pytest.raises(ProductConfigError, match="first bootstrap"):
        await coordinator.prepare(
            candidate_path=None, actor_member_id=None, activation_command_id=None
        )
    with pytest.raises(ProductConfigError, match="stable actor"):
        await coordinator.prepare(
            candidate_path=CONFIG_PATH,
            actor_member_id=None,
            activation_command_id=None,
        )
    for actor in (member, inactive_admin):
        with pytest.raises(AuthorizationError):
            await coordinator.prepare(
                candidate_path=CONFIG_PATH,
                actor_member_id=actor.id,
                activation_command_id=uuid4(),
            )
    command_id = uuid4()
    active = await coordinator.prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin.id,
        activation_command_id=command_id,
    )
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ProductConfigError):
        await coordinator.prepare(
            candidate_path=invalid_path,
            actor_member_id=admin.id,
            activation_command_id=uuid4(),
        )
    await EconomyService(database.unit_of_work).apply_one(starting_grant(member.id))
    await database.dispose()

    restarted = Database(database_url)
    restored = await ProductConfigBootstrapCoordinator(
        restarted.unit_of_work, load_product_config_candidate
    ).prepare(candidate_path=None, actor_member_id=None, activation_command_id=None)
    replay = await EconomyService(restarted.unit_of_work).apply_one(starting_grant(member.id))
    history = await EconomyQueryService(restarted.unit_of_work).history(
        telegram_user_id=member.telegram_user_id, target_member_id=member.id
    )
    assert restored == active
    assert replay.replayed
    assert len(history.items) == 1
    await restarted.dispose()


async def test_history_cursor_handles_equal_timestamps_without_gaps(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=270, role=MemberRole.ADMINISTRATOR)
    member = await add_member(database, telegram_user_id=271)
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add_all(
            AccountTransactionModel(
                id=uuid4(),
                member_id=member.id,
                credit_delta=1,
                experience_delta=0,
                transaction_type=TransactionType.ADMIN_ADJUSTMENT.value,
                idempotency_key=f"page:{index}",
                payload_hash=f"hash:{index}",
                created_by_member_id=admin.id,
                reason="Pagination fixture.",
                created_at=created_at,
            )
            for index in range(7)
        )
        persisted = await session.get(MemberModel, member.id)
        assert persisted is not None
        persisted.credit_balance_cached = Decimal(7)
    queries = EconomyQueryService(database.unit_of_work)
    transaction_ids: list[UUID] = []
    cursor = None
    while True:
        page = await queries.history(
            telegram_user_id=member.telegram_user_id,
            target_member_id=member.id,
            limit=3,
            cursor=cursor,
        )
        transaction_ids.extend(item.transaction_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(transaction_ids) == len(set(transaction_ids)) == 7
    assert transaction_ids == sorted(transaction_ids, reverse=True)
    await database.dispose()


async def test_public_uow_composition_commits_or_rolls_back_as_one_unit(
    database_url: str,
) -> None:
    database = Database(database_url)
    first = await add_member(database, telegram_user_id=280)
    second = await add_member(database, telegram_user_id=281)
    third = await add_member(database, telegram_user_id=282)
    commands = (starting_grant(first.id), starting_grant(second.id))

    with pytest.raises(RuntimeError, match="Injected"):
        await apply_faulty_composition(database, commands)
    assert await count(database, AccountTransactionModel) == 0
    assert await count(database, AuditEventModel) == 0

    with pytest.raises(EconomyError, match="must not be empty"):
        await apply_composed_batch(database, marker_id="empty", commands=())
    assert await count(database, AccountTransactionModel) == 0
    assert await count(database, AuditEventModel) == 0

    async with database.unit_of_work() as unit_of_work:
        await unit_of_work.append_audit_event(
            actor_member_id=None,
            action="task_like_marker",
            entity_type="task_like",
            entity_id="commit",
            reason="Composition commit.",
        )
        created = await unit_of_work.economy.apply_batch(commands)
        await unit_of_work.commit()
    async with database.unit_of_work() as unit_of_work:
        replay = await unit_of_work.economy.apply_batch(tuple(reversed(commands)))
        await unit_of_work.commit()
    assert {item.transaction_id for item in created} == {item.transaction_id for item in replay}
    assert all(item.replayed for item in replay)

    with pytest.raises(IdempotencyConflictError, match="mix"):
        await apply_composed_batch(
            database,
            marker_id="mixed",
            commands=(commands[0], starting_grant(third.id)),
        )
    assert await count(database, AccountTransactionModel) == 2
    assert await count(database, AuditEventModel) == 1

    first_batch = (
        refund_reward(member_id=first.id, amount=1, idempotency_key="composed:a:first"),
        refund_reward(member_id=second.id, amount=1, idempotency_key="composed:a:second"),
    )
    second_batch = (
        refund_reward(member_id=second.id, amount=1, idempotency_key="composed:b:second"),
        refund_reward(member_id=first.id, amount=1, idempotency_key="composed:b:first"),
    )
    await asyncio.wait_for(
        asyncio.gather(
            apply_composed_batch(database, marker_id="concurrent-a", commands=first_batch),
            apply_composed_batch(database, marker_id="concurrent-b", commands=second_batch),
        ),
        timeout=10,
    )
    assert await count(database, AccountTransactionModel) == 6
    assert await count(database, AuditEventModel) == 3
    await database.dispose()


async def test_activation_and_economy_reverse_member_order_do_not_deadlock(
    database_url: str,
) -> None:
    database = Database(database_url)
    admin = await add_member(
        database,
        telegram_user_id=290,
        role=MemberRole.ADMINISTRATOR,
        member_id=UUID(int=100),
    )
    first = await add_member(database, telegram_user_id=291, member_id=UUID(int=50))
    second = await add_member(database, telegram_user_id=292, member_id=UUID(int=150))
    await prepare_config(database, admin.id)
    economy = EconomyService(database.unit_of_work)
    await economy.apply_one(
        admin_adjustment(
            member_id=first.id,
            credit_delta=0,
            experience_delta=7,
            idempotency_key="stale-cache:fixture",
            context=AdministrativeContext(admin.id, "Stale cache fixture."),
        )
    )
    base_candidate = load_product_config_candidate(CONFIG_PATH)
    faster_second_level = replace(
        base_candidate.levels[1],
        experience_required=5,
        display_name="Быстрый вклад",
    )
    candidate = replace(
        base_candidate,
        config_version=2,
        levels=(base_candidate.levels[0], faster_second_level, *base_candidate.levels[2:]),
    )
    config_service = ProductConfigService(database.unit_of_work)
    await config_service.ingest(candidate=candidate, actor_member_id=admin.id)
    queries = EconomyQueryService(database.unit_of_work)

    _, _, observed = await asyncio.wait_for(
        asyncio.gather(
            config_service.activate(
                ProductConfigActivationCommand(uuid4(), 2, admin.id, "Concurrent activation.")
            ),
            economy.apply_batch(
                (
                    earn_reward(
                        member_id=second.id, amount=4, idempotency_key="reverse-order:second"
                    ),
                    earn_reward(
                        member_id=first.id, amount=1, idempotency_key="reverse-order:first"
                    ),
                )
            ),
            queries.level(target_member_id=first.id),
        ),
        timeout=10,
    )
    active = await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(candidate_path=None, actor_member_id=None, activation_command_id=None)
    assert active.version == 2
    assert (observed.config_version, observed.level_number) in {(1, 1), (2, 2)}
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        first_persisted = await session.get(MemberModel, first.id)
        second_persisted = await session.get(MemberModel, second.id)
    assert first_persisted is not None
    assert second_persisted is not None
    assert first_persisted.experience_total_cached == 8
    assert first_persisted.level_number == 2
    assert first_persisted.level_config_version_id == active.id
    assert second_persisted.experience_total_cached == 4
    assert second_persisted.level_number == 1
    assert second_persisted.level_config_version_id == active.id
    assert await count(database, AccountTransactionModel) == 3
    assert await count(database, LevelBackfillRunModel) == 2
    await database.dispose()


async def test_config_history_and_pointer_are_immutable(database_url: str) -> None:
    database = Database(database_url)
    admin = await add_member(database, telegram_user_id=300, role=MemberRole.ADMINISTRATOR)
    await prepare_config(database, admin.id)
    targets = (
        ("product_config_versions", "version = 999"),
        ("levels", "display_name = 'Changed'"),
        ("product_config_activations", "reason = 'Changed'"),
        ("level_backfill_runs", "outcome_code = 'Changed'"),
    )
    for table, assignment in targets:
        await assert_database_error(database, f"UPDATE {table} SET {assignment}", {})  # noqa: S608
        await assert_database_error(database, f"DELETE FROM {table}", {})  # noqa: S608
    await assert_database_error(database, "DELETE FROM active_product_config", {})
    await assert_database_error(
        database, "UPDATE active_product_config SET singleton_key = false", {}
    )
    await database.dispose()
