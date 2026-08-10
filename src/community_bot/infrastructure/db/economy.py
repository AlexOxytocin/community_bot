"""PostgreSQL persistence for the immutable economy and product configuration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select, text

from community_bot.application.economy import (
    ActiveProductConfig,
    LedgerHistoryCursor,
    LedgerHistoryItem,
    LedgerHistoryPage,
    ProductConfigActivationCommand,
    ProductConfigActivationResult,
    ProductConfigVersion,
    ReconciliationMismatch,
)
from community_bot.domain.economy import (
    CachedLevel,
    EconomyCommand,
    EconomyError,
    EconomyMutationResult,
    IdempotencyConflictError,
    InsufficientBalanceError,
    LevelDefinition,
    ProductConfigCandidate,
    ProductConfigError,
    ResolvedLevel,
    ReversalCommand,
    TransactionType,
    economy_payload_hash,
    normalize_economy_command,
    resolve_level,
    validate_economy_command,
)
from community_bot.domain.members import AuthorizationError, Member, MemberRole, MemberStatus
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    ActiveProductConfigModel,
    AuditEventModel,
    LevelBackfillRunModel,
    LevelModel,
    MemberModel,
    ProductConfigActivationModel,
    ProductConfigVersionModel,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from community_bot.domain.economy import EconomyMutationCommand

_CONFIG_GATE = "product_config_mutation"


@dataclass(frozen=True, slots=True)
class _ActiveConfigSnapshot:
    config: ActiveProductConfig
    model: ProductConfigVersionModel


@dataclass(frozen=True, slots=True)
class _StagedEconomyBatch:
    results: tuple[EconomyMutationResult, ...]
    totals: dict[UUID, tuple[int, int]]
    experience_changed: set[UUID]
    persisted: tuple[tuple[EconomyCommand, UUID], ...]


class SqlAlchemyEconomyMutation:
    """Apply atomic idempotent economy batches in one caller-owned session."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        after_ledger_flushed: Callable[[], None] | None = None,
        after_cache_flushed: Callable[[], None] | None = None,
    ) -> None:
        """Bind the adapter to an open transaction."""
        self._session = session
        self._after_ledger_flushed = after_ledger_flushed
        self._after_cache_flushed = after_cache_flushed

    async def apply_one(self, command: EconomyMutationCommand) -> EconomyMutationResult:
        """Apply one command through the batch protocol."""
        return (await self.apply_batch((command,)))[0]

    async def apply_batch(
        self, commands: Sequence[EconomyMutationCommand]
    ) -> tuple[EconomyMutationResult, ...]:
        """Apply an all-new batch or replay an all-stored batch atomically."""
        prepared = await self.prepare_batch(commands)
        return await prepared.apply()

    async def prepare_batch(
        self,
        commands: Sequence[EconomyMutationCommand],
        *,
        additional_member_ids: Sequence[UUID] = (),
    ) -> _SqlAlchemyPreparedEconomyBatch:
        """Acquire all economy gates and member locks before any ledger effect."""
        if not commands:
            message = "Economy batch must not be empty."
            raise EconomyError(message)
        resolved = await self._resolve_commands(commands)
        keys = [command.idempotency_key for command in resolved]
        if len(keys) != len(set(keys)):
            message = "An economy batch must contain unique idempotency keys."
            raise IdempotencyConflictError(message)

        await self._lock_idempotency_keys(keys)
        stored = await self._stored_by_key(keys)
        replayed = _replay_batch(resolved, stored)
        member_ids = {
            member_id
            for command in resolved
            for member_id in (command.member_id, command.actor_member_id)
            if member_id is not None
        }
        member_ids.update(additional_member_ids)
        members = await _lock_member_models(self._session, member_ids)
        if replayed is None:
            await self._lock_and_validate_reversal_sources(resolved)
            _authorize_administrative_commands(resolved, members)
        return _SqlAlchemyPreparedEconomyBatch(
            session=self._session,
            commands=resolved,
            stored=stored,
            member_models=members,
            after_ledger_flushed=self._after_ledger_flushed,
            after_cache_flushed=self._after_cache_flushed,
        )

    async def _resolve_commands(
        self, commands: Sequence[EconomyMutationCommand]
    ) -> tuple[EconomyCommand, ...]:
        source_ids = {
            command.reversed_transaction_id
            for command in commands
            if isinstance(command, ReversalCommand)
        }
        sources = await _transactions_by_id(self._session, source_ids)
        resolved: list[EconomyCommand] = []
        for command in commands:
            if isinstance(command, ReversalCommand):
                source = sources.get(command.reversed_transaction_id)
                if source is None:
                    message = "Reversal source transaction does not exist."
                    raise LookupError(message)
                if source.transaction_type == TransactionType.FRAUD_REVERSAL.value:
                    message = "A reversal cannot reverse another reversal."
                    raise IdempotencyConflictError(message)
                normalized = EconomyCommand(
                    transaction_type=TransactionType.FRAUD_REVERSAL,
                    member_id=source.member_id,
                    idempotency_key=command.idempotency_key,
                    credit_delta=-source.credit_delta,
                    experience_delta=-source.experience_delta,
                    actor_member_id=command.actor_member_id,
                    reason=command.reason,
                    comment=command.comment,
                    reversed_transaction_id=source.id,
                )
            else:
                normalized = command
            validate_economy_command(normalized)
            resolved.append(normalize_economy_command(normalized))
        return tuple(resolved)

    async def _lock_idempotency_keys(self, keys: Sequence[str]) -> None:
        identities: list[tuple[int, str]] = []
        for key in keys:
            lock_id = await self._session.scalar(
                text("SELECT hashtextextended(:key, 0)"), {"key": key}
            )
            if not isinstance(lock_id, int):
                message = "PostgreSQL did not return an idempotency lock identity."
                raise TypeError(message)
            identities.append((lock_id, key))
        for lock_id in sorted({identity[0] for identity in identities}):
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id}
            )

    async def _stored_by_key(self, keys: Sequence[str]) -> dict[str, AccountTransactionModel]:
        models = (
            await self._session.scalars(
                select(AccountTransactionModel).where(
                    AccountTransactionModel.idempotency_key.in_(keys)
                )
            )
        ).all()
        return {model.idempotency_key: model for model in models}

    async def _lock_and_validate_reversal_sources(self, commands: Sequence[EconomyCommand]) -> None:
        requested_source_ids = [
            command.reversed_transaction_id
            for command in commands
            if command.reversed_transaction_id is not None
        ]
        if len(requested_source_ids) != len(set(requested_source_ids)):
            message = "One batch cannot reverse the same source more than once."
            raise IdempotencyConflictError(message)
        source_ids = sorted(requested_source_ids, key=str)
        if not source_ids:
            return
        locked = (
            await self._session.scalars(
                select(AccountTransactionModel)
                .where(AccountTransactionModel.id.in_(source_ids))
                .order_by(AccountTransactionModel.id)
                .with_for_update()
            )
        ).all()
        sources = {model.id: model for model in locked}
        if len(sources) != len(source_ids):
            message = "One or more reversal sources do not exist."
            raise LookupError(message)
        already_reversed = await self._session.scalar(
            select(AccountTransactionModel.id).where(
                AccountTransactionModel.reversed_transaction_id.in_(source_ids)
            )
        )
        if already_reversed is not None:
            message = "A source transaction can be reversed exactly once."
            raise IdempotencyConflictError(message)
        for command in commands:
            if command.reversed_transaction_id is None:
                continue
            source = sources[command.reversed_transaction_id]
            if (
                command.member_id != source.member_id
                or command.credit_delta != -source.credit_delta
                or command.experience_delta != -source.experience_delta
                or source.transaction_type == TransactionType.FRAUD_REVERSAL.value
            ):
                message = "Reversal no longer matches its immutable source."
                raise IdempotencyConflictError(message)


