from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.domain.economy import (
    AdministrativeContext,
    CachedLevel,
    EconomyError,
    ProductConfigCandidate,
    ProductConfigError,
    TransactionType,
    admin_adjustment,
    apply_penalty,
    earn_community_reward,
    earn_partial_reward,
    earn_reward,
    economy_payload_hash,
    refund_reward,
    reserve_reward,
    resolve_level,
    starting_grant,
)

CONFIG_PATH = Path(__file__).parents[2] / "config" / "product-config.v1.json"

if TYPE_CHECKING:
    from collections.abc import Callable


def test_named_economy_factories_produce_exact_deltas_and_metadata() -> None:
    member_id = uuid4()
    actor_id = uuid4()
    context = AdministrativeContext(actor_member_id=actor_id, reason="Correction")

    commands = (
        starting_grant(member_id),
        reserve_reward(member_id=member_id, amount=4, idempotency_key="reserve:1"),
        earn_reward(member_id=member_id, amount=4, idempotency_key="earn:1"),
        refund_reward(member_id=member_id, amount=4, idempotency_key="refund:1"),
        earn_partial_reward(member_id=member_id, amount=2, idempotency_key="partial:1"),
        earn_community_reward(member_id=member_id, amount=3, idempotency_key="community:1"),
        apply_penalty(
            member_id=member_id,
            amount=2,
            idempotency_key="penalty:1",
            context=context,
        ),
        admin_adjustment(
            member_id=member_id,
            credit_delta=1,
            experience_delta=-1,
            idempotency_key="adjustment:1",
            context=context,
        ),
    )

    assert [
        (item.transaction_type, item.credit_delta, item.experience_delta) for item in commands
    ] == [
        (TransactionType.STARTING_GRANT, 5, 0),
        (TransactionType.TASK_REWARD_RESERVED, -4, 0),
        (TransactionType.TASK_REWARD_EARNED, 4, 4),
        (TransactionType.TASK_REWARD_REFUNDED, 4, 0),
        (TransactionType.PARTIAL_TASK_REWARD, 2, 2),
        (TransactionType.COMMUNITY_TASK_REWARD, 3, 3),
        (TransactionType.PENALTY, -2, 0),
        (TransactionType.ADMIN_ADJUSTMENT, 1, -1),
    ]
    assert commands[-1].actor_member_id == actor_id
    assert commands[-1].reason == "Correction"


@pytest.mark.parametrize("amount", [0, -1])
def test_amount_factories_reject_nonpositive_values(amount: int) -> None:
    with pytest.raises(EconomyError, match="positive"):
        earn_reward(member_id=uuid4(), amount=amount, idempotency_key="reward")


def test_starting_grant_has_stable_identity_and_payload_hash() -> None:
    member_id = uuid4()
    command = starting_grant(member_id)

    assert command.idempotency_key == f"starting_grant:{member_id}"
    assert economy_payload_hash(command) == economy_payload_hash(replace(command))


def test_product_config_hash_excludes_config_version_only() -> None:
    first = load_product_config_candidate(CONFIG_PATH)
    second = replace(first, config_version=2)
    level = first.levels[1]
    product_changes = (
        replace(first, interaction_alert_threshold=first.interaction_alert_threshold + 1),
        replace(first, interaction_alert_window_days=first.interaction_alert_window_days + 1),
        replace(
            first,
            levels=(first.levels[0], replace(level, experience_required=11), *first.levels[2:]),
        ),
        replace(
            first,
            levels=(
                first.levels[0],
                replace(level, display_name="Другой уровень"),
                *first.levels[2:],
            ),
        ),
        replace(
            first,
            levels=(first.levels[0], replace(level, description="Описание"), *first.levels[2:]),
        ),
        replace(
            first,
            levels=(
                first.levels[0],
                replace(level, level_up_message="Новый уровень"),
                *first.levels[2:],
            ),
        ),
        replace(
            first,
            levels=(
                first.levels[0],
                replace(level, permissions={"tasks": True}),
                *first.levels[2:],
            ),
        ),
    )

    assert first.content_hash == second.content_hash
    assert all(first.content_hash != changed.content_hash for changed in product_changes)


