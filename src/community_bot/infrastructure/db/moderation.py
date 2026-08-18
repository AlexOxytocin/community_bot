# ruff: noqa: C901, D107, EM101, PLR0911, PLR0912, PLR0913, PLR0915, PLR2004, TRY003
"""PostgreSQL moderation state machine and effective sanction policy."""

from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from dataclasses import asdict
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, or_, select, text

from community_bot.application.moderation import (
    InteractionAlert,
    ModerationCase,
    ModerationCaseDetail,
    PaidAssignment,
    ResolutionPreview,
    ResolveCaseCommand,
    Sanction,
    SanctionCard,
)
from community_bot.domain.economy import (
    AdministrativeContext,
    EconomyMutationResult,
    ReversalCommand,
    TransactionType,
    apply_penalty,
    earn_community_reward,
    earn_partial_reward,
    earn_reward,
    refund_reward,
)
from community_bot.domain.members import Member, MemberRole, MemberStatus
from community_bot.domain.moderation import (
    AlertOutcome,
    ModerationError,
    ResolutionCode,
    RestrictedAction,
    SanctionType,
    resolution_effect,
    risk_signal_key,
    validate_sanction,
)
from community_bot.infrastructure.db.assignments import _cards as assignment_cards
from community_bot.infrastructure.db.economy import SqlAlchemyEconomyMutation
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    ActiveProductConfigModel,
    AssignmentModel,
    AuditEventModel,
    DisputeAppealModel,
    DisputeEvidenceModel,
    DisputeResolutionModel,
    InteractionAlertAssignmentModel,
    InteractionAlertModel,
    KarmaVoteModel,
    KarmaVoteModerationModel,
    MemberModel,
    MemberSanctionModel,
    ModerationCaseModel,
    ModerationDecisionDraftModel,
    ModerationRiskSignalModel,
    OutboxEventModel,
    ProductConfigVersionModel,
    ReliabilityEventModel,
    ReliabilityOutcomeCorrectionModel,
    SanctionEventModel,
    TaskModel,
)
from community_bot.infrastructure.db.test_runs import active_scope

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from community_bot.application.moderation import (
        ConfirmResolutionCommand,
        IssueSanctionCommand,
        ModerateKarmaCommand,
        OpenFraudCaseCommand,
        PreviewResolutionCommand,
        RequestAppealCommand,
        ReviewAlertCommand,
        RevokeSanctionCommand,
    )

_CASE_GATE = "moderation_case"
_SANCTION_GATE = "member_sanction"
_PAIR_GATE = "interaction_alert_pair"