def _stage_economy_batch(
    session: AsyncSession,
    commands: Sequence[EconomyCommand],
    members: dict[UUID, MemberModel],
) -> _StagedEconomyBatch:
    results: list[EconomyMutationResult] = []
    totals: dict[UUID, tuple[int, int]] = {}
    experience_changed: set[UUID] = set()
    persisted: list[tuple[EconomyCommand, UUID]] = []
    for command in commands:
        member = members[command.member_id]
        current_credit, current_experience = totals.get(
            command.member_id,
            (member.credit_balance_cached, member.experience_total_cached),
        )
        credit_total = current_credit + command.credit_delta
        experience_total = current_experience + command.experience_delta
        if credit_total < 0 or experience_total < 0:
            message = "Economy mutation would make a cached total negative."
            raise InsufficientBalanceError(message)
        totals[command.member_id] = (credit_total, experience_total)
        if command.experience_delta:
            experience_changed.add(command.member_id)

        transaction_id = uuid.uuid4()
        session.add(_transaction_model(command, transaction_id))
        persisted.append((command, transaction_id))
        results.append(
            EconomyMutationResult(
                transaction_id=transaction_id,
                member_id=command.member_id,
                transaction_type=command.transaction_type,
                credit_delta=command.credit_delta,
                experience_delta=command.experience_delta,
                replayed=False,
            )
        )
    return _StagedEconomyBatch(
        results=tuple(results),
        totals=totals,
        experience_changed=experience_changed,
        persisted=tuple(persisted),
    )


