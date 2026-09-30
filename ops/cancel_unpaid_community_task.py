"""Audited, explicitly authorized cancellation of an unpaid community test task.

Dry-run is the default. Refuse every task with economic history: this tool never
issues credits, reverses payments, deletes history, or changes member balances.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, or_, select

from community_bot.bootstrap.settings import get_settings
from community_bot.infrastructure.db.assignments import acquire_task_gate, append_reliability
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AssignmentModel,
    AuditEventModel,
    MemberModel,
    ModerationCaseModel,
    TaskModel,
)

ACTION = "unpaid_community_test_task_cancelled"
REASON = "Owner requested cancellation of a test task without participant fault."


async def cancel(
    database: Database,
    *,
    task_id: UUID,
    expected_title: str,
    apply: bool,
) -> dict[str, object]:
    """Lock the aggregate and cancel only if no economic settlement is necessary."""
    async with database.session_factory.begin() as session:
        await acquire_task_gate(session, task_id)
        task = await session.get(TaskModel, task_id, with_for_update=True)
        if task is None or task.title != expected_title or task.origin != "community":
            raise ValueError("Exact community task identity does not match.")
        assignments = (
            await session.scalars(
                select(AssignmentModel).where(AssignmentModel.task_id == task_id).with_for_update()
            )
        ).all()
        assignment_ids = [item.id for item in assignments]
        ledger_count = await session.scalar(
            select(func.count(AccountTransactionModel.id)).where(
                or_(
                    AccountTransactionModel.task_id == task_id,
                    AccountTransactionModel.assignment_id.in_(assignment_ids),
                ),
            )
        )
        if ledger_count or task.reserved_credit_total or any(a.slot_ever_paid for a in assignments):
            raise ValueError("Task has economic history; cancellation requires a settlement plan.")
        audit = await session.scalar(
            select(AuditEventModel.id).where(
                AuditEventModel.action == ACTION,
                AuditEventModel.entity_id == str(task_id),
            )
        )
        if audit is not None:
            if task.status != "cancelled" or any(a.status != "cancelled" for a in assignments):
                raise ValueError("Previous cancellation receipt conflicts with current state.")
            return {"status": "already_cancelled", "assignments": len(assignments), "refunded": 0}
        if task.status not in {"published", "closed_for_new_performers", "settling"} or any(
            a.status not in {"accepted", "submitted", "reviewer_required"} for a in assignments
        ):
            raise ValueError("Task or assignment is no longer eligible for unpaid cancellation.")
        cases = await session.scalar(
            select(func.count(ModerationCaseModel.id)).where(
                ModerationCaseModel.assignment_id.in_(assignment_ids),
            )
        )
        if cases:
            raise ValueError("Task has moderation history; resolve it through moderation.")
        owners = (
            await session.scalars(
                select(MemberModel)
                .where(
                    MemberModel.status == "active",
                    MemberModel.role == "administrator",
                    MemberModel.permissions_json.contains(["superadministrator"]),
                )
                .with_for_update()
            )
        ).all()
        if len(owners) != 1:
            raise ValueError("A unique active superadministrator is required.")
        before = {
            "task_status": task.status,
            "assignment_statuses": [a.status for a in assignments],
        }
        if not apply:
            return {
                "status": "dry_run",
                "before": before,
                "assignments": len(assignments),
                "ledger_entries": ledger_count,
                "refunded": 0,
            }
        now = datetime.datetime.now(datetime.UTC)
        for assignment in assignments:
            assignment.status = "cancelled"
            assignment.cancelled_at = now
            assignment.reviewed_at = now
            assignment.terminal_outcome = "cancel_without_fault"
            assignment.terminal_command_id = uuid5(NAMESPACE_URL, f"{ACTION}:{assignment.id}")
            await append_reliability(
                session, assignment.id, "cancelled_creator", owners[0].id, REASON
            )
        task.status = "cancelled"
        task.cancelled_at = now
        task.updated_at = now
        result = {"status": "cancelled", "assignments": len(assignments), "refunded": 0}
        session.add(
            AuditEventModel(
                actor_member_id=owners[0].id,
                action=ACTION,
                entity_type="task",
                entity_id=str(task_id),
                before_json=before,
                after_json=result,
                reason=REASON,
            )
        )
        return result


async def run(task_id: UUID, expected_title: str, *, apply: bool) -> dict[str, object]:
    """Use the runtime database configuration without exposing credentials."""
    database = Database(get_settings().database_url)
    try:
        return await cancel(database, task_id=task_id, expected_title=expected_title, apply=apply)
    finally:
        await database.dispose()


def main() -> None:
    """Require exact task identity and explicit apply."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True, type=UUID)
    parser.add_argument("--expected-title", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.task_id, args.expected_title, apply=args.apply))))


if __name__ == "__main__":
    main()