class SqlAlchemyModerationMutation:
    """Apply moderation commands inside the caller-owned SQLAlchemy transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        after_ledger_flushed: Callable[[], None] | None = None,
        after_cache_flushed: Callable[[], None] | None = None,
    ) -> None:
        self._session = session
        self._economy = SqlAlchemyEconomyMutation(
            session,
            after_ledger_flushed=after_ledger_flushed,
            after_cache_flushed=after_cache_flushed,
        )

    async def list_cases(
        self, *, actor: Member, limit: int = 20, include_fraud_review: bool = True
    ) -> tuple[ModerationCase, ...]:
        """List current open or appealed cases without private evidence."""
        _require_staff(actor)
        scope = await active_scope(self._session, actor.id)
        test_scope = (
            TaskModel.test_run_id.is_(None) if scope is None else TaskModel.test_run_id == scope.id
        )
        statement = (
            select(ModerationCaseModel, AssignmentModel, TaskModel)
            .join(AssignmentModel, AssignmentModel.id == ModerationCaseModel.assignment_id)
            .join(TaskModel, TaskModel.id == AssignmentModel.task_id)
            .where(ModerationCaseModel.status.in_(("open", "appealed")), test_scope)
            .order_by(ModerationCaseModel.opened_at, ModerationCaseModel.id)
        )
        if not include_fraud_review:
            statement = statement.where(ModerationCaseModel.case_type != "fraud_review")
        visible = []
        rows = await self._session.stream(statement.execution_options(yield_per=max(limit, 20)))
        async for case, assignment, task in rows:
            try:
                await self._reject_conflict(
                    actor, assignment, task, case, 1 if case.status == "open" else 2
                )
            except PermissionError:
                continue
            visible.append(await self._case(case))
            if len(visible) == limit:
                break
        return tuple(visible)

    async def case_detail(self, case_id: uuid.UUID, actor: Member) -> ModerationCaseDetail:
        """Return the safe initial-dispute projection and server-owned outcomes."""
        case, assignment, task = await self._case_context(case_id, actor)
        if case.case_type != "dispute" or case.status != "open":
            raise LookupError("Moderation dispute is not awaiting an initial resolution.")
        cards = await assignment_cards(
            self._session,
            AssignmentModel.id == assignment.id,
            scope_member_id=actor.id,
            assignment_id=assignment.id,
        )
        if not cards:
            raise PermissionError("Moderation case is outside the actor test scope.")
        card = cards[0]
        return ModerationCaseDetail(
            case=await self._case(case),
            task_title=card.task_title,
            task_origin=card.task_origin,
            credit_reward_per_performer=card.task.credit_reward_per_performer,
            assignment_status=card.assignment.status.value,
            result_summary=card.result_summary,
            dispute_reason=case.reason,
            allowed_resolution_codes=self._allowed_resolution_codes(actor, task, case),
        )

    async def replay_web_resolution(self, case_id: uuid.UUID, actor: Member) -> ModerationCase:
        """Replay a web outcome only inside the actor's current safe case scope."""
        case, _assignment, _task = await self._case_context(case_id, actor)
        return await self._case(case)

    async def list_paid_assignments(self, *, limit: int = 20) -> tuple[PaidAssignment, ...]:
        """List paid assignments without exposing private result payloads."""
        rows = (
            await self._session.execute(
                select(AssignmentModel, TaskModel.title, MemberModel.display_name)
                .join(TaskModel, TaskModel.id == AssignmentModel.task_id)
                .join(MemberModel, MemberModel.id == AssignmentModel.performer_id)
                .where(AssignmentModel.status.in_(("approved", "partially_approved")))
                .order_by(AssignmentModel.accepted_at.desc(), AssignmentModel.id)
                .limit(limit)
            )
        ).all()
        return tuple(
            PaidAssignment(model.id, title, display_name, model.status)
            for model, title, display_name in rows
        )

    async def list_open_alerts(self, *, limit: int = 20) -> tuple[InteractionAlert, ...]:
        """List open alerts with only member display names and aggregate counts."""
        first = MemberModel.__table__.alias("first_member")
        second = MemberModel.__table__.alias("second_member")
        rows = (
            await self._session.execute(
                select(
                    InteractionAlertModel,
                    first.c.display_name,
                    second.c.display_name,
                )
                .join(first, first.c.id == InteractionAlertModel.first_member_id)
                .join(second, second.c.id == InteractionAlertModel.second_member_id)
                .where(InteractionAlertModel.state == "open")
                .order_by(InteractionAlertModel.opened_at, InteractionAlertModel.id)
                .limit(limit)
            )
        ).all()
        return tuple(
            InteractionAlert(
                model.id, first_name, second_name, model.interaction_count, model.threshold
            )
            for model, first_name, second_name in rows
        )

    async def list_active_sanctions(self, *, limit: int = 20) -> tuple[SanctionCard, ...]:
        """List active sanctions with their target display names."""
        rows = (
            await self._session.execute(
                select(MemberSanctionModel, MemberModel.display_name)
                .join(MemberModel, MemberModel.id == MemberSanctionModel.target_member_id)
                .where(MemberSanctionModel.state == "active")
                .order_by(MemberSanctionModel.created_at.desc(), MemberSanctionModel.id)
                .limit(limit)
            )
        ).all()
        return tuple(SanctionCard(_sanction(model), display_name) for model, display_name in rows)

    async def replay(self, outcome: str) -> object:
        """Reconstruct a committed moderation result from its receipt marker."""
        parts = outcome.split(":", maxsplit=2)
        if len(parts) != 3 or parts[0] != "moderation":
            raise ModerationError("Stored update is not a moderation outcome.")
        operation, raw_value = parts[1], parts[2]
        if operation == "preview_resolution":
            model = await self._session.get(ModerationDecisionDraftModel, uuid.UUID(raw_value))
            if model is None:
                raise LookupError("Stored moderation preview does not exist.")
            return _preview(model)
        if operation in {
            "open_fraud_case",
            "resolve_case",
            "confirm_resolution",
            "request_appeal",
        }:
            model = await self._session.get(ModerationCaseModel, uuid.UUID(raw_value))
            if model is None:
                raise LookupError("Stored moderation case does not exist.")
            return await self._case(model)
        if operation in {"issue_sanction", "revoke_sanction"}:
            model = await self._session.get(MemberSanctionModel, uuid.UUID(raw_value))
            if model is None:
                raise LookupError("Stored sanction does not exist.")
            return _sanction(model)
        return raw_value

    async def open_fraud_case(self, command: OpenFraudCaseCommand, actor: Member) -> ModerationCase:
        """Open one administrator-only case for a paid assignment."""
        _require_admin(actor)
        reason = _required(command.reason, "Fraud case reason is required.")
        payload_hash = _payload_hash(
            {
                "assignment_id": str(command.assignment_id),
                "reason": reason,
                "evidence_reference": command.evidence_reference,
            }
        )
        await _gate(self._session, _CASE_GATE, command.assignment_id)
        stored = await self._session.scalar(
            select(ModerationCaseModel).where(
                ModerationCaseModel.open_command_id == command.command_id
            )
        )
        if stored is not None:
            if (
                stored.assignment_id != command.assignment_id
                or stored.open_payload_hash != payload_hash
            ):
                raise ModerationError("Fraud case command conflicts with stored payload.")
            return await self._case(stored)
        assignment = await self._session.scalar(
            select(AssignmentModel)
            .where(AssignmentModel.id == command.assignment_id)
            .with_for_update()
        )
        if assignment is None:
            raise LookupError("Assignment does not exist.")
        if assignment.status not in {"approved", "partially_approved"}:
            raise ModerationError("Post-payment fraud requires a paid assignment.")
        active = await self._session.scalar(
            select(ModerationCaseModel).where(
                ModerationCaseModel.assignment_id == assignment.id,
                ModerationCaseModel.status.in_(("open", "resolved", "appealed")),
            )
        )
        if active is not None:
            raise ModerationError("Assignment already has an active moderation case.")
        source_rows = await self._fraud_sources(assignment.id)
        if not source_rows:
            raise ModerationError("Paid fraud case has no reversible payout.")
        prepared = await self._economy.prepare_batch(
            tuple(
                ReversalCommand(
                    reversed_transaction_id=row.id,
                    idempotency_key=f"fraud-open:{command.command_id}:validate:{row.id}",
                    actor_member_id=actor.id,
                    reason=reason,
                )
                for row in source_rows
            )
        )
        validation = await self._session.begin_nested()
        try:
            await prepared.apply()
        finally:
            await validation.rollback()
        model = ModerationCaseModel(
            id=uuid.uuid4(),
            assignment_id=assignment.id,
            case_type="fraud_review",
            status="open",
            opened_by_member_id=actor.id,
            open_command_id=command.command_id,
            open_payload_hash=payload_hash,
            reason=reason,
        )
        self._session.add(model)
        if command.evidence_reference:
            self._session.add(
                DisputeEvidenceModel(
                    case_id=model.id,
                    author_member_id=actor.id,
                    evidence_type="reference",
                    reference=command.evidence_reference.strip(),
                )
            )
        await self._audit(actor.id, "fraud_case_opened", "moderation_case", model.id, reason)
        await self._session.flush()
        return await self._case(model)

    async def resolve_case(self, command: ResolveCaseCommand, actor: Member) -> ModerationCase:
        """Apply an initial or appealed resolution atomically."""
        _require_staff(actor)
        reason = _required(command.reason, "Resolution reason is required.")
        payload_hash = _payload_hash(
            {
                "case_id": str(command.case_id),
                "expected_revision": command.expected_revision,
                "code": command.code.value,
                "reason": reason,
            }
        )
        await self._acquire_case_assignment_gate(command.case_id)
        stored = await self._session.scalar(
            select(DisputeResolutionModel).where(
                DisputeResolutionModel.command_id == command.command_id
            )
        )
        if stored is not None:
            if stored.case_id != command.case_id or stored.payload_hash != payload_hash:
                raise ModerationError("Resolution command conflicts with stored payload.")
            case = await self._session.get(ModerationCaseModel, stored.case_id)
            if case is None:
                raise LookupError("Stored moderation case does not exist.")
            return await self._case(case)
        case = await self._session.scalar(
            select(ModerationCaseModel)
            .where(ModerationCaseModel.id == command.case_id)
            .with_for_update()
        )
        if case is None:
            raise LookupError("Moderation case does not exist.")
        if command.initial_dispute_only and (case.case_type != "dispute" or case.status != "open"):
            raise ModerationError("Web moderation accepts only an initial dispute resolution.")
        if case.revision != command.expected_revision:
            raise ModerationError("Moderation case revision is stale.")
        version = 1 if case.status == "open" else 2 if case.status == "appealed" else 0
        if not version:
            raise ModerationError("Moderation case is not awaiting a resolution.")
        if version == 2 and actor.role is not MemberRole.ADMINISTRATOR:
            raise PermissionError("Only an administrator may resolve an appeal.")
        if (
            case.case_type == "fraud_review" or command.code is ResolutionCode.FRAUD
        ) and actor.role is not MemberRole.ADMINISTRATOR:
            raise PermissionError("Only an administrator may apply a fraud resolution.")
        assignment = await self._session.scalar(
            select(AssignmentModel)
            .where(AssignmentModel.id == case.assignment_id)
            .with_for_update()
        )
        if assignment is None:
            raise LookupError("Case assignment does not exist.")
        task = await self._session.get(TaskModel, assignment.task_id)
        if task is None:
            raise LookupError("Case task does not exist.")
        await self._require_test_scope(actor.id, task)
        await self._reject_conflict(actor, assignment, task, case, version)
        if (
            case.case_type == "fraud_review"
            and version == 1
            and command.code is not ResolutionCode.FRAUD
        ):
            raise ModerationError("A post-payment fraud case accepts only the fraud code.")
        effect = resolution_effect(command.code, origin=task.origin)
        previous = None
        reversal_results = ()
        if version == 2:
            previous = await self._current_resolution(case)
            source_ids = tuple(
                uuid.UUID(value) for value in previous.effect_json.get("ledger_ids", [])
            )
            reversible_source_ids = tuple(
                await self._session.scalars(
                    select(AccountTransactionModel.id).where(
                        AccountTransactionModel.id.in_(source_ids),
                        AccountTransactionModel.reversed_transaction_id.is_(None),
                    )
                )
            )
            if reversible_source_ids:
                reversal_results = await self._economy.apply_batch(
                    tuple(
                        ReversalCommand(
                            reversed_transaction_id=source_id,
                            idempotency_key=f"case:{case.id}:v2:reverse:{source_id}",
                            actor_member_id=actor.id,
                            reason=reason,
                            transaction_type=TransactionType.RESOLUTION_REVERSAL,
                        )
                        for source_id in reversible_source_ids
                    )
                )
        payout_results = await self._apply_resolution_economy(
            case=case,
            assignment=assignment,
            task=task,
            code=command.code,
            version=version,
            actor=actor,
            reason=reason,
        )
        previous_assignment_status = assignment.status
        assignment.status = effect.assignment_status
        performer_paid = any(
            result.member_id == assignment.performer_id and result.credit_delta > 0
            for result in payout_results
        )
        assignment.slot_ever_paid = assignment.slot_ever_paid or performer_paid
        assignment.terminal_command_id = command.command_id
        assignment.terminal_outcome = command.code.value
        assignment.reviewed_at = datetime.datetime.now(datetime.UTC)
        if version == 1 and case.case_type != "fraud_review":
            self._session.add(
                ReliabilityEventModel(
                    assignment_id=assignment.id,
                    event_type=effect.reliability_outcome,
                    actor_member_id=actor.id,
                    reason=reason,
                )
            )
        else:
            if previous is None and case.case_type != "fraud_review":
                raise RuntimeError("Appeal resolution lost its previous outcome.")
            self._session.add(
                ReliabilityOutcomeCorrectionModel(
                    assignment_id=assignment.id,
                    case_id=case.id,
                    resolution_version=version,
                    previous_outcome=(
                        previous_assignment_status
                        if previous is None
                        else str(previous.effect_json["reliability_outcome"])
                    ),
                    new_outcome=effect.reliability_outcome,
                    actor_member_id=actor.id,
                )
            )
        resolution = DisputeResolutionModel(
            id=uuid.uuid4(),
            case_id=case.id,
            version=version,
            code=command.code.value,
            actor_member_id=actor.id,
            command_id=command.command_id,
            payload_hash=payload_hash,
            reason=reason,
            effect_json={
                **asdict(effect),
                "ledger_ids": [str(item.transaction_id) for item in payout_results],
                "reversal_ids": [str(item.transaction_id) for item in reversal_results],
            },
            conflict_snapshot_json={"actor_id": str(actor.id), "clear": True},
        )
        self._session.add(resolution)
        await self._session.flush()
        case.current_resolution_id = resolution.id
        case.status = "resolved"
        case.resolved_at = datetime.datetime.now(datetime.UTC)
        case.revision += 1
        if effect.risk_target:
            await self._add_resolution_signal(
                case, assignment, task, command.code, effect.risk_target
            )
        self._session.add(
            OutboxEventModel(
                event_type="moderation_case_resolved",
                aggregate_type="moderation_case",
                aggregate_id=case.id,
                payload_json={"case_id": str(case.id), "code": command.code.value},
                business_key=f"moderation-case:{case.id}:resolution:{version}",
            )
        )
        await self._audit(actor.id, "moderation_case_resolved", "moderation_case", case.id, reason)
        await recompute_interaction_alert(self._session, assignment.id)
        await self._session.flush()
        return await self._case(case)

    async def preview_resolution(
        self, command: PreviewResolutionCommand, actor: Member
    ) -> ResolutionPreview:
        """Persist a restart-safe preview under the case gate."""
        _require_staff(actor)
        reason = _required(command.reason, "Resolution reason is required.")
        await self._acquire_case_assignment_gate(command.case_id)
        case = await self._session.get(ModerationCaseModel, command.case_id)
        if case is None or case.revision != command.expected_revision:
            raise ModerationError("Moderation case revision is stale.")
        if case.status not in {"open", "appealed"}:
            raise ModerationError("Moderation case is not awaiting a resolution.")
        model = ModerationDecisionDraftModel(
            id=uuid.uuid4(),
            actor_member_id=actor.id,
            case_id=case.id,
            expected_revision=case.revision,
            code=command.code.value,
            reason=reason,
            resolution_command_id=uuid.uuid5(
                uuid.NAMESPACE_URL, f"moderation-draft:{command.update_id}"
            ),
        )
        self._session.add(model)
        await self._session.flush()
        return _preview(model)

    async def confirm_resolution(
        self, command: ConfirmResolutionCommand, actor: Member
    ) -> ModerationCase:
        """Apply one pending draft and make stale callbacks harmless."""
        draft = await self._session.scalar(
            select(ModerationDecisionDraftModel)
            .where(ModerationDecisionDraftModel.id == command.draft_id)
            .with_for_update()
        )
        if draft is None or draft.actor_member_id != actor.id:
            raise PermissionError("Moderation preview belongs to another actor.")
        if draft.state == "confirmed":
            case = await self._session.get(ModerationCaseModel, draft.case_id)
            if case is None:
                raise LookupError("Confirmed preview case does not exist.")
            return await self._case(case)
        result = await self.resolve_case(
            ResolveCaseCommand(
                update_id=command.update_id,
                actor_telegram_user_id=command.actor_telegram_user_id,
                case_id=draft.case_id,
                command_id=draft.resolution_command_id,
                expected_revision=draft.expected_revision,
                code=ResolutionCode(draft.code),
                reason=draft.reason,
            ),
            actor,
        )
        draft.state = "confirmed"
        await self._session.flush()
        return result

    async def request_appeal(self, command: RequestAppealCommand, actor: Member) -> ModerationCase:
        """Append the only appeal within seven days."""
        reason = _required(command.reason, "Appeal reason is required.")
        await self._acquire_case_assignment_gate(command.case_id)
        stored = await self._session.scalar(
            select(DisputeAppealModel).where(DisputeAppealModel.command_id == command.command_id)
        )
        if stored is not None:
            if stored.case_id != command.case_id or stored.reason != reason:
                raise ModerationError("Appeal command conflicts with stored payload.")
            case = await self._session.get(ModerationCaseModel, stored.case_id)
            if case is None:
                raise LookupError("Stored appeal case does not exist.")
            return await self._case(case)
        case = await self._session.scalar(
            select(ModerationCaseModel)
            .where(ModerationCaseModel.id == command.case_id)
            .with_for_update()
        )
        if case is None or case.status != "resolved" or case.resolved_at is None:
            raise ModerationError("Only a resolved case may be appealed.")
        assignment = await self._session.get(AssignmentModel, case.assignment_id)
        task = (
            None if assignment is None else await self._session.get(TaskModel, assignment.task_id)
        )
        if assignment is None or task is None:
            raise LookupError("Appeal assignment does not exist.")
        if actor.id not in {assignment.performer_id, task.creator_id}:
            raise PermissionError("Only a case party may request an appeal.")
        now = datetime.datetime.now(datetime.UTC)
        if now > case.resolved_at + datetime.timedelta(days=7):
            raise ModerationError("Appeal deadline has passed.")
        self._session.add(
            DisputeAppealModel(
                id=uuid.uuid4(),
                case_id=case.id,
                appellant_member_id=actor.id,
                command_id=command.command_id,
                reason=reason,
            )
        )
        case.status = "appealed"
        case.revision += 1
        await self._audit(actor.id, "moderation_case_appealed", "moderation_case", case.id, reason)
        await self._session.flush()
        return await self._case(case)

    async def issue_sanction(self, command: IssueSanctionCommand, actor: Member) -> Sanction:
        """Issue a role-authorized reversible sanction."""
        _require_staff(actor)
        reason = _required(command.reason, "Sanction reason is required.")
        actions = validate_sanction(
            sanction_type=command.sanction_type,
            actions=command.restricted_actions,
            ends_at=command.ends_at,
            now=datetime.datetime.now(datetime.UTC),
        )
        if command.sanction_type is SanctionType.BAN and actor.role is not MemberRole.ADMINISTRATOR:
            raise PermissionError("Only an administrator may issue a ban.")
        if RestrictedAction.KARMA_VOTE in actions and (
            actor.role is not MemberRole.ADMINISTRATOR or "karma_review" not in actor.permissions
        ):
            raise PermissionError("Karma voting restriction requires karma_review.")
        await _gate(self._session, _SANCTION_GATE, command.target_member_id)
        stored = await self._session.scalar(
            select(MemberSanctionModel).where(MemberSanctionModel.command_id == command.command_id)
        )
        if stored is not None:
            return _sanction(stored)
        target = await self._session.scalar(
            select(MemberModel).where(MemberModel.id == command.target_member_id).with_for_update()
        )
        if target is None:
            raise LookupError("Sanction target does not exist.")
        if target.id == actor.id:
            raise PermissionError("A moderator cannot sanction themselves.")
        applied_status = None
        if command.sanction_type is SanctionType.SUSPENSION:
            applied_status = MemberStatus.SUSPENDED.value
        elif command.sanction_type is SanctionType.BAN:
            applied_status = MemberStatus.BANNED.value
        model = MemberSanctionModel(
            id=uuid.uuid4(),
            target_member_id=target.id,
            author_member_id=actor.id,
            sanction_type=command.sanction_type.value,
            restricted_actions_json=[item.value for item in actions],
            reason=reason,
            starts_at=datetime.datetime.now(datetime.UTC),
            ends_at=command.ends_at,
            previous_status=target.status if applied_status else None,
            applied_status=applied_status,
            command_id=command.command_id,
        )
        self._session.add(model)
        self._session.add(
            SanctionEventModel(
                sanction_id=model.id,
                event_type="issued",
                actor_member_id=actor.id,
                reason=reason,
                command_id=command.command_id,
            )
        )
        if applied_status:
            target.status = applied_status
        await self._audit(actor.id, "sanction_issued", "member_sanction", model.id, reason)
        await self._session.flush()
        return _sanction(model)

    async def revoke_sanction(self, command: RevokeSanctionCommand, actor: Member) -> Sanction:
        """Revoke an active sanction and safely restore status."""
        _require_staff(actor)
        reason = _required(command.reason, "Revocation reason is required.")
        stored_event = await self._session.scalar(
            select(SanctionEventModel).where(SanctionEventModel.command_id == command.command_id)
        )
        if stored_event is not None:
            model = await self._session.get(MemberSanctionModel, stored_event.sanction_id)
            if model is None:
                raise LookupError("Stored sanction does not exist.")
            return _sanction(model)
        model = await self._session.get(MemberSanctionModel, command.sanction_id)
        if model is None:
            raise LookupError("Sanction does not exist.")
        await _gate(self._session, _SANCTION_GATE, model.target_member_id)
        model = await self._session.scalar(
            select(MemberSanctionModel)
            .where(MemberSanctionModel.id == command.sanction_id)
            .with_for_update()
        )
        if model is None:
            raise LookupError("Sanction does not exist.")
        if (
            model.sanction_type == SanctionType.BAN.value
            and actor.role is not MemberRole.ADMINISTRATOR
        ):
            raise PermissionError("Only an administrator may revoke a ban.")
        if model.state == "active":
            model.state = "revoked"
            await self._restore_status(model)
            self._session.add(
                SanctionEventModel(
                    sanction_id=model.id,
                    event_type="revoked",
                    actor_member_id=actor.id,
                    reason=reason,
                    command_id=command.command_id,
                )
            )
            await self._audit(actor.id, "sanction_revoked", "member_sanction", model.id, reason)
        await self._session.flush()
        return _sanction(model)

    async def review_alert(self, command: ReviewAlertCommand, actor: Member) -> str:
        """Close one alert and apply an optional all-or-nothing penalty batch."""
        _require_admin(actor)
        if "interaction_review" not in actor.permissions:
            raise PermissionError("Interaction review permission is required.")
        notes = _required(command.notes, "Interaction review notes are required.")
        if command.penalties and command.outcome is not AlertOutcome.PENALTY_RECOMMENDED:
            raise ModerationError("Penalty requires the penalty_recommended outcome.")
        alert = await self._session.get(InteractionAlertModel, command.alert_id)
        if alert is None:
            raise LookupError("Interaction alert does not exist.")
        commands = tuple(
            apply_penalty(
                member_id=member_id,
                amount=amount,
                idempotency_key=f"interaction-alert:{alert.id}:penalty:{member_id}",
                context=AdministrativeContext(actor.id, "interaction_alert_penalty", notes),
            )
            for member_id, amount in command.penalties
        )
        prepared = None if not commands else await self._economy.prepare_batch(commands)
        first, second = sorted((alert.first_member_id, alert.second_member_id), key=str)
        await _gate(self._session, _PAIR_GATE, f"{first}:{second}")
        alert = await self._session.scalar(
            select(InteractionAlertModel)
            .where(InteractionAlertModel.id == command.alert_id)
            .with_for_update()
        )
        if alert is None:
            raise LookupError("Interaction alert does not exist.")
        if alert.state == "closed":
            return f"alert:{alert.id}:{alert.outcome}"
        if prepared is not None:
            await prepared.apply()
        alert.state = "closed"
        alert.outcome = command.outcome.value
        alert.meeting_notes = notes
        alert.closed_at = datetime.datetime.now(datetime.UTC)
        await self._audit(
            actor.id, "interaction_alert_reviewed", "interaction_alert", alert.id, notes
        )
        await self._session.flush()
        return f"alert:{alert.id}:{alert.outcome}"

    async def moderate_karma(self, command: ModerateKarmaCommand, actor: Member) -> str:
        """Exclude or restore one exact current vote revision."""
        _require_admin(actor)
        if "karma_review" not in actor.permissions:
            raise PermissionError("Karma review permission is required.")
        reason = _required(command.reason, "Karma moderation reason is required.")
        vote = await self._session.get(KarmaVoteModel, command.vote_id)
        if vote is None:
            raise LookupError("Karma vote does not exist.")
        first, second = sorted((vote.rater_id, vote.target_id), key=str)
        await _gate(self._session, "reputation_pair", f"{first}:{second}")
        vote = await self._session.scalar(
            select(KarmaVoteModel).where(KarmaVoteModel.id == command.vote_id).with_for_update()
        )
        if vote is None or vote.revision != command.vote_revision:
            raise ModerationError("Karma vote revision is stale.")
        stored = await self._session.scalar(
            select(KarmaVoteModerationModel).where(
                KarmaVoteModerationModel.command_id == command.command_id
            )
        )
        state = "excluded" if command.exclude else "restored"
        if stored is None:
            latest = await self._session.scalar(
                select(KarmaVoteModerationModel)
                .where(
                    KarmaVoteModerationModel.karma_vote_id == vote.id,
                    KarmaVoteModerationModel.vote_revision == vote.revision,
                )
                .order_by(
                    KarmaVoteModerationModel.created_at.desc(), KarmaVoteModerationModel.id.desc()
                )
                .limit(1)
            )
            if latest is None or latest.state != state:
                stored = KarmaVoteModerationModel(
                    id=uuid.uuid4(),
                    karma_vote_id=vote.id,
                    vote_revision=vote.revision,
                    state=state,
                    actor_member_id=actor.id,
                    reason=reason,
                    command_id=command.command_id,
                )
                self._session.add(stored)
        await self._audit(actor.id, f"karma_vote_{state}", "karma_vote", vote.id, reason)
        await self._session.flush()
        return f"karma:{vote.id}:{vote.revision}:{state}"

    async def _apply_resolution_economy(
        self,
        *,
        case: ModerationCaseModel,
        assignment: AssignmentModel,
        task: TaskModel,
        code: ResolutionCode,
        version: int,
        actor: Member,
        reason: str,
    ) -> tuple[EconomyMutationResult, ...]:
        if case.case_type == "fraud_review" and version == 1:
            source_rows = await self._fraud_sources(assignment.id)
            if not source_rows:
                raise ModerationError("Paid fraud case has no reversible payout.")
            return await self._economy.apply_batch(
                tuple(
                    ReversalCommand(
                        reversed_transaction_id=row.id,
                        idempotency_key=f"case:{case.id}:v{version}:fraud:{row.id}",
                        actor_member_id=actor.id,
                        reason=reason,
                    )
                    for row in source_rows
                )
            )
        reward = task.credit_reward_per_performer
        if code in {ResolutionCode.FULL_PAYMENT, ResolutionCode.CREATOR_ABUSE}:
            builder = earn_community_reward if task.origin == "community" else earn_reward
            commands = (
                builder(
                    member_id=assignment.performer_id,
                    amount=reward,
                    idempotency_key=f"case:{case.id}:v{version}:full",
                    task_id=task.id,
                    assignment_id=assignment.id,
                ),
            )
        elif code is ResolutionCode.PARTIAL_PAYMENT:
            amount = (reward + 1) // 2
            builder = earn_community_reward if task.origin == "community" else earn_partial_reward
            pending = [
                builder(
                    member_id=assignment.performer_id,
                    amount=amount,
                    idempotency_key=f"case:{case.id}:v{version}:partial",
                    task_id=task.id,
                    assignment_id=assignment.id,
                )
            ]
            if task.creator_id is not None and amount < reward:
                pending.append(
                    refund_reward(
                        member_id=task.creator_id,
                        amount=reward - amount,
                        idempotency_key=f"case:{case.id}:v{version}:remainder",
                        task_id=task.id,
                        assignment_id=assignment.id,
                    )
                )
            commands = tuple(pending)
        elif task.creator_id is not None:
            commands = (
                refund_reward(
                    member_id=task.creator_id,
                    amount=reward,
                    idempotency_key=f"case:{case.id}:v{version}:refund",
                    task_id=task.id,
                    assignment_id=assignment.id,
                ),
            )
        else:
            commands = ()
        return () if not commands else await self._economy.apply_batch(commands)

    async def _acquire_case_assignment_gate(self, case_id: uuid.UUID) -> None:
        """Serialize every case mutation by its assignment identity."""
        case = await self._session.get(ModerationCaseModel, case_id)
        if case is None:
            raise LookupError("Moderation case does not exist.")
        await _gate(self._session, _CASE_GATE, case.assignment_id)

    async def _case_context(
        self, case_id: uuid.UUID, actor: Member
    ) -> tuple[ModerationCaseModel, AssignmentModel, TaskModel]:
        """Load one case and enforce staff, test-run, and conflict boundaries."""
        _require_staff(actor)
        case = await self._session.get(ModerationCaseModel, case_id)
        if case is None:
            raise LookupError("Moderation case does not exist.")
        assignment = await self._session.get(AssignmentModel, case.assignment_id)
        if assignment is None:
            raise LookupError("Case assignment does not exist.")
        task = await self._session.get(TaskModel, assignment.task_id)
        if task is None:
            raise LookupError("Case task does not exist.")
        await self._require_test_scope(actor.id, task)
        await self._reject_conflict(
            actor, assignment, task, case, 1 if case.status != "appealed" else 2
        )
        return case, assignment, task

    async def _require_test_scope(self, actor_id: uuid.UUID, task: TaskModel) -> None:
        scope = await active_scope(self._session, actor_id)
        if task.test_run_id != (None if scope is None else scope.id):
            raise PermissionError("Moderation case is outside the actor test scope.")

    @staticmethod
    def _allowed_resolution_codes(
        actor: Member, task: TaskModel, case: ModerationCaseModel
    ) -> tuple[ResolutionCode, ...]:
        if case.case_type == "fraud_review":
            return (ResolutionCode.FRAUD,) if actor.role is MemberRole.ADMINISTRATOR else ()
        codes = []
        for code in ResolutionCode:
            if code is ResolutionCode.FRAUD and actor.role is not MemberRole.ADMINISTRATOR:
                continue
            try:
                resolution_effect(code, origin=task.origin)
            except ModerationError:
                continue
            codes.append(code)
        return tuple(codes)

    async def _fraud_sources(self, assignment_id: uuid.UUID) -> tuple[AccountTransactionModel, ...]:
        """Return every immutable positive payout eligible for exact reversal."""
        return tuple(
            (
                await self._session.scalars(
                    select(AccountTransactionModel).where(
                        AccountTransactionModel.assignment_id == assignment_id,
                        AccountTransactionModel.transaction_type.in_(
                            (
                                "task_reward_earned",
                                "partial_task_reward",
                                "community_task_reward",
                            )
                        ),
                        AccountTransactionModel.credit_delta > 0,
                    )
                )
            ).all()
        )

    async def _reject_conflict(
        self,
        actor: Member,
        assignment: AssignmentModel,
        task: TaskModel,
        case: ModerationCaseModel,
        version: int,
    ) -> None:
        if actor.id in {assignment.performer_id, task.creator_id}:
            raise PermissionError("Moderator has a conflict of interest in this case.")
        parties = [assignment.performer_id]
        if task.creator_id is not None:
            parties.append(task.creator_id)
        invited = await self._session.scalar(
            select(MemberModel.id).where(
                MemberModel.id.in_(parties), MemberModel.invited_by_member_id == actor.id
            )
        )
        prior_sanction = await self._session.scalar(
            select(MemberSanctionModel.id).where(
                MemberSanctionModel.target_member_id.in_(parties),
                MemberSanctionModel.author_member_id == actor.id,
            )
        )
        if invited is not None or prior_sanction is not None:
            raise PermissionError("Moderator has a prior relationship with a case party.")
        if version == 2:
            previous = await self._current_resolution(case)
            if previous.actor_member_id == actor.id:
                raise PermissionError("Appeal must be decided by another administrator.")

    async def _current_resolution(self, case: ModerationCaseModel) -> DisputeResolutionModel:
        if case.current_resolution_id is None:
            raise ModerationError("Case has no previous resolution.")
        model = await self._session.get(DisputeResolutionModel, case.current_resolution_id)
        if model is None:
            raise LookupError("Current resolution does not exist.")
        return model

    async def _add_resolution_signal(
        self,
        case: ModerationCaseModel,
        assignment: AssignmentModel,
        task: TaskModel,
        code: ResolutionCode,
        target: str,
    ) -> None:
        target_id = task.creator_id if target == "creator" else assignment.performer_id
        key = f"resolution:{case.id}:{case.revision + 1}:{code.value}"
        self._session.add(
            ModerationRiskSignalModel(
                id=uuid.uuid4(),
                signal_type=f"resolution_{code.value}",
                target_member_id=target_id,
                entity_key=str(case.id),
                idempotency_key=key,
                details_json={"case_id": str(case.id), "assignment_id": str(assignment.id)},
            )
        )

    async def _restore_status(self, sanction: MemberSanctionModel) -> None:
        if sanction.applied_status is None or sanction.previous_status is None:
            return
        member = await self._session.scalar(
            select(MemberModel).where(MemberModel.id == sanction.target_member_id).with_for_update()
        )
        if member is None or member.status != sanction.applied_status:
            return
        other = await self._session.scalar(
            select(MemberSanctionModel.id).where(
                MemberSanctionModel.target_member_id == sanction.target_member_id,
                MemberSanctionModel.id != sanction.id,
                MemberSanctionModel.state == "active",
                MemberSanctionModel.applied_status.is_not(None),
                or_(
                    MemberSanctionModel.ends_at.is_(None),
                    MemberSanctionModel.ends_at > datetime.datetime.now(datetime.UTC),
                ),
            )
        )
        if other is None:
            member.status = sanction.previous_status

    async def _case(self, model: ModerationCaseModel) -> ModerationCase:
        code = None
        if model.current_resolution_id is not None:
            current = await self._session.get(DisputeResolutionModel, model.current_resolution_id)
            code = None if current is None else ResolutionCode(current.code)
        return ModerationCase(
            id=model.id,
            assignment_id=model.assignment_id,
            case_type=model.case_type,
            status=model.status,
            revision=model.revision,
            current_code=code,
            opened_at=model.opened_at,
            resolved_at=model.resolved_at,
        )

    async def _audit(
        self, actor_id: UUID | None, action: str, entity_type: str, entity_id: UUID, reason: str
    ) -> None:
        self._session.add(
            AuditEventModel(
                actor_member_id=actor_id,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id),
                before_json=None,
                after_json=None,
                reason=reason,
            )
        )