def _apply_member_caches(
    staged: _StagedEconomyBatch,
    members: dict[UUID, MemberModel],
    active: _ActiveConfigSnapshot | None,
) -> None:
    for member_id, (credit_total, experience_total) in staged.totals.items():
        member = members[member_id]
        member.credit_balance_cached = credit_total
        member.experience_total_cached = experience_total
        if active is not None and member_id in staged.experience_changed:
            level = resolve_level(
                experience_total=experience_total,
                config_id=active.config.id,
                config_version=active.config.version,
                levels=active.config.levels,
                cache=CachedLevel(
                    level_number=member.level_number,
                    config_id=member.level_config_version_id,
                )
                if member.level_config_version_id is not None
                else None,
            )
            member.level_number = level.level_number
            member.level_config_version_id = active.config.id


def _append_economy_audit(session: AsyncSession, staged: _StagedEconomyBatch) -> None:
    for command, transaction_id in staged.persisted:
        if command.transaction_type in {
            TransactionType.PENALTY,
            TransactionType.ADMIN_ADJUSTMENT,
            TransactionType.FRAUD_REVERSAL,
        }:
            session.add(_economy_audit(command, transaction_id))


def _transaction_model(command: EconomyCommand, transaction_id: UUID) -> AccountTransactionModel:
    return AccountTransactionModel(
        id=transaction_id,
        member_id=command.member_id,
        credit_delta=command.credit_delta,
        experience_delta=command.experience_delta,
        transaction_type=command.transaction_type.value,
        idempotency_key=command.idempotency_key,
        payload_hash=economy_payload_hash(command),
        created_by_member_id=command.actor_member_id,
        reason=command.reason,
        comment=command.comment,
        reversed_transaction_id=command.reversed_transaction_id,
    )


