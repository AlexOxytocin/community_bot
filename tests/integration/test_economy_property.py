from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.economy import EconomyService, ProductConfigBootstrapCoordinator
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.domain.economy import (
    AdministrativeContext,
    EconomyError,
    EconomyMutationResult,
    ReversalCommand,
    TransactionType,
    admin_adjustment,
    apply_penalty,
    earn_reward,
    refund_reward,
    reserve_reward,
    starting_grant,
)
from community_bot.domain.members import AuthorizationError, MemberRole, MemberStatus
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AuditEventModel,
    MemberModel,
)

if TYPE_CHECKING:
    from uuid import UUID

    from community_bot.domain.economy import EconomyMutationCommand

pytestmark = pytest.mark.integration

CONFIG_PATH = Path(__file__).parents[2] / "config" / "product-config.v1.json"


@dataclass(frozen=True, slots=True)
class EconomySnapshot:
    """Persisted economy state observed after one attempted command."""

    credit_cache: int
    experience_cache: int
    credit_sum: int
    experience_sum: int
    ledger_count: int
    audit_count: int


@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
@given(st.lists(st.integers(min_value=-100, max_value=100), min_size=1, max_size=18))
def test_generated_committed_sequences_preserve_ledger_and_cache_invariants(
    database_url: str, operations: list[int]
) -> None:
    asyncio.run(_run_generated_sequence(database_url, operations))


async def _run_generated_sequence(database_url: str, operations: list[int]) -> None:
    database = Database(database_url)
    admin = await _add_member(database, role=MemberRole.ADMINISTRATOR)
    member = await _add_member(database)
    await _ensure_active_config(database, admin.id)
    service = EconomyService(database.unit_of_work)
    grant = await service.apply_one(starting_grant(member.id))
    successful: list[EconomyMutationResult] = [grant]

    required_operations = [1, 2, 3, 4, 12, 6, -99]
    for index, token in enumerate([*required_operations, *operations]):
        before = await _snapshot(database, member.id)
        command = _generated_command(
            token=token,
            index=index,
            member=member,
            admin=admin,
            successful=successful,
        )
        rejected = False
        try:
            result = await service.apply_one(command)
        except (EconomyError, AuthorizationError):
            rejected = True
        else:
            if not result.replayed:
                successful.append(result)
        after = await _snapshot(database, member.id)

        if rejected:
            assert after == before
        assert after.credit_cache == after.credit_sum
        assert after.experience_cache == after.experience_sum
        assert after.credit_cache >= 0
        assert after.experience_cache >= 0
        await _assert_ordinary_operations_have_zero_experience(database, member.id)
    await database.dispose()


def _generated_command(
    *,
    token: int,
    index: int,
    member: MemberModel,
    admin: MemberModel,
    successful: list[EconomyMutationResult],
) -> EconomyMutationCommand:
    operation = abs(token) % 7
    amount = abs(token) % 10 + 1
    key = f"property:{member.id}:{index}"
    if operation == 0:
        command = starting_grant(member.id)
    elif operation == 1:
        command = reserve_reward(member_id=member.id, amount=amount, idempotency_key=key)
    elif operation == 2:
        command = refund_reward(member_id=member.id, amount=amount, idempotency_key=key)
    elif operation == 3:
        command = earn_reward(member_id=member.id, amount=amount, idempotency_key=key)
    elif operation == 4:
        command = apply_penalty(
            member_id=member.id,
            amount=amount,
            idempotency_key=key,
            context=AdministrativeContext(admin.id, "Generated penalty."),
        )
    elif operation == 5:
        sign = 1 if token >= 0 else -1
        command = admin_adjustment(
            member_id=member.id,
            credit_delta=sign * amount,
            experience_delta=sign * amount if token % 3 == 0 else 0,
            idempotency_key=key,
            context=AdministrativeContext(admin.id, "Generated adjustment."),
        )
    else:
        source = successful[abs(token) % len(successful)]
        command = ReversalCommand(
            reversed_transaction_id=source.transaction_id,
            idempotency_key=key,
            actor_member_id=admin.id,
            reason="Generated reversal.",
        )
    return command


async def _add_member(database: Database, *, role: MemberRole = MemberRole.MEMBER) -> MemberModel:
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        member = MemberModel(
            telegram_user_id=uuid4().int % (2**63 - 1),
            display_name="Property member",
            timezone="UTC",
            role=role.value,
            status=MemberStatus.ACTIVE.value,
            level_number=1,
        )
        session.add(member)
    return member


async def _ensure_active_config(database: Database, admin_id: UUID) -> None:
    async with database.unit_of_work() as unit_of_work:
        active = await unit_of_work.get_active_product_config()
    if active is not None:
        return
    await ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    ).prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=admin_id,
        activation_command_id=uuid4(),
        reason="Property test bootstrap.",
    )


async def _snapshot(database: Database, member_id: UUID) -> EconomySnapshot:
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        member = await session.get(MemberModel, member_id)
        assert member is not None
        sums = (
            await session.execute(
                select(
                    func.coalesce(func.sum(AccountTransactionModel.credit_delta), 0),
                    func.coalesce(func.sum(AccountTransactionModel.experience_delta), 0),
                    func.count(AccountTransactionModel.id),
                ).where(AccountTransactionModel.member_id == member_id)
            )
        ).one()
        audit_count = int(
            await session.scalar(select(func.count()).select_from(AuditEventModel)) or 0
        )
    return EconomySnapshot(
        credit_cache=member.credit_balance_cached,
        experience_cache=member.experience_total_cached,
        credit_sum=sums[0],
        experience_sum=sums[1],
        ledger_count=sums[2],
        audit_count=audit_count,
    )


async def _assert_ordinary_operations_have_zero_experience(
    database: Database, member_id: UUID
) -> None:
    ordinary_types = (
        TransactionType.STARTING_GRANT.value,
        TransactionType.TASK_REWARD_RESERVED.value,
        TransactionType.TASK_REWARD_REFUNDED.value,
        TransactionType.PENALTY.value,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        nonzero = await session.scalar(
            select(func.count())
            .select_from(AccountTransactionModel)
            .where(
                AccountTransactionModel.member_id == member_id,
                AccountTransactionModel.transaction_type.in_(ordinary_types),
                AccountTransactionModel.experience_delta != 0,
            )
        )
    assert nonzero == 0