async def effective_member_status(
    session: AsyncSession, member: MemberModel, *, materialize: bool
) -> MemberStatus:
    """Resolve expired status sanctions without depending on a scheduler."""
    if member.status != MemberStatus.SUSPENDED.value:
        return MemberStatus(member.status)
    now = datetime.datetime.now(datetime.UTC)
    active = await session.scalar(
        select(MemberSanctionModel).where(
            MemberSanctionModel.target_member_id == member.id,
            MemberSanctionModel.state == "active",
            MemberSanctionModel.applied_status == MemberStatus.SUSPENDED.value,
            or_(MemberSanctionModel.ends_at.is_(None), MemberSanctionModel.ends_at > now),
        )
    )
    if active is not None:
        return MemberStatus.SUSPENDED
    expired = await session.scalar(
        select(MemberSanctionModel)
        .where(
            MemberSanctionModel.target_member_id == member.id,
            MemberSanctionModel.state == "active",
            MemberSanctionModel.applied_status == MemberStatus.SUSPENDED.value,
            MemberSanctionModel.ends_at <= now,
        )
        .order_by(MemberSanctionModel.starts_at.desc())
    )
    if expired is None or expired.previous_status is None:
        return MemberStatus(member.status)
    if materialize:
        expired.state = "expired"
        member.status = expired.previous_status
        session.add(
            SanctionEventModel(
                sanction_id=expired.id,
                event_type="expired",
                actor_member_id=None,
                reason="effective_status_resolution",
            )
        )
    return MemberStatus(expired.previous_status)