class _SqlAlchemyPreparedEconomyBatch:
    """Prepared SQLAlchemy batch retaining transaction-scoped locks."""

    def __init__(  # noqa: PLR0913 - prepared state is explicit and immutable.
        self,
        *,
        session: AsyncSession,
        commands: Sequence[EconomyCommand],
        stored: dict[str, AccountTransactionModel],
        member_models: dict[UUID, MemberModel],
        after_ledger_flushed: Callable[[], None] | None,
        after_cache_flushed: Callable[[], None] | None,
    ) -> None:
        self._session = session
        self._commands = tuple(commands)
        self._stored = stored
        self._member_models = member_models
        self._after_ledger_flushed = after_ledger_flushed
        self._after_cache_flushed = after_cache_flushed
        self._applied: tuple[EconomyMutationResult, ...] | None = None

    @property
    def members(self) -> dict[UUID, Member]:
        """Return security snapshots for every member in the lock scope."""
        return {
            member_id: Member(
                id=model.id,
                telegram_user_id=model.telegram_user_id,
                role=MemberRole(model.role),
                status=MemberStatus(model.status),
            )
            for member_id, model in self._member_models.items()
        }

    async def apply(self) -> tuple[EconomyMutationResult, ...]:
        """Apply new rows or return stored results without releasing locks."""
        if self._applied is not None:
            return self._applied
        replayed = _replay_batch(self._commands, self._stored)
        if replayed is not None:
            self._applied = replayed
            return replayed

        active = None
        if any(command.experience_delta for command in self._commands):
            active = await _get_active_snapshot(self._session)
            if active is None:
                message = "Experience mutations require an active product configuration."
                raise ProductConfigError(message)

        staged = _stage_economy_batch(
            self._session,
            self._commands,
            self._member_models,
        )
        await self._session.flush()
        if self._after_ledger_flushed is not None:
            self._after_ledger_flushed()
        _apply_member_caches(staged, self._member_models, active)
        await self._session.flush()
        if self._after_cache_flushed is not None:
            self._after_cache_flushed()
        _append_economy_audit(self._session, staged)
        await self._session.flush()
        self._applied = staged.results
        return staged.results