def test_level_resolver_covers_every_threshold_and_ignores_stale_cache() -> None:
    candidate = load_product_config_candidate(CONFIG_PATH)
    config_id = uuid4()
    stale_id = uuid4()

    for level in candidate.levels:
        resolved = resolve_level(
            experience_total=level.experience_required,
            config_id=config_id,
            config_version=candidate.config_version,
            levels=candidate.levels,
            cache=CachedLevel(level_number=10, config_id=stale_id),
        )
        assert resolved.level_number == level.level_number
        if level.level_number > 1:
            before = resolve_level(
                experience_total=level.experience_required - 1,
                config_id=config_id,
                config_version=candidate.config_version,
                levels=candidate.levels,
            )
            assert before.level_number == level.level_number - 1
    for experience in (1001, 2**40):
        assert (
            resolve_level(
                experience_total=experience,
                config_id=config_id,
                config_version=candidate.config_version,
                levels=candidate.levels,
            ).level_number
            == 10
        )


@given(st.lists(st.tuples(st.sampled_from(("reserve", "refund", "reward")), st.integers(1, 50))))
def test_generated_economy_sequence_preserves_nonnegative_totals(
    operations: list[tuple[str, int]],
) -> None:
    member_id = uuid4()
    credit_total = 10
    experience_total = 0
    for index, (operation, amount) in enumerate(operations):
        if operation == "reserve":
            command = reserve_reward(
                member_id=member_id,
                amount=amount,
                idempotency_key=f"property:{index}",
            )
        elif operation == "refund":
            command = refund_reward(
                member_id=member_id,
                amount=amount,
                idempotency_key=f"property:{index}",
            )
        else:
            command = earn_reward(
                member_id=member_id,
                amount=amount,
                idempotency_key=f"property:{index}",
            )
        next_credit = credit_total + command.credit_delta
        next_experience = experience_total + command.experience_delta
        if next_credit < 0 or next_experience < 0:
            assert (credit_total, experience_total) == (credit_total, experience_total)
            continue
        credit_total = next_credit
        experience_total = next_experience
        assert credit_total >= 0
        assert experience_total >= 0
        if operation in {"reserve", "refund"}:
            assert command.experience_delta == 0


def test_candidate_hash_is_independent_of_json_and_level_order(tmp_path: Path) -> None:
    original = load_product_config_candidate(CONFIG_PATH)
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["levels"].reverse()
    reordered = tmp_path / "reordered.json"
    reordered.write_text(
        json.dumps(payload, ensure_ascii=False, indent=7, sort_keys=True), encoding="utf-8"
    )

    assert load_product_config_candidate(reordered).content_hash == original.content_hash


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update({"unknown": True}), "invalid"),
        (
            lambda payload: payload["levels"][0].update({"display_name": "Level"}),
            "invalid",
        ),
        (
            lambda payload: payload["levels"][1].update({"experience_required": 0}),
            "invalid",
        ),
        (lambda payload: payload.update({"interaction_alert_threshold": -1}), "invalid"),
        (lambda payload: payload.update({"interaction_alert_window_days": 0}), "invalid"),
        (lambda payload: payload.update({"config_version": 0}), "invalid"),
        (lambda payload: payload.update({"schema_version": 2}), "invalid"),
        (lambda payload: payload["levels"].pop(), "invalid"),
        (lambda payload: payload["levels"][1].update({"level_number": 1}), "invalid"),
        (lambda payload: payload["levels"][0].update({"permissions": []}), "invalid"),
    ],
)
def test_product_config_loader_rejects_unknown_non_russian_and_duplicate_thresholds(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    mutation(payload)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ProductConfigError, match=message):
        load_product_config_candidate(path)


def test_empty_level_scale_cannot_resolve() -> None:
    with pytest.raises(ProductConfigError, match="contain levels"):
        resolve_level(
            experience_total=0,
            config_id=uuid4(),
            config_version=1,
            levels=(),
        )


def test_candidate_payload_keeps_identity_metadata() -> None:
    candidate: ProductConfigCandidate = load_product_config_candidate(CONFIG_PATH)

    assert candidate.payload()["config_version"] == candidate.config_version
    assert candidate.payload()["interaction_alert_window_days"] == 7