async def ensure_action_allowed(
    session: AsyncSession, member_id: UUID, action: RestrictedAction
) -> None:
    """Materialize elapsed sanctions and reject one currently restricted action."""
    await _gate(session, _SANCTION_GATE, member_id)
    member = await session.scalar(
        select(MemberModel).where(MemberModel.id == member_id).with_for_update()
    )
    if member is None:
        raise LookupError("Member does not exist.")
    await effective_member_status(session, member, materialize=True)
    now = datetime.datetime.now(datetime.UTC)
    blocked = await session.scalar(
        select(MemberSanctionModel.id).where(
            MemberSanctionModel.target_member_id == member_id,
            MemberSanctionModel.state == "active",
            MemberSanctionModel.sanction_type == SanctionType.RESTRICTION.value,
            MemberSanctionModel.restricted_actions_json.contains([action.value]),
            or_(MemberSanctionModel.ends_at.is_(None), MemberSanctionModel.ends_at > now),
        )
    )
    if blocked is not None:
        message = f"Action is restricted: {action.value}."
        raise PermissionError(message)


def _sanction(model: MemberSanctionModel) -> Sanction:
    return Sanction(
        id=model.id,
        target_member_id=model.target_member_id,
        sanction_type=SanctionType(model.sanction_type),
        state=model.state,
        restricted_actions=tuple(
            RestrictedAction(value) for value in model.restricted_actions_json
        ),
        starts_at=model.starts_at,
        ends_at=model.ends_at,
    )


