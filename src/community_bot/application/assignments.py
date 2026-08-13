# ruff: noqa: C901, D102, D107, EM101, PLC0415, PLR0912, PLR0915, TRY003
"""Atomic application workflows for task acceptance, delivery, and review."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from community_bot.domain.assignments import (
    Assignment,
    AssignmentDecision,
    AssignmentError,
    AssignmentStatus,
    ResultVersion,
    SubmissionDraft,
    partial_reward,
    require_dispute_allowed,
    require_submit_allowed,
)
from community_bot.domain.catalog import validate_payload
from community_bot.domain.economy import (
    earn_community_reward,
    earn_partial_reward,
    earn_reward,
    refund_reward,
)
from community_bot.domain.members import Member, MemberRole, MemberStatus
from community_bot.domain.moderation import RestrictedAction
from community_bot.domain.tasks import TaskStatus

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from contextlib import AbstractAsyncContextManager

    from community_bot.application.catalog import CatalogTemplate
    from community_bot.application.conversations import TextFlow
    from community_bot.application.economy import ActiveProductConfig, EconomyMutationPort
    from community_bot.application.tasks import PublishedTask
    from community_bot.domain.economy import ResolvedLevel


@dataclass(frozen=True, slots=True)
class AcceptAssignmentCommand:
    """Accept one free task slot."""

    update_id: int
    actor_telegram_user_id: int
    task_id: UUID


@dataclass(frozen=True, slots=True)
class SubmitResultCommand:
    """Append one assignment result version."""

    update_id: int
    actor_telegram_user_id: int
    assignment_id: UUID
    submit_command_id: UUID
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class DecideAssignmentCommand:
    """Apply an author's exact assignment decision."""

    update_id: int
    actor_telegram_user_id: int
    assignment_id: UUID
    decision_command_id: UUID
    decision: AssignmentDecision


@dataclass(frozen=True, slots=True)
class BeginSubmissionCommand:
    """Start or resume durable result input for one assignment."""

    update_id: int
    actor_telegram_user_id: int
    assignment_id: UUID


@dataclass(frozen=True, slots=True)
class SaveSubmissionDraftCommand:
    """Validate and persist one result preview."""

    update_id: int
    actor_telegram_user_id: int
    draft_id: UUID
    expected_revision: int
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ConfirmSubmissionDraftCommand:
    """Confirm a durable result preview exactly once."""

    update_id: int
    actor_telegram_user_id: int
    draft_id: UUID
    expected_revision: int


@dataclass(frozen=True, slots=True)
class AssignmentCard:
    """Privacy-safe Telegram projection for one assignment and its task."""

    assignment: Assignment
    task: PublishedTask
    task_title: str
    task_origin: str
    task_creator_id: UUID | None
    reviewer_admin_id: UUID | None
    performer_display_name: str
    result_summary: str | None
    case_id: UUID | None
    case_status: str | None
    case_revision: int | None