async def acquire_product_config_mutation_gate(session: AsyncSession) -> None:
    """Serialize every product configuration mutation through one gate."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:gate, 0))"),
        {"gate": _CONFIG_GATE},
    )


async def get_active_product_config(session: AsyncSession) -> ActiveProductConfig | None:
    """Read the current immutable configuration and ordered levels."""
    snapshot = await _get_active_snapshot(session)
    return None if snapshot is None else snapshot.config


async def ingest_product_config_locked(
    session: AsyncSession,
    *,
    candidate: ProductConfigCandidate,
    actor_id: UUID,
) -> ProductConfigVersion:
    """Ingest one candidate after the caller acquired gate then actor row."""
    by_version = await session.scalar(
        select(ProductConfigVersionModel).where(
            ProductConfigVersionModel.version == candidate.config_version
        )
    )
    if by_version is not None:
        if by_version.content_hash != candidate.content_hash:
            message = "Product config version already exists with another payload."
            raise IdempotencyConflictError(message)
        return await _to_product_config_version(session, by_version)

    by_hash = await session.scalar(
        select(ProductConfigVersionModel).where(
            ProductConfigVersionModel.content_hash == candidate.content_hash
        )
    )
    if by_hash is not None:
        message = "The same product config payload cannot use another version."
        raise IdempotencyConflictError(message)
    latest_version = await session.scalar(select(func.max(ProductConfigVersionModel.version)))
    if latest_version is not None and candidate.config_version <= latest_version:
        message = "A new product config version must be greater than every stored version."
        raise ProductConfigError(message)

    model = ProductConfigVersionModel(
        id=uuid.uuid4(),
        version=candidate.config_version,
        schema_version=candidate.schema_version,
        content_hash=candidate.content_hash,
        payload_json=candidate.payload(),
        created_by_member_id=actor_id,
    )
    session.add(model)
    await session.flush()
    session.add_all(
        LevelModel(
            product_config_version_id=model.id,
            level_number=level.level_number,
            experience_required=level.experience_required,
            display_name=level.display_name,
            description=level.description,
            level_up_message=level.level_up_message,
            permissions_json=dict(level.permissions or {}),
        )
        for level in candidate.levels
    )
    session.add(
        AuditEventModel(
            actor_member_id=actor_id,
            action="product_config_ingested",
            entity_type="product_config_version",
            entity_id=str(model.id),
            before_json=None,
            after_json={
                "version": candidate.config_version,
                "content_hash": candidate.content_hash,
            },
            reason="Product configuration ingestion.",
        )
    )
    await session.flush()
    return _candidate_version(model, candidate)


async def activate_product_config_locked(
    session: AsyncSession,
    command: ProductConfigActivationCommand,
    *,
    after_pointer_switched: Callable[[], None] | None = None,
) -> ProductConfigActivationResult:
    """Activate a stored config after gate, member prelock, and authorization."""
    reason = command.reason.strip()
    existing = await session.scalar(
        select(ProductConfigActivationModel).where(
            ProductConfigActivationModel.activation_command_id == command.activation_command_id
        )
    )
    target = await session.scalar(
        select(ProductConfigVersionModel).where(
            ProductConfigVersionModel.version == command.target_config_version
        )
    )
    if target is None:
        message = "Target product configuration version does not exist."
        raise LookupError(message)
    if existing is not None:
        if (
            existing.product_config_version_id != target.id
            or existing.activated_by_member_id != command.actor_member_id
            or existing.reason != reason
        ):
            message = "Activation identity was reused with another payload."
            raise IdempotencyConflictError(message)
        return ProductConfigActivationResult(
            activation_id=existing.id,
            target_config_id=target.id,
            outcome_code=existing.outcome_code,
            replayed=True,
        )

    pointer = await session.get(ActiveProductConfigModel, True)
    outcome = (
        "already_active"
        if pointer is not None and pointer.product_config_version_id == target.id
        else "activated"
    )
    activation = ProductConfigActivationModel(
        id=uuid.uuid4(),
        activation_command_id=command.activation_command_id,
        product_config_version_id=target.id,
        activated_by_member_id=command.actor_member_id,
        outcome_code=outcome,
        reason=reason,
    )
    session.add(activation)
    await session.flush()

    if outcome == "activated":
        if pointer is None:
            session.add(
                ActiveProductConfigModel(
                    singleton_key=True,
                    product_config_version_id=target.id,
                    activation_id=activation.id,
                )
            )
        else:
            pointer.product_config_version_id = target.id
            pointer.activation_id = activation.id
            pointer.updated_at = func.now()
        await session.flush()
        if after_pointer_switched is not None:
            after_pointer_switched()
        levels = await _load_levels(session, target.id)
        members = (await session.scalars(select(MemberModel).order_by(MemberModel.id))).all()
        for member in members:
            resolved = resolve_level(
                experience_total=member.experience_total_cached,
                config_id=target.id,
                config_version=target.version,
                levels=levels,
            )
            member.level_number = resolved.level_number
            member.level_config_version_id = target.id
        session.add(
            LevelBackfillRunModel(
                id=uuid.uuid4(),
                activation_id=activation.id,
                product_config_version_id=target.id,
                processed_members=len(members),
                outcome_code="completed",
            )
        )

    session.add(
        AuditEventModel(
            actor_member_id=command.actor_member_id,
            action="product_config_activation_requested",
            entity_type="product_config_version",
            entity_id=str(target.id),
            before_json=None,
            after_json={"version": target.version, "outcome_code": outcome},
            reason=reason,
        )
    )
    await session.flush()
    return ProductConfigActivationResult(
        activation_id=activation.id,
        target_config_id=target.id,
        outcome_code=outcome,
        replayed=False,
    )


async def read_ledger_history(
    session: AsyncSession,
    *,
    member_id: UUID,
    limit: int,
    cursor: LedgerHistoryCursor | None,
) -> LedgerHistoryPage:
    """Read stable descending ledger history with a keyset cursor."""
    statement = select(AccountTransactionModel).where(
        AccountTransactionModel.member_id == member_id
    )
    if cursor is not None:
        statement = statement.where(
            (AccountTransactionModel.created_at < cursor.created_at)
            | (
                (AccountTransactionModel.created_at == cursor.created_at)
                & (AccountTransactionModel.id < cursor.transaction_id)
            )
        )
    models = (
        await session.scalars(
            statement.order_by(
                AccountTransactionModel.created_at.desc(), AccountTransactionModel.id.desc()
            ).limit(limit + 1)
        )
    ).all()
    page_models = models[:limit]
    items = tuple(_history_item(model) for model in page_models)
    next_cursor = None
    if len(models) > limit and page_models:
        last = page_models[-1]
        next_cursor = LedgerHistoryCursor(created_at=last.created_at, transaction_id=last.id)
    return LedgerHistoryPage(items=items, next_cursor=next_cursor)


async def reconcile_economy(session: AsyncSession) -> tuple[ReconciliationMismatch, ...]:
    """Compare every cache with immutable ledger aggregates."""
    aggregate = (
        select(
            AccountTransactionModel.member_id.label("member_id"),
            func.sum(AccountTransactionModel.credit_delta).label("credit_total"),
            func.sum(AccountTransactionModel.experience_delta).label("experience_total"),
        )
        .group_by(AccountTransactionModel.member_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                MemberModel.id,
                MemberModel.credit_balance_cached,
                MemberModel.experience_total_cached,
                func.coalesce(aggregate.c.credit_total, 0),
                func.coalesce(aggregate.c.experience_total, 0),
            )
            .outerjoin(aggregate, aggregate.c.member_id == MemberModel.id)
            .where(
                (MemberModel.credit_balance_cached != func.coalesce(aggregate.c.credit_total, 0))
                | (
                    MemberModel.experience_total_cached
                    != func.coalesce(aggregate.c.experience_total, 0)
                )
            )
            .order_by(MemberModel.id)
        )
    ).all()
    return tuple(
        ReconciliationMismatch(
            member_id=row[0],
            actual_credit_balance=row[1],
            actual_experience_total=row[2],
            expected_credit_balance=row[3],
            expected_experience_total=row[4],
        )
        for row in rows
    )


async def resolve_member_level(session: AsyncSession, member_id: UUID) -> ResolvedLevel:
    """Resolve a member against the exact active config, bypassing stale cache."""
    member = await session.get(MemberModel, member_id)
    if member is None:
        message = "Member record does not exist."
        raise LookupError(message)
    active = await _get_active_snapshot(session)
    if active is None:
        message = "No active product configuration exists."
        raise ProductConfigError(message)
    return resolve_level(
        experience_total=member.experience_total_cached,
        config_id=active.config.id,
        config_version=active.config.version,
        levels=active.config.levels,
        cache=CachedLevel(
            level_number=member.level_number,
            config_id=member.level_config_version_id,
        )
        if member.level_config_version_id is not None
        else None,
    )


async def _get_active_snapshot(session: AsyncSession) -> _ActiveConfigSnapshot | None:
    pointer = await session.get(ActiveProductConfigModel, True)
    if pointer is None:
        return None
    model = await session.get(ProductConfigVersionModel, pointer.product_config_version_id)
    if model is None:
        message = "Active product configuration points to a missing version."
        raise ProductConfigError(message)
    levels = await _load_levels(session, model.id)
    return _ActiveConfigSnapshot(
        config=ActiveProductConfig(
            id=model.id,
            version=model.version,
            content_hash=model.content_hash,
            levels=levels,
        ),
        model=model,
    )


async def _load_levels(session: AsyncSession, config_id: UUID) -> tuple[LevelDefinition, ...]:
    models = (
        await session.scalars(
            select(LevelModel)
            .where(LevelModel.product_config_version_id == config_id)
            .order_by(LevelModel.level_number)
        )
    ).all()
    return tuple(
        LevelDefinition(
            level_number=model.level_number,
            experience_required=model.experience_required,
            display_name=model.display_name,
            description=model.description,
            level_up_message=model.level_up_message,
            permissions=model.permissions_json,
        )
        for model in models
    )


async def _to_product_config_version(
    session: AsyncSession, model: ProductConfigVersionModel
) -> ProductConfigVersion:
    return ProductConfigVersion(
        id=model.id,
        version=model.version,
        content_hash=model.content_hash,
        levels=await _load_levels(session, model.id),
    )


def _candidate_version(
    model: ProductConfigVersionModel, candidate: ProductConfigCandidate
) -> ProductConfigVersion:
    return ProductConfigVersion(
        id=model.id,
        version=model.version,
        content_hash=model.content_hash,
        levels=candidate.levels,
    )


async def _lock_member_models(
    session: AsyncSession, member_ids: set[UUID]
) -> dict[UUID, MemberModel]:
    ordered = sorted(member_ids, key=str)
    models = (
        await session.scalars(
            select(MemberModel)
            .where(MemberModel.id.in_(ordered))
            .order_by(MemberModel.id)
            .with_for_update()
        )
    ).all()
    by_id = {model.id: model for model in models}
    if len(by_id) != len(ordered):
        message = "One or more member records do not exist."
        raise LookupError(message)
    return by_id


async def _transactions_by_id(
    session: AsyncSession, transaction_ids: set[UUID]
) -> dict[UUID, AccountTransactionModel]:
    if not transaction_ids:
        return {}
    models = (
        await session.scalars(
            select(AccountTransactionModel).where(AccountTransactionModel.id.in_(transaction_ids))
        )
    ).all()
    return {model.id: model for model in models}


def _authorize_administrative_commands(
    commands: Sequence[EconomyCommand], members: dict[UUID, MemberModel]
) -> None:
    for command in commands:
        if command.actor_member_id is None:
            continue
        actor = members[command.actor_member_id]
        if (
            actor.status != MemberStatus.ACTIVE.value
            or actor.role != MemberRole.ADMINISTRATOR.value
        ):
            message = "An active administrator is required for this economy mutation."
            raise AuthorizationError(message)


def _replay_batch(
    commands: Sequence[EconomyCommand], stored: dict[str, AccountTransactionModel]
) -> tuple[EconomyMutationResult, ...] | None:
    if not stored:
        return None
    if len(stored) != len(commands):
        message = "An economy batch cannot mix stored and new commands."
        raise IdempotencyConflictError(message)
    return tuple(_stored_result(stored[command.idempotency_key], command) for command in commands)


def _stored_result(
    model: AccountTransactionModel, command: EconomyCommand
) -> EconomyMutationResult:
    if model.payload_hash != economy_payload_hash(command):
        message = "Idempotency key was reused with another economy payload."
        raise IdempotencyConflictError(message)
    return EconomyMutationResult(
        transaction_id=model.id,
        member_id=model.member_id,
        transaction_type=TransactionType(model.transaction_type),
        credit_delta=model.credit_delta,
        experience_delta=model.experience_delta,
        replayed=True,
    )


def _economy_audit(command: EconomyCommand, transaction_id: UUID) -> AuditEventModel:
    return AuditEventModel(
        actor_member_id=command.actor_member_id,
        action="economy_administrative_mutation",
        entity_type="account_transaction",
        entity_id=str(transaction_id),
        before_json=None,
        after_json={
            "member_id": str(command.member_id),
            "transaction_type": command.transaction_type.value,
            "credit_delta": command.credit_delta,
            "experience_delta": command.experience_delta,
            "reversed_transaction_id": (
                None
                if command.reversed_transaction_id is None
                else str(command.reversed_transaction_id)
            ),
        },
        reason=command.reason,
    )


def _history_item(model: AccountTransactionModel) -> LedgerHistoryItem:
    return LedgerHistoryItem(
        transaction_id=model.id,
        member_id=model.member_id,
        transaction_type=model.transaction_type,
        credit_delta=model.credit_delta,
        experience_delta=model.experience_delta,
        comment=model.comment,
        created_at=model.created_at,
    )