def _preview(model: ModerationDecisionDraftModel) -> ResolutionPreview:
    return ResolutionPreview(
        id=model.id,
        case_id=model.case_id,
        expected_revision=model.expected_revision,
        code=ResolutionCode(model.code),
        reason=model.reason,
    )


async def generate_karma_signals(session: AsyncSession, vote_id: UUID) -> None:
    """Create privacy-safe signals for the accepted D-023 karma rules."""
    vote = await session.get(KarmaVoteModel, vote_id)
    if vote is None or vote.value != -1:
        return
    now = datetime.datetime.now(datetime.UTC)
    since = now - datetime.timedelta(hours=24)
    candidates: list[tuple[str, UUID, tuple[str, ...], dict[str, object]]] = []
    reverse = await session.scalar(
        select(KarmaVoteModel.id).where(
            KarmaVoteModel.rater_id == vote.target_id,
            KarmaVoteModel.target_id == vote.rater_id,
            KarmaVoteModel.value == -1,
        )
    )
    disputed = await session.scalar(
        select(ModerationCaseModel.id)
        .join(AssignmentModel, AssignmentModel.id == ModerationCaseModel.assignment_id)
        .join(TaskModel, TaskModel.id == AssignmentModel.task_id)
        .where(
            ModerationCaseModel.case_type == "dispute",
            or_(
                and_(
                    TaskModel.creator_id == vote.rater_id,
                    AssignmentModel.performer_id == vote.target_id,
                ),
                and_(
                    TaskModel.creator_id == vote.target_id,
                    AssignmentModel.performer_id == vote.rater_id,
                ),
            ),
        )
    )
    if reverse is not None and disputed is not None:
        pair = tuple(sorted((str(vote.rater_id), str(vote.target_id))))
        candidates.append(("mutual_negative_with_dispute", vote.target_id, pair, {"pair": pair}))
    negative_count = int(
        await session.scalar(
            select(func.count(KarmaVoteModel.id)).where(
                KarmaVoteModel.target_id == vote.target_id,
                KarmaVoteModel.value == -1,
                KarmaVoteModel.updated_at > since,
            )
        )
        or 0
    )
    if negative_count >= 3:
        candidates.append(
            (
                "negative_burst",
                vote.target_id,
                (str(vote.target_id),),
                {"target_id": str(vote.target_id), "count": negative_count},
            )
        )
    fingerprint = hashlib.sha256(" ".join(vote.comment.casefold().split()).encode()).hexdigest()
    comment_count = int(
        await session.scalar(
            select(func.count(func.distinct(KarmaVoteModel.rater_id))).where(
                KarmaVoteModel.target_id == vote.target_id,
                KarmaVoteModel.value == -1,
                KarmaVoteModel.updated_at > since,
                func.regexp_replace(func.lower(KarmaVoteModel.comment), r"\s+", " ", "g")
                == " ".join(vote.comment.casefold().split()),
            )
        )
        or 0
    )
    if comment_count >= 3:
        candidates.append(
            (
                "duplicate_negative_comment",
                vote.target_id,
                (str(vote.target_id), fingerprint),
                {
                    "target_id": str(vote.target_id),
                    "fingerprint": fingerprint,
                    "count": comment_count,
                },
            )
        )
    for rule, target_id, entity, details in candidates:
        key = risk_signal_key(rule=rule, occurred_at=now, entity_parts=entity)
        existing = await session.scalar(
            select(ModerationRiskSignalModel.id).where(
                ModerationRiskSignalModel.idempotency_key == key
            )
        )
        if existing is None:
            session.add(
                ModerationRiskSignalModel(
                    id=uuid.uuid4(),
                    signal_type=rule,
                    target_member_id=target_id,
                    entity_key=":".join(entity),
                    idempotency_key=key,
                    details_json=details,
                )
            )
    await session.flush()