class AssignmentUnitOfWork(Protocol):  # pragma: no cover - structural typing contract.
    """Caller-owned transaction required by assignment workflows."""

    @property
    def economy(self) -> EconomyMutationPort: ...
    async def acquire_update_gate(self, update_id: int) -> None: ...
    async def get_receipt_outcome(self, update_id: int) -> str | None: ...
    async def acquire_task_identity_gate(self, telegram_user_id: int) -> None: ...
    async def acquire_assignment_task_gate(self, task_id: UUID) -> None: ...
    async def acquire_assignment_limit_gate(self, member_id: UUID) -> None: ...
    async def get_member_by_telegram_user_id(self, telegram_user_id: int) -> Member | None: ...
    async def ensure_moderation_action_allowed(
        self, member_id: UUID, action: RestrictedAction
    ) -> None: ...
    async def lock_members(self, member_ids: Sequence[UUID]) -> dict[UUID, Member]: ...
    async def resolve_member_level(self, member_id: UUID) -> ResolvedLevel: ...
    async def get_active_product_config(self) -> ActiveProductConfig | None: ...
    async def lock_task(self, task_id: UUID) -> PublishedTask | None: ...
    async def catalog_template(self, template_id: UUID) -> CatalogTemplate | None: ...
    async def count_active_assignments(self, performer_id: UUID) -> int: ...
    async def create_assignment(
        self, *, task_id: UUID, performer_id: UUID, slots: int
    ) -> Assignment: ...
    async def lock_assignment(self, assignment_id: UUID) -> Assignment | None: ...
    async def get_assignment(self, assignment_id: UUID) -> Assignment | None: ...
    async def list_assignments(self, performer_id: UUID) -> tuple[Assignment, ...]: ...
    async def list_assignment_cards(self, performer_id: UUID) -> tuple[AssignmentCard, ...]: ...
    async def list_review_cards(self, actor_id: UUID) -> tuple[AssignmentCard, ...]: ...
    async def list_task_assignments(
        self, task_id: UUID, *, for_update: bool = False
    ) -> tuple[Assignment, ...]: ...
    async def cancel_assignment(self, assignment_id: UUID, reason: str) -> Assignment: ...
    async def append_assignment_result(
        self,
        *,
        assignment_id: UUID,
        command_id: UUID,
        payload: dict[str, object],
        now: datetime.datetime,
    ) -> ResultVersion: ...
    async def get_assignment_result(self, result_id: UUID) -> ResultVersion | None: ...
    async def get_submission_draft(
        self, draft_id: UUID, *, for_update: bool = False
    ) -> SubmissionDraft | None: ...
    async def delete_submission_draft(self, draft_id: UUID) -> None: ...
    async def create_or_get_submission_draft(
        self, *, assignment_id: UUID, performer_id: UUID
    ) -> SubmissionDraft: ...
    async def save_submission_draft_payload(
        self,
        *,
        draft_id: UUID,
        expected_revision: int,
        payload: dict[str, object],
    ) -> SubmissionDraft: ...
    async def complete_submission_draft(
        self, *, draft_id: UUID, result_id: UUID
    ) -> SubmissionDraft: ...
    async def set_assignment_decision(
        self,
        *,
        assignment_id: UUID,
        status: AssignmentStatus,
        command_id: UUID,
        outcome: str,
        now: datetime.datetime,
    ) -> Assignment: ...
    async def mark_reviewer_required(self, assignment_id: UUID) -> Assignment: ...
    async def open_assignment_dispute(
        self, *, assignment_id: UUID, performer_id: UUID, command_id: UUID, comment: str
    ) -> UUID: ...
    async def append_assignment_reliability(
        self, assignment_id: UUID, event_type: str, actor_id: UUID | None, reason: str | None
    ) -> None: ...
    async def recompute_interaction_alert(self, assignment_id: UUID) -> None: ...
    async def add_assignment_outbox(
        self, *, assignment: Assignment, event_type: str, business_key: str
    ) -> None: ...
    async def add_receipt(
        self, *, update_id: int, update_type: str, actor_id: UUID | None, outcome_code: str
    ) -> None: ...
    async def get_text_flow(
        self, member_id: UUID, *, for_update: bool = False
    ) -> TextFlow | None: ...
    async def claim_text_flow(  # noqa: PLR0913
        self,
        *,
        member_id: UUID,
        flow_type: str,
        step: str,
        reference_id: UUID | None,
        revision: int,
        payload: dict[str, object] | None = None,
    ) -> object: ...
    async def clear_text_flow(
        self, *, member_id: UUID, flow_type: str, reference_id: UUID | None = None
    ) -> bool: ...
    async def commit(self) -> None: ...
    async def save_task_status(self, *, task_id: UUID, status: TaskStatus) -> PublishedTask: ...


class AssignmentUnitOfWorkFactory(Protocol):  # pragma: no cover - structural typing contract.
    """Create isolated assignment transactions."""

    def __call__(self) -> AbstractAsyncContextManager[AssignmentUnitOfWork]: ...


class AssignmentDeadlineSource(Protocol):  # pragma: no cover - structural typing contract.
    """List bounded tasks whose acceptance deadline has arrived."""

    async def due_task_ids(self, *, now: datetime.datetime, limit: int) -> Sequence[UUID]: ...


class AssignmentDeadlineWorker:
    """Finalize due assignments through the canonical transactional service."""

    def __init__(
        self,
        source: AssignmentDeadlineSource,
        service: AssignmentService,
        *,
        batch_size: int = 25,
    ) -> None:
        self._source = source
        self._service = service
        self._batch_size = batch_size

    async def tick(self, *, now: datetime.datetime) -> int:
        """Finalize one bounded due-task batch and return its task count."""
        task_ids = await self._source.due_task_ids(now=now, limit=self._batch_size)
        for task_id in task_ids:
            await self._service.finalize_deadline(
                task_id=task_id,
                command_id=UUID(int=task_id.int ^ int(now.timestamp())),
                now=now,
            )
        return len(task_ids)


