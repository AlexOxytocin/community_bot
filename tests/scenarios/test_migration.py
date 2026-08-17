from __future__ import annotations

from uuid import uuid4

import pytest

from community_bot.compact_import import classify_rows, logical_signatures


def test_test_run_task_closure_is_synthetic_but_members_stay_public() -> None:
    run_id, member_id, task_id, assignment_id = uuid4(), uuid4(), uuid4(), uuid4()
    transaction_id, event_id = uuid4(), uuid4()
    inventory = classify_rows(
        {
            "test_runs": [{"id": run_id}],
            "test_run_participants": [{"run_id": run_id, "member_id": member_id}],
            "members": [{"id": member_id}],
            "tasks": [{"id": task_id, "test_run_id": run_id}],
            "assignments": [{"id": assignment_id, "task_id": task_id}],
            "account_transactions": [
                {
                    "id": transaction_id,
                    "member_id": member_id,
                    "task_id": task_id,
                    "assignment_id": assignment_id,
                    "reversed_transaction_id": None,
                    "created_by_member_id": None,
                }
            ],
            "outbox_events": [
                {
                    "id": event_id,
                    "aggregate_type": "task",
                    "aggregate_id": task_id,
                }
            ],
        }
    )

    assert inventory.states["members"][(member_id,)] == "public"
    assert inventory.states["tasks"][(task_id,)] == "synthetic"
    assert inventory.states["assignments"][(assignment_id,)] == "synthetic"
    assert inventory.states["account_transactions"][(transaction_id,)] == "synthetic"
    assert inventory.states["outbox_events"][(event_id,)] == "synthetic"


def test_opaque_test_participant_effect_is_ambiguous_and_blocks_import() -> None:
    run_id, first_member, second_member, vote_id = uuid4(), uuid4(), uuid4(), uuid4()
    inventory = classify_rows(
        {
            "test_runs": [{"id": run_id}],
            "test_run_participants": [{"run_id": run_id, "member_id": first_member}],
            "members": [{"id": first_member}, {"id": second_member}],
            "karma_votes": [
                {
                    "id": vote_id,
                    "rater_id": first_member,
                    "target_id": second_member,
                }
            ],
        }
    )

    assert inventory.states["karma_votes"][(vote_id,)] == "ambiguous"
    with pytest.raises(ValueError, match="Ambiguous source rows block import"):
        inventory.require_unambiguous()


def test_public_task_chain_remains_public() -> None:
    member_id, task_id, assignment_id = uuid4(), uuid4(), uuid4()
    inventory = classify_rows(
        {
            "members": [{"id": member_id}],
            "tasks": [{"id": task_id, "test_run_id": None}],
            "assignments": [{"id": assignment_id, "task_id": task_id}],
        }
    )

    assert inventory.counts()["tasks"] == {
        "public": 1,
        "synthetic": 0,
        "ambiguous": 0,
    }
    inventory.require_unambiguous()


def test_logical_checksum_is_order_independent_and_quarantine_is_separate() -> None:
    run_id, public_task, synthetic_task = uuid4(), uuid4(), uuid4()
    rows = {
        "test_runs": [{"id": run_id}],
        "tasks": [
            {"id": public_task, "test_run_id": None},
            {"id": synthetic_task, "test_run_id": run_id},
        ],
    }
    inventory = classify_rows(rows)
    reversed_rows = {**rows, "tasks": list(reversed(rows["tasks"]))}

    forward = logical_signatures(rows)
    reverse = logical_signatures(reversed_rows)
    quarantine = logical_signatures(rows, provenance=inventory, state="synthetic")

    assert forward == reverse
    assert quarantine["tasks"]["count"] == 1
    assert quarantine["tasks"]["sha256"] != forward["tasks"]["sha256"]