async def recompute_interaction_alert(
    session: AsyncSession, assignment_id: UUID
) -> InteractionAlertModel | None:
    """Recompute one unordered paid pair after settlement or reversal."""
    assignment = await session.get(AssignmentModel, assignment_id)
    if assignment is None:
        return None
    task = await session.get(TaskModel, assignment.task_id)
    if task is None or task.origin != "member" or task.creator_id is None:
        return None
    first, second = sorted((task.creator_id, assignment.performer_id), key=str)
    await _gate(session, _PAIR_GATE, f"{first}:{second}")
    active_row = (
        await session.execute(
            select(ActiveProductConfigModel, ProductConfigVersionModel)
            .join(
                ProductConfigVersionModel,
                ProductConfigVersionModel.id == ActiveProductConfigModel.product_config_version_id,
            )
            .where(ActiveProductConfigModel.singleton_key.is_(True))
        )
    ).one_or_none()
    if active_row is None:
        return None
    _, config = active_row
    threshold = int(config.payload_json.get("interaction_alert_threshold", 0))
    window_days = int(config.payload_json.get("interaction_alert_window_days", 7))
    if threshold <= 0:
        return None
    since = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=window_days)
    paid_ids = (
        await session.scalars(
            select(AccountTransactionModel.assignment_id)
            .join(AssignmentModel, AssignmentModel.id == AccountTransactionModel.assignment_id)
            .join(TaskModel, TaskModel.id == AssignmentModel.task_id)
            .where(
                TaskModel.origin == "member",
                or_(
                    and_(TaskModel.creator_id == first, AssignmentModel.performer_id == second),
                    and_(TaskModel.creator_id == second, AssignmentModel.performer_id == first),
                ),
                AccountTransactionModel.transaction_type.in_(
                    ("task_reward_earned", "partial_task_reward")
                ),
                AccountTransactionModel.credit_delta > 0,
                AccountTransactionModel.created_at > since,
            )
            .distinct()
        )
    ).all()
    # The correlated alias above cannot refer to two instances of the same model;
    # remove reversed sources explicitly with a second compact query.
    reversed_ids = set(
        await session.scalars(
            select(AccountTransactionModel.reversed_transaction_id).where(
                AccountTransactionModel.reversed_transaction_id.is_not(None)
            )
        )
    )
    source_rows = (
        await session.scalars(
            select(AccountTransactionModel).where(
                AccountTransactionModel.assignment_id.in_(paid_ids),
                AccountTransactionModel.transaction_type.in_(
                    ("task_reward_earned", "partial_task_reward")
                ),
                AccountTransactionModel.credit_delta > 0,
            )
        )
    ).all()
    eligible_ids = {row.assignment_id for row in source_rows if row.id not in reversed_ids}
    count = len(eligible_ids)
    current = await session.scalar(
        select(InteractionAlertModel)
        .where(
            InteractionAlertModel.first_member_id == first,
            InteractionAlertModel.second_member_id == second,
            InteractionAlertModel.state == "open",
        )
        .with_for_update()
    )
    now = datetime.datetime.now(datetime.UTC)
    if current is not None:
        current.interaction_count = count
        current.threshold = threshold
        current.window_days = window_days
        current.config_version_id = config.id
        if count <= threshold:
            current.state = "closed"
            current.outcome = "rearmed"
            current.closed_at = now
        await _sync_alert_assignments(session, current.id, eligible_ids)
        return current
    latest = await session.scalar(
        select(InteractionAlertModel)
        .where(
            InteractionAlertModel.first_member_id == first,
            InteractionAlertModel.second_member_id == second,
        )
        .order_by(InteractionAlertModel.opened_at.desc())
        .limit(1)
    )
    if latest is not None and latest.state == "closed" and latest.outcome == "rearmed":
        latest.interaction_count = count
    if count <= threshold or (latest is not None and latest.interaction_count > threshold):
        return latest
    current = InteractionAlertModel(
        id=uuid.uuid4(),
        first_member_id=first,
        second_member_id=second,
        interaction_count=count,
        threshold=threshold,
        window_days=window_days,
        config_version_id=config.id,
    )
    session.add(current)
    await session.flush()
    await _sync_alert_assignments(session, current.id, eligible_ids)
    session.add(
        OutboxEventModel(
            event_type="interaction_alert_opened",
            aggregate_type="interaction_alert",
            aggregate_id=current.id,
            payload_json={"alert_id": str(current.id), "interaction_count": count},
            business_key=f"interaction-alert:{current.id}:opened",
        )
    )
    return current


async def _sync_alert_assignments(
    session: AsyncSession, alert_id: UUID, assignment_ids: set[UUID | None]
) -> None:
    existing = set(
        await session.scalars(
            select(InteractionAlertAssignmentModel.assignment_id).where(
                InteractionAlertAssignmentModel.alert_id == alert_id
            )
        )
    )
    for assignment_id in assignment_ids - existing:
        if assignment_id is not None:
            session.add(
                InteractionAlertAssignmentModel(alert_id=alert_id, assignment_id=assignment_id)
            )


async def _gate(session: AsyncSession, namespace: str, value: object) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:value, hashtextextended(:gate, 0)))"),
        {"gate": namespace, "value": str(value)},
    )


def _payload_hash(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _required(value: str, message: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ModerationError(message)
    return normalized


def _require_staff(actor: Member) -> None:
    if actor.status is not MemberStatus.ACTIVE or actor.role not in {
        MemberRole.MODERATOR,
        MemberRole.ADMINISTRATOR,
    }:
        raise PermissionError("Active moderation staff is required.")


def _require_admin(actor: Member) -> None:
    if actor.status is not MemberStatus.ACTIVE or actor.role is not MemberRole.ADMINISTRATOR:
        raise PermissionError("An active administrator is required.")