class AssignmentService:
    """Coordinate the complete performer/author exchange lifecycle."""

    def __init__(self, unit_of_work_factory: AssignmentUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def accept(self, command: AcceptAssignmentCommand) -> Assignment:
        """Atomically claim one free slot and enforce the active limit."""
        assignment, _task = await self.accept_with_task(command)
        return assignment

    async def accept_with_task(
        self, command: AcceptAssignmentCommand
    ) -> tuple[Assignment, PublishedTask]:
        """Accept one task and return its authoritative display snapshot."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin(uow, command.update_id)
            if replay is not None:
                assignment = await _assignment_replay(uow, replay)
                task = await uow.lock_task(assignment.task_id)
                if task is None:
                    raise LookupError("Assignment task does not exist.")
                return assignment, task
            await uow.acquire_task_identity_gate(command.actor_telegram_user_id)
            actor = await _actor(uow, command.actor_telegram_user_id)
            await uow.ensure_moderation_action_allowed(actor.id, RestrictedAction.ACCEPT_TASK)
            await uow.acquire_assignment_limit_gate(actor.id)
            await uow.acquire_assignment_task_gate(command.task_id)
            task = await uow.lock_task(command.task_id)
            if task is None:
                raise LookupError("Task does not exist.")
            actor = (await uow.lock_members((actor.id,)))[actor.id]
            if task.origin == "community" and task.reviewer_admin_id == actor.id:
                raise PermissionError("Community reviewer cannot perform the task.")
            level = await uow.resolve_member_level(actor.id)
            task_snapshot = task.acceptance_snapshot()
            from community_bot.domain.tasks import validate_acceptance_actor

            validate_acceptance_actor(task_snapshot, actor, resolved_level=level)
            if datetime.datetime.now(datetime.UTC) >= task.deadline_at:
                raise AssignmentError("Task acceptance deadline has passed.")
            active = await uow.get_active_product_config()
            limit = 3 if active is None else active.maximum_active_assignments
            if await uow.count_active_assignments(actor.id) >= limit:
                raise AssignmentError("Member has reached the active assignment limit.")
            assignment = await uow.create_assignment(
                task_id=task.id, performer_id=actor.id, slots=task.performer_slots
            )
            await uow.add_assignment_outbox(
                assignment=assignment,
                event_type="assignment_accepted",
                business_key=f"assignment:{assignment.id}:accepted",
            )
            await _finish(uow, command.update_id, actor.id, assignment)
            return assignment, task

    async def list_owned(self, actor_telegram_user_id: int) -> tuple[Assignment, ...]:
        """Return only assignments owned by the active performer."""
        async with self._unit_of_work_factory() as uow:
            actor = await _actor(uow, actor_telegram_user_id)
            return await uow.list_assignments(actor.id)

    async def cards(self, actor_telegram_user_id: int) -> tuple[AssignmentCard, ...]:
        """Return visible performer cards without exposing internal identifiers."""
        async with self._unit_of_work_factory() as uow:
            actor = await _actor(uow, actor_telegram_user_id)
            return await uow.list_assignment_cards(actor.id)

    async def begin_dispute(
        self, *, update_id: int, actor_telegram_user_id: int, assignment_id: UUID
    ) -> Assignment:
        """Select one rejected assignment as the current private comment flow."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin(uow, update_id)
            if replay is not None:
                return await _assignment_replay(uow, replay)
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            actor = await _actor(uow, actor_telegram_user_id)
            assignment = await uow.get_assignment(assignment_id)
            if assignment is None or assignment.performer_id != actor.id:
                raise PermissionError("Assignment is not owned by this member.")
            require_dispute_allowed(assignment, now=datetime.datetime.now(datetime.UTC))
            await uow.claim_text_flow(
                member_id=actor.id,
                flow_type="assignment_dispute",
                step="comment",
                reference_id=assignment.id,
                revision=0,
            )
            await uow.add_receipt(
                update_id=update_id,
                update_type="assignment_workflow",
                actor_id=actor.id,
                outcome_code=f"assignment:{assignment.id}",
            )
            await uow.commit()
            return assignment

    async def cancel_text_flow(
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        flow_type: str,
        reference_id: UUID,
    ) -> bool:
        """Cancel only the selected assignment result or dispute input."""
        if flow_type not in {"assignment_result", "assignment_dispute"}:
            return False
        async with self._unit_of_work_factory() as uow:
            await uow.acquire_update_gate(update_id)
            stored = await uow.get_receipt_outcome(update_id)
            if stored is not None:
                if stored != f"assignment_flow_cancelled:{flow_type}:{reference_id}":
                    raise AssignmentError("Telegram update belongs to another operation.")
                return True
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            actor = await _actor(uow, actor_telegram_user_id)
            owner = await uow.get_text_flow(actor.id, for_update=True)
            if owner is None or owner.flow_type != flow_type or owner.reference_id != reference_id:
                return False
            if flow_type == "assignment_result":
                draft = await uow.get_submission_draft(reference_id, for_update=True)
                if draft is None or draft.performer_id != actor.id:
                    raise PermissionError("Submission draft is not owned by this member.")
                if draft.submitted_result_id is None:
                    await uow.delete_submission_draft(draft.id)
            await uow.clear_text_flow(
                member_id=actor.id,
                flow_type=flow_type,
                reference_id=reference_id,
            )
            outcome = f"assignment_flow_cancelled:{flow_type}:{reference_id}"
            await uow.add_receipt(
                update_id=update_id,
                update_type="assignment_workflow",
                actor_id=actor.id,
                outcome_code=outcome,
            )
            await uow.commit()
            return True

    async def review_cards(self, actor_telegram_user_id: int) -> tuple[AssignmentCard, ...]:
        """Return only assignments this actor may attempt to review."""
        async with self._unit_of_work_factory() as uow:
            actor = await _actor(uow, actor_telegram_user_id)
            return await uow.list_review_cards(actor.id)

    async def begin_submission(self, command: BeginSubmissionCommand) -> SubmissionDraft:
        """Start or resume result input with all state persisted in PostgreSQL."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin(uow, command.update_id)
            if replay is not None:
                return await _draft_replay(uow, replay)
            await uow.acquire_task_identity_gate(command.actor_telegram_user_id)
            actor = await _actor(uow, command.actor_telegram_user_id)
            preliminary = await uow.get_assignment(command.assignment_id)
            if preliminary is None or preliminary.performer_id != actor.id:
                raise PermissionError("Assignment is not owned by this member.")
            await uow.acquire_assignment_task_gate(preliminary.task_id)
            task = await uow.lock_task(preliminary.task_id)
            assignment = await uow.lock_assignment(preliminary.id)
            if task is None or assignment is None:
                raise LookupError("Assignment task does not exist.")
            if task.origin == "community" and task.reviewer_admin_id == actor.id:
                raise PermissionError("Community reviewer cannot perform the task.")
            require_submit_allowed(
                assignment, task_deadline=task.deadline_at, now=datetime.datetime.now(datetime.UTC)
            )
            draft = await uow.create_or_get_submission_draft(
                assignment_id=assignment.id, performer_id=actor.id
            )
            await uow.claim_text_flow(
                member_id=actor.id,
                flow_type="assignment_result",
                step="text",
                reference_id=draft.id,
                revision=draft.revision,
            )
            await uow.add_receipt(
                update_id=command.update_id,
                update_type="assignment_workflow",
                actor_id=actor.id,
                outcome_code=f"draft:{draft.id}",
            )
            await uow.commit()
            return draft

    async def save_submission_draft(self, command: SaveSubmissionDraftCommand) -> SubmissionDraft:
        """Persist a schema-valid preview without submitting the assignment."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin(uow, command.update_id)
            if replay is not None:
                return await _draft_replay(uow, replay)
            await uow.acquire_task_identity_gate(command.actor_telegram_user_id)
            actor = await _actor(uow, command.actor_telegram_user_id)
            preliminary = await uow.get_submission_draft(command.draft_id)
            if preliminary is None or preliminary.performer_id != actor.id:
                raise PermissionError("Submission draft is not owned by this member.")
            assignment = await uow.get_assignment(preliminary.assignment_id)
            if assignment is None:
                raise LookupError("Assignment does not exist.")
            await uow.acquire_assignment_task_gate(assignment.task_id)
            task = await uow.lock_task(assignment.task_id)
            assignment = await uow.lock_assignment(assignment.id)
            draft = await uow.get_submission_draft(command.draft_id, for_update=True)
            if task is None or assignment is None or draft is None:
                raise LookupError("Submission draft context does not exist.")
            if assignment.performer_id != actor.id or draft.assignment_id != assignment.id:
                raise PermissionError("Submission draft is not owned by this member.")
            require_submit_allowed(
                assignment, task_deadline=task.deadline_at, now=datetime.datetime.now(datetime.UTC)
            )
            template = await uow.catalog_template(task.template_id)
            if template is None:
                raise LookupError("Historical task template does not exist.")
            payload = validate_payload(template.result_schema, command.payload)
            saved = await uow.save_submission_draft_payload(
                draft_id=draft.id,
                expected_revision=command.expected_revision,
                payload=payload,
            )
            await uow.claim_text_flow(
                member_id=actor.id,
                flow_type="assignment_result",
                step="preview",
                reference_id=saved.id,
                revision=saved.revision,
            )
            await uow.add_receipt(
                update_id=command.update_id,
                update_type="assignment_workflow",
                actor_id=actor.id,
                outcome_code=f"draft:{saved.id}",
            )
            await uow.commit()
            return saved

    async def confirm_submission_draft(
        self, command: ConfirmSubmissionDraftCommand
    ) -> ResultVersion:
        """Append the preview as a result under its stable command identity."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin(uow, command.update_id)
            if replay is not None:
                return await _result_replay(uow, replay)
            await uow.acquire_task_identity_gate(command.actor_telegram_user_id)
            actor = await _actor(uow, command.actor_telegram_user_id)
            preliminary = await uow.get_submission_draft(command.draft_id)
            if preliminary is None or preliminary.performer_id != actor.id:
                raise PermissionError("Submission draft is not owned by this member.")
            assignment = await uow.get_assignment(preliminary.assignment_id)
            if assignment is None:
                raise LookupError("Assignment does not exist.")
            await uow.acquire_assignment_task_gate(assignment.task_id)
            task = await uow.lock_task(assignment.task_id)
            assignment = await uow.lock_assignment(assignment.id)
            draft = await uow.get_submission_draft(command.draft_id, for_update=True)
            if task is None or assignment is None or draft is None:
                raise LookupError("Submission draft context does not exist.")
            if assignment.performer_id != actor.id or draft.assignment_id != assignment.id:
                raise PermissionError("Submission draft is not owned by this member.")
            if draft.revision != command.expected_revision:
                raise AssignmentError("Submission draft revision is stale.")
            if draft.submitted_result_id is not None:
                raise AssignmentError("Submission draft is already confirmed.")
            if draft.payload is None:
                raise AssignmentError("Submission draft has no preview payload.")
            now = datetime.datetime.now(datetime.UTC)
            require_submit_allowed(assignment, task_deadline=task.deadline_at, now=now)
            result = await uow.append_assignment_result(
                assignment_id=assignment.id,
                command_id=draft.submit_command_id,
                payload=draft.payload,
                now=now,
            )
            await uow.complete_submission_draft(draft_id=draft.id, result_id=result.id)
            await uow.clear_text_flow(
                member_id=actor.id,
                flow_type="assignment_result",
                reference_id=draft.id,
            )
            updated = await uow.lock_assignment(assignment.id)
            if updated is None:
                raise LookupError("Assignment does not exist.")
            await uow.add_assignment_outbox(
                assignment=updated,
                event_type="assignment_submitted",
                business_key=f"assignment:{assignment.id}:result:{result.version}",
            )
            await uow.add_receipt(
                update_id=command.update_id,
                update_type="assignment_workflow",
                actor_id=actor.id,
                outcome_code=f"result:{result.id}",
            )
            await uow.commit()
            return result

    async def cancel(
        self, *, update_id: int, actor_telegram_user_id: int, assignment_id: UUID, reason: str
    ) -> Assignment:
        """Cancel one accepted assignment and free its slot."""
        normalized = reason.strip()
        if not normalized:
            raise AssignmentError("Assignment cancellation reason is required.")
        async with self._unit_of_work_factory() as uow:
            replay = await _begin(uow, update_id)
            if replay is not None:
                return await _assignment_replay(uow, replay)
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            actor = await _actor(uow, actor_telegram_user_id)
            preliminary = await uow.get_assignment(assignment_id)
            if preliminary is None:
                raise LookupError("Assignment does not exist.")
            await uow.acquire_assignment_task_gate(preliminary.task_id)
            assignment = await uow.lock_assignment(assignment_id)
            if assignment is None or assignment.performer_id != actor.id:
                raise PermissionError("Assignment is not owned by this member.")
            if assignment.status is not AssignmentStatus.ACCEPTED:
                raise AssignmentError("Only an accepted assignment can be cancelled.")
            assignment = await uow.cancel_assignment(assignment.id, normalized)
            await uow.add_assignment_outbox(
                assignment=assignment,
                event_type="assignment_cancelled",
                business_key=f"assignment:{assignment.id}:cancelled",
            )
            await _finish(uow, update_id, actor.id, assignment)
            return assignment

    async def submit(self, command: SubmitResultCommand) -> ResultVersion:
        """Append one validated result version without extending review time."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin(uow, command.update_id)
            if replay is not None:
                marker, _, _version_id = replay.partition(":")
                if marker != "result":
                    raise AssignmentError("Telegram update belongs to another operation.")
                assignment = await uow.lock_assignment(command.assignment_id)
                if assignment is None:
                    raise LookupError("Assignment does not exist.")
                return await uow.append_assignment_result(
                    assignment_id=assignment.id,
                    command_id=command.submit_command_id,
                    payload=dict(command.payload),
                    now=datetime.datetime.now(datetime.UTC),
                )
            await uow.acquire_task_identity_gate(command.actor_telegram_user_id)
            actor = await _actor(uow, command.actor_telegram_user_id)
            assignment = await uow.get_assignment(command.assignment_id)
            if assignment is None or assignment.performer_id != actor.id:
                raise PermissionError("Assignment is not owned by this member.")
            await uow.acquire_assignment_task_gate(assignment.task_id)
            task = await uow.lock_task(assignment.task_id)
            assignment = await uow.lock_assignment(assignment.id)
            if assignment is None or task is None:
                raise LookupError("Assignment task does not exist.")
            now = datetime.datetime.now(datetime.UTC)
            require_submit_allowed(assignment, task_deadline=task.deadline_at, now=now)
            template = await uow.catalog_template(task.template_id)
            if template is None:
                raise LookupError("Historical task template does not exist.")
            payload = validate_payload(template.result_schema, command.payload)
            result = await uow.append_assignment_result(
                assignment_id=assignment.id,
                command_id=command.submit_command_id,
                payload=payload,
                now=now,
            )
            updated = await uow.lock_assignment(assignment.id)
            if updated is None:
                raise LookupError("Assignment does not exist.")
            await uow.add_assignment_outbox(
                assignment=updated,
                event_type="assignment_submitted",
                business_key=f"assignment:{assignment.id}:result:{result.version}",
            )
            await uow.add_receipt(
                update_id=command.update_id,
                update_type="assignment_workflow",
                actor_id=actor.id,
                outcome_code=f"result:{result.id}",
            )
            await uow.commit()
            return result

    async def decide(self, command: DecideAssignmentCommand) -> Assignment:
        """Apply full, partial, or reject author review exactly once."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin(uow, command.update_id)
            if replay is not None:
                return await _assignment_replay(uow, replay)
            await uow.acquire_task_identity_gate(command.actor_telegram_user_id)
            actor = await _actor(uow, command.actor_telegram_user_id)
            assignment = await uow.get_assignment(command.assignment_id)
            if assignment is None:
                raise LookupError("Assignment does not exist.")
            await uow.acquire_assignment_task_gate(assignment.task_id)
            task = await uow.lock_task(assignment.task_id)
            assignment = await uow.lock_assignment(assignment.id)
            authorized = task is not None and (
                task.creator_id == actor.id
                or (
                    task.origin == "community"
                    and actor.role is MemberRole.ADMINISTRATOR
                    and (
                        (
                            task.reviewer_admin_id == actor.id
                            and task.created_by_admin_id != actor.id
                        )
                        or (task.reviewer_admin_id is None and task.created_by_admin_id is None)
                    )
                )
            )
            if assignment is None or task is None or not authorized:
                raise PermissionError("Only the task creator can review this assignment.")
            if assignment.status in {
                AssignmentStatus.APPROVED,
                AssignmentStatus.PARTIALLY_APPROVED,
                AssignmentStatus.REJECTED_PENDING_DISPUTE,
            }:
                if (
                    assignment.terminal_outcome != command.decision.value
                    or assignment.terminal_command_id != command.decision_command_id
                ):
                    raise AssignmentError("Assignment already has another review outcome.")
                await _finish(uow, command.update_id, actor.id, assignment)
                return assignment
            if assignment.status is not AssignmentStatus.SUBMITTED:
                raise AssignmentError("Only a submitted assignment can be reviewed.")
            now = datetime.datetime.now(datetime.UTC)
            if assignment.review_deadline_at is not None and now >= assignment.review_deadline_at:
                raise AssignmentError("Assignment review deadline has passed.")
            commands = ()
            if command.decision is AssignmentDecision.FULL:
                status = AssignmentStatus.APPROVED
                payout = task.credit_reward_per_performer
            elif command.decision is AssignmentDecision.PARTIAL:
                status = AssignmentStatus.PARTIALLY_APPROVED
                payout = partial_reward(task.credit_reward_per_performer)
            else:
                status = AssignmentStatus.REJECTED_PENDING_DISPUTE
                payout = 0
            if payout:
                if task.origin == "community":
                    reward_builder = earn_community_reward
                else:
                    reward_builder = (
                        earn_reward if status is AssignmentStatus.APPROVED else earn_partial_reward
                    )
                reward = reward_builder(
                    member_id=assignment.performer_id,
                    amount=payout,
                    idempotency_key=f"assignment:{assignment.id}:{status.value}:reward",
                    task_id=task.id,
                    assignment_id=assignment.id,
                )
                pending = [reward]
                remainder = task.credit_reward_per_performer - payout
                if remainder and task.creator_id is not None:
                    pending.append(
                        refund_reward(
                            member_id=task.creator_id,
                            amount=remainder,
                            idempotency_key=f"assignment:{assignment.id}:{status.value}:refund",
                            task_id=task.id,
                            assignment_id=assignment.id,
                        )
                    )
                commands = tuple(pending)
            prepared = None if not commands else await uow.economy.prepare_batch(commands)
            updated = await uow.set_assignment_decision(
                assignment_id=assignment.id,
                status=status,
                command_id=command.decision_command_id,
                outcome=command.decision.value,
                now=now,
            )
            if prepared is not None:
                await prepared.apply()
            if status in {AssignmentStatus.APPROVED, AssignmentStatus.PARTIALLY_APPROVED}:
                await uow.append_assignment_reliability(assignment.id, status.value, actor.id, None)
                await uow.recompute_interaction_alert(assignment.id)
            await uow.add_assignment_outbox(
                assignment=updated,
                event_type="assignment_reviewed",
                business_key=f"assignment:{assignment.id}:{status.value}",
            )
            if status in {AssignmentStatus.APPROVED, AssignmentStatus.PARTIALLY_APPROVED}:
                await _update_task_aggregate(
                    uow, task.id, task.performer_slots, now, task.deadline_at
                )
            await _finish(uow, command.update_id, actor.id, updated)
            return updated

    async def dispute(
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        assignment_id: UUID,
        command_id: UUID,
        comment: str,
    ) -> Assignment:
        """Open one private dispute inside the protected 24-hour window."""
        normalized = comment.strip()
        if not normalized:
            raise AssignmentError("Dispute comment is required.")
        async with self._unit_of_work_factory() as uow:
            replay = await _begin(uow, update_id)
            if replay is not None:
                return await _assignment_replay(uow, replay)
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            actor = await _actor(uow, actor_telegram_user_id)
            assignment = await uow.get_assignment(assignment_id)
            if assignment is None or assignment.performer_id != actor.id:
                raise PermissionError("Assignment is not owned by this member.")
            await uow.acquire_assignment_task_gate(assignment.task_id)
            assignment = await uow.lock_assignment(assignment.id)
            if assignment is None:
                raise LookupError("Assignment does not exist.")
            require_dispute_allowed(assignment, now=datetime.datetime.now(datetime.UTC))
            await uow.open_assignment_dispute(
                assignment_id=assignment.id,
                performer_id=actor.id,
                command_id=command_id,
                comment=normalized,
            )
            await uow.clear_text_flow(
                member_id=actor.id,
                flow_type="assignment_dispute",
                reference_id=assignment.id,
            )
            updated = await uow.lock_assignment(assignment.id)
            if updated is None:
                raise LookupError("Assignment does not exist.")
            await uow.add_assignment_outbox(
                assignment=updated,
                event_type="assignment_disputed",
                business_key=f"assignment:{assignment.id}:disputed",
            )
            await _finish(uow, update_id, actor.id, updated)
            return updated

    async def finalize_review(
        self, *, assignment_id: UUID, command_id: UUID, now: datetime.datetime
    ) -> Assignment:
        """Autoconfirm one submitted result at the exact review boundary."""
        async with self._unit_of_work_factory() as uow:
            assignment = await uow.get_assignment(assignment_id)
            if assignment is None:
                raise LookupError("Assignment does not exist.")
            await uow.acquire_assignment_task_gate(assignment.task_id)
            task = await uow.lock_task(assignment.task_id)
            assignment = await uow.lock_assignment(assignment.id)
            if assignment is None or task is None:
                raise LookupError("Assignment task does not exist.")
            if assignment.status is not AssignmentStatus.SUBMITTED:
                return assignment
            if assignment.review_deadline_at is None or now < assignment.review_deadline_at:
                raise AssignmentError("Assignment review deadline has not arrived.")
            if task.origin == "community":
                reviewer = (
                    None
                    if task.reviewer_admin_id is None
                    else (await uow.lock_members((task.reviewer_admin_id,))).get(
                        task.reviewer_admin_id
                    )
                )
                if (
                    reviewer is None
                    or reviewer.role is not MemberRole.ADMINISTRATOR
                    or reviewer.status is not MemberStatus.ACTIVE
                    or reviewer.id in {task.created_by_admin_id, assignment.performer_id}
                ):
                    updated = await uow.mark_reviewer_required(assignment.id)
                    await uow.add_assignment_outbox(
                        assignment=updated,
                        event_type="reviewer_required",
                        business_key=f"assignment:{assignment.id}:reviewer_required",
                    )
                    await uow.commit()
                    return updated
            reward_builder = earn_community_reward if task.origin == "community" else earn_reward
            prepared = await uow.economy.prepare_batch(
                (
                    reward_builder(
                        member_id=assignment.performer_id,
                        amount=task.credit_reward_per_performer,
                        idempotency_key=f"assignment:{assignment.id}:approved:reward",
                        task_id=task.id,
                        assignment_id=assignment.id,
                    ),
                )
            )
            updated = await uow.set_assignment_decision(
                assignment_id=assignment.id,
                status=AssignmentStatus.APPROVED,
                command_id=command_id,
                outcome="autoconfirmed",
                now=now,
            )
            await prepared.apply()
            await uow.append_assignment_reliability(
                assignment.id, "approved", None, "review_deadline"
            )
            await uow.recompute_interaction_alert(assignment.id)
            await uow.add_assignment_outbox(
                assignment=updated,
                event_type="assignment_autoconfirmed",
                business_key=f"assignment:{assignment.id}:approved",
            )
            await _update_task_aggregate(uow, task.id, task.performer_slots, now, task.deadline_at)
            await uow.commit()
            return updated

    async def finalize_rejection(
        self, *, assignment_id: UUID, command_id: UUID, now: datetime.datetime
    ) -> Assignment:
        """Finalize an undisputed rejection and refund its member-task slot."""
        async with self._unit_of_work_factory() as uow:
            assignment = await uow.get_assignment(assignment_id)
            if assignment is None:
                raise LookupError("Assignment does not exist.")
            await uow.acquire_assignment_task_gate(assignment.task_id)
            task = await uow.lock_task(assignment.task_id)
            assignment = await uow.lock_assignment(assignment.id)
            if assignment is None or task is None:
                raise LookupError("Assignment task does not exist.")
            if assignment.status is not AssignmentStatus.REJECTED_PENDING_DISPUTE:
                return assignment
            if (
                assignment.reject_dispute_deadline_at is None
                or now < assignment.reject_dispute_deadline_at
            ):
                raise AssignmentError("Assignment dispute deadline has not arrived.")
            prepared = None
            if task.creator_id is not None:
                prepared = await uow.economy.prepare_batch(
                    (
                        refund_reward(
                            member_id=task.creator_id,
                            amount=task.credit_reward_per_performer,
                            idempotency_key=f"assignment:{assignment.id}:rejected:refund",
                            task_id=task.id,
                            assignment_id=assignment.id,
                        ),
                    )
                )
            updated = await uow.set_assignment_decision(
                assignment_id=assignment.id,
                status=AssignmentStatus.REJECTED,
                command_id=command_id,
                outcome="rejected",
                now=now,
            )
            if prepared is not None:
                await prepared.apply()
            await uow.append_assignment_reliability(
                assignment.id, "rejected", None, "dispute_deadline"
            )
            await uow.add_assignment_outbox(
                assignment=updated,
                event_type="assignment_rejected",
                business_key=f"assignment:{assignment.id}:rejected",
            )
            await _update_task_aggregate(uow, task.id, task.performer_slots, now, task.deadline_at)
            await uow.commit()
            return updated

    async def finalize_deadline(
        self, *, task_id: UUID, command_id: UUID, now: datetime.datetime
    ) -> tuple[Assignment, ...]:
        """Mark accepted slots no-show and refund each unearned member reserve."""
        async with self._unit_of_work_factory() as uow:
            await uow.acquire_assignment_task_gate(task_id)
            task = await uow.lock_task(task_id)
            if task is None:
                raise LookupError("Task does not exist.")
            if now < task.deadline_at:
                raise AssignmentError("Task deadline has not arrived.")
            assignments = await uow.list_task_assignments(task.id, for_update=True)
            pending = tuple(
                item for item in assignments if item.status is AssignmentStatus.ACCEPTED
            )
            commands = ()
            if task.creator_id is not None:
                refunds = [
                    refund_reward(
                        member_id=task.creator_id,
                        amount=task.credit_reward_per_performer,
                        idempotency_key=f"assignment:{item.id}:no_show:refund",
                        task_id=task.id,
                        assignment_id=item.id,
                    )
                    for item in pending
                ]
                latest_by_slot: dict[int, Assignment] = {}
                for item in assignments:
                    latest_by_slot[item.slot_number] = item
                occupied_slots = sum(
                    item.status is not AssignmentStatus.CANCELLED
                    for item in latest_by_slot.values()
                )
                unfilled_slots = task.performer_slots - occupied_slots
                if unfilled_slots:
                    refunds.append(
                        refund_reward(
                            member_id=task.creator_id,
                            amount=task.credit_reward_per_performer * unfilled_slots,
                            idempotency_key=f"task:{task.id}:unfilled:refund",
                            task_id=task.id,
                        )
                    )
                commands = tuple(refunds)
            prepared = None if not commands else await uow.economy.prepare_batch(commands)
            updated: list[Assignment] = []
            for item in pending:
                terminal = await uow.set_assignment_decision(
                    assignment_id=item.id,
                    status=AssignmentStatus.NO_SHOW,
                    command_id=UUID(int=command_id.int ^ item.id.int),
                    outcome="no_show",
                    now=now,
                )
                await uow.append_assignment_reliability(item.id, "no_show", None, "task_deadline")
                await uow.add_assignment_outbox(
                    assignment=terminal,
                    event_type="assignment_no_show",
                    business_key=f"assignment:{item.id}:no_show",
                )
                updated.append(terminal)
            if prepared is not None:
                await prepared.apply()
            await _update_task_aggregate(uow, task.id, task.performer_slots, now, task.deadline_at)
            await uow.commit()
            return tuple(updated)


async def _begin(uow: AssignmentUnitOfWork, update_id: int) -> str | None:
    await uow.acquire_update_gate(update_id)
    return await uow.get_receipt_outcome(update_id)


async def _actor(uow: AssignmentUnitOfWork, telegram_user_id: int) -> Member:
    actor = await uow.get_member_by_telegram_user_id(telegram_user_id)
    if actor is None or actor.status is not MemberStatus.ACTIVE:
        raise PermissionError("Only an active member can use assignment workflows.")
    return actor


async def _finish(
    uow: AssignmentUnitOfWork, update_id: int, actor_id: UUID, assignment: Assignment
) -> None:
    await uow.add_receipt(
        update_id=update_id,
        update_type="assignment_workflow",
        actor_id=actor_id,
        outcome_code=f"assignment:{assignment.id}",
    )
    await uow.commit()


async def _assignment_replay(uow: AssignmentUnitOfWork, outcome: str) -> Assignment:
    marker, separator, raw_id = outcome.partition(":")
    if marker != "assignment" or not separator:
        raise AssignmentError("Telegram update belongs to another operation.")
    assignment = await uow.get_assignment(UUID(raw_id))
    if assignment is None:
        raise LookupError("Stored assignment outcome does not exist.")
    return assignment


async def _draft_replay(uow: AssignmentUnitOfWork, outcome: str) -> SubmissionDraft:
    marker, separator, raw_id = outcome.partition(":")
    if marker != "draft" or not separator:
        raise AssignmentError("Telegram update belongs to another operation.")
    draft = await uow.get_submission_draft(UUID(raw_id))
    if draft is None:
        raise LookupError("Stored submission draft does not exist.")
    return draft


async def _result_replay(uow: AssignmentUnitOfWork, outcome: str) -> ResultVersion:
    marker, separator, raw_id = outcome.partition(":")
    if marker != "result" or not separator:
        raise AssignmentError("Telegram update belongs to another operation.")
    result = await uow.get_assignment_result(UUID(raw_id))
    if result is None:
        raise LookupError("Stored submission result does not exist.")
    return result


async def _update_task_aggregate(
    uow: AssignmentUnitOfWork,
    task_id: UUID,
    performer_slots: int,
    now: datetime.datetime,
    deadline: datetime.datetime,
) -> None:
    """Derive the task lifecycle only from locked latest slot states."""
    history = await uow.list_task_assignments(task_id, for_update=True)
    latest_by_slot: dict[int, Assignment] = {}
    for assignment in history:
        latest_by_slot[assignment.slot_number] = assignment
    latest = tuple(latest_by_slot.values())
    active = {
        AssignmentStatus.ACCEPTED,
        AssignmentStatus.SUBMITTED,
        AssignmentStatus.REJECTED_PENDING_DISPUTE,
        AssignmentStatus.DISPUTED,
        AssignmentStatus.REVIEWER_REQUIRED,
    }
    if any(item.status in active for item in latest) or (
        now < deadline and len(latest_by_slot) < performer_slots
    ):
        status = TaskStatus.PUBLISHED if now < deadline else TaskStatus.SETTLING
    else:
        paid = sum(
            item.status in {AssignmentStatus.APPROVED, AssignmentStatus.PARTIALLY_APPROVED}
            for item in latest
        )
        if paid == performer_slots:
            status = TaskStatus.COMPLETED
        elif paid:
            status = TaskStatus.PARTIALLY_COMPLETED
        else:
            status = TaskStatus.EXPIRED
    await uow.save_task_status(task_id=task_id, status=status)
