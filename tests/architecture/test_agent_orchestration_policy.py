from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import NoReturn


ROOT = Path(__file__).parents[2]
CONFIG_PATH = ROOT / "agents" / "config.yaml"
GLOBAL_PROFILES = {
    "luna_explorer",
    "luna_worker",
    "sol_developer",
    "sol_reviewer",
}
EXECUTION_BUDGET_KEYS = {
    "checkpoint_calls",
    "descendant_agents_allowed",
    "hard_calls",
    "hard_minutes",
    "max_child_agents",
    "max_auto_extensions",
    "max_followups_per_child",
    "max_fresh_context_handoffs",
    "max_total_threads_including_root",
    "max_unchanged_state_checks",
    "min_state_check_interval",
}
EXPECTED_ROUTES = {
    "jira_work": ("docs/AGENT_WORKFLOW.md", "docs/JIRA_WORKFLOW.md"),
    "product_behavior": ("docs/mvp/README.md", "docs/mvp/01_PRODUCT_REQUIREMENTS.md"),
    "domain_rules": ("docs/mvp/02_DOMAIN_RULES.md",),
    "technology_or_architecture": (
        "docs/mvp/TECH_STACK.md",
        "docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md",
        "docs/adr/README.md",
    ),
    "multi_agent_work": (
        "docs/AGENT_CONTEXT_AND_COST_POLICY.md",
        "agents/README.md",
        "agents/config.yaml",
        "agents/workflow.yaml",
    ),
    "telegram_live": ("docs/operations/PILOT_RUNBOOK.md",),
    "release_or_deployment": (
        "docs/release-2/README.md",
        "docs/operations/PILOT_RUNBOOK.md",
    ),
}
EXPECTED_CONTINUATION_REFS = {
    "max_auto_extensions": "codex.agent-budget.v1#/continuation/max_auto_extensions",
    "max_fresh_context_handoffs": (
        "codex.agent-budget.v1#/continuation/max_fresh_context_handoffs"
    ),
    "progress_evidence": "codex.agent-budget.v1#/continuation/progress_evidence_any_of",
    "initial_state": "codex.agent-budget.v1#/continuation/initial_state",
    "terminal_states": "codex.agent-budget.v1#/continuation/terminal_states",
    "states": "codex.agent-budget.v1#/continuation/states",
    "decision_owner": "codex.agent-budget.v1#/continuation/decision_owner",
}
EXPECTED_CONSUMERS = {
    "AGENTS.md",
    "agents/workflow.yaml",
    "agents/README.md",
    "agents/developer/instruction.md",
    "agents/analyst-architect/instruction.md",
    "agents/plan-reviewer/instruction.md",
    "agents/final-review/instruction.md",
    "docs/AGENT_CONTEXT_AND_COST_POLICY.md",
    "docs/AGENT_WORKFLOW.md",
    "docs/PROJECT_RULES_AND_GUARDRAILS_RU.md",
}
EXPECTED_PACKET_FIELDS = {
    "task": {
        "issue_key",
        "objective",
        "scope",
        "acceptance",
        "relevant_paths",
        "known_state",
        "progress_evidence",
        "next_action",
    },
    "review": {
        "issue_snapshot",
        "acceptance",
        "diff_summary",
        "verification",
        "risks",
        "source_links",
    },
    "jira_snapshot": {
        "issue_key",
        "status",
        "acceptance",
        "dependencies",
        "updated_at",
    },
}

YamlMap = dict[str, object]


def _fail(message: str) -> NoReturn:
    raise ValueError(message)


def _mapping(value: object) -> YamlMap:
    if not isinstance(value, dict):
        _fail(f"expected mapping, got {type(value).__name__}")
    return cast("YamlMap", value)


def _sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        _fail(f"expected list, got {type(value).__name__}")
    return cast("list[object]", value)


def _load_config() -> YamlMap:
    return _mapping(yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")))


def _walk(node: object, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], object]]:
    yield path, node
    if isinstance(node, dict):
        for key, value in cast("YamlMap", node).items():
            yield from _walk(value, (*path, key))
    elif isinstance(node, list):
        for index, value in enumerate(cast("list[object]", node)):
            yield from _walk(value, (*path, str(index)))


def _validate_budget_node(node: YamlMap, path: tuple[str, ...]) -> None:
    required = {"value", "unit", "min", "max"}
    if not required <= node.keys():
        _fail(f"incomplete budget node at {'/'.join(path)}")
    value = node["value"]
    minimum = node["min"]
    maximum = node["max"]
    numeric_values = (value, minimum, maximum)
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in numeric_values):
        _fail(f"non-integer budget at {'/'.join(path)}")
    value_int = cast("int", value)
    minimum_int = cast("int", minimum)
    maximum_int = cast("int", maximum)
    if not minimum_int <= value_int <= maximum_int:
        _fail(f"budget outside bounds at {'/'.join(path)}")
    if not isinstance(node["unit"], str) or not node["unit"]:
        _fail(f"missing budget unit at {'/'.join(path)}")


def _project_policy(config: YamlMap) -> YamlMap:
    if config.get("schema_version") != 2:
        _fail("agents/config.yaml must use schema version 2")
    policy = _mapping(config["orchestration_policy"])
    if policy.get("policy_id") != "community_bot.orchestration.v2":
        _fail("unexpected project orchestration policy id")

    external = _mapping(policy["external_execution_policy"])
    if external.get("policy_id") != "codex.agent-budget.v1":
        _fail("unexpected global execution policy id")
    if external.get("locator") != "windows_user_profile/.codex/policies/agent-budget.yaml":
        _fail("unexpected global execution policy locator")
    if external.get("locator_resolution") != "[Environment]::GetFolderPath('UserProfile')":
        _fail("unexpected global execution policy locator resolution")
    expected_command = (
        'powershell -NoProfile -Command "& ([IO.Path]::Combine('
        "[Environment]::GetFolderPath('UserProfile'), '.codex', 'tools', "
        "'Get-CodexTokenAudit.ps1')) -ValidatePolicy -Hours 1 -Json\""
    )
    if external.get("validation_command") != expected_command:
        _fail("unexpected global execution policy validation command")
    if set(_sequence(external["required_profiles"])) != GLOBAL_PROFILES:
        _fail("global profile contract drifted")
    if external.get("repository_execution_budget_values") != "forbidden":
        _fail("repository execution budget values must be forbidden")
    return policy


def _validate_budget_contract(policy: YamlMap) -> None:
    for path, value in _walk(policy):
        if path and path[-1] in EXECUTION_BUDGET_KEYS and not isinstance(value, str):
            _fail(f"local execution budget found at {'/'.join(path)}")
        if isinstance(value, dict) and {"value", "unit", "min", "max"} <= value.keys():
            _validate_budget_node(_mapping(value), path)


def _validate_document_routing(policy: YamlMap, root: Path) -> None:
    routing = _mapping(policy["document_routing"])
    startup = [root / cast("str", item) for item in _sequence(routing["startup_documents"])]
    if any(not path.is_file() for path in startup):
        _fail("startup document does not exist")
    estimated_tokens = round(
        sum(len(path.read_text(encoding="utf-8").split()) for path in startup) * 1.3
    )
    startup_limit = _mapping(routing["startup_estimated_tokens_limit"])["value"]
    if not isinstance(startup_limit, int) or estimated_tokens > startup_limit:
        _fail("startup documents exceed their estimated token budget")
    routes = _mapping(routing["conditional_routes"])
    if routes.keys() != EXPECTED_ROUTES.keys():
        _fail("conditional route set drifted")
    for route_name, expected_documents in EXPECTED_ROUTES.items():
        actual_documents = tuple(cast("str", item) for item in _sequence(routes[route_name]))
        if actual_documents != expected_documents:
            _fail(f"conditional route drifted: {route_name}")
        for document in actual_documents:
            if not (root / document).is_file():
                _fail(f"conditional document does not exist: {document}")


def _validate_role_routing(policy: YamlMap) -> None:
    roles = _mapping(policy["role_routing"])
    expected_roles = {
        "developer": ("sol_developer", "luna_worker", "sol_developer"),
        "analyst-architect": ("luna_explorer", None, "sol_reviewer"),
        "plan-reviewer": ("sol_reviewer", None, None),
        "final-review": ("sol_reviewer", None, None),
    }
    for role_name, expected in expected_roles.items():
        role = _mapping(roles[role_name])
        actual = (
            role.get("default_profile"),
            role.get("bounded_profile"),
            role.get("escalation_profile"),
        )
        if actual != expected:
            _fail(f"role routing drifted: {role_name}")


def _validate_packets(policy: YamlMap) -> None:
    for packet_name, expected_fields in EXPECTED_PACKET_FIELDS.items():
        packet = _mapping(_mapping(policy["packets"])[packet_name])
        if set(_sequence(packet["required_fields"])) != expected_fields:
            _fail(f"packet fields drifted: {packet_name}")

    continuation = _mapping(policy["continuation"])
    if continuation.keys() != {"external_policy_refs", "handoff_packet"}:
        _fail("project continuation contains a local execution authority")
    refs = _mapping(continuation["external_policy_refs"])
    if refs != EXPECTED_CONTINUATION_REFS:
        _fail("global continuation references drifted")
    expected_packet_ref = "agents/config.yaml#/orchestration_policy/packets/task"
    if continuation.get("handoff_packet") != expected_packet_ref:
        _fail("continuation handoff packet drifted")


def _validate_consumers(policy: YamlMap, root: Path) -> None:
    consumers = set(_sequence(policy["consumers"]))
    if consumers != EXPECTED_CONSUMERS:
        _fail("policy consumer set drifted")
    for consumer in consumers:
        consumer_path = root / cast("str", consumer)
        if not consumer_path.is_file():
            _fail(f"policy consumer does not exist: {consumer}")
        text = consumer_path.read_text(encoding="utf-8")
        if "community_bot.orchestration.v2" not in text and "orchestration_policy" not in text:
            _fail(f"policy consumer does not reference the contract: {consumer}")

    serialized = yaml.safe_dump(policy).lower()
    if "gpt-5.6-terra" in serialized or "xhigh" in serialized:
        _fail("project orchestration defaults to a forbidden runtime profile")


def _validate_policy(config: YamlMap, *, root: Path = ROOT) -> None:
    policy = _project_policy(config)
    _validate_budget_contract(policy)
    _validate_document_routing(policy, root)
    _validate_role_routing(policy)
    _validate_packets(policy)
    _validate_consumers(policy, root)


def test_agent_orchestration_policy_is_valid() -> None:
    _validate_policy(_load_config())


def test_conditional_route_document_drift_is_rejected() -> None:
    config = deepcopy(_load_config())
    policy = _mapping(config["orchestration_policy"])
    routing = _mapping(policy["document_routing"])
    routes = _mapping(routing["conditional_routes"])
    routes["jira_work"] = ["docs/does-not-exist.md"]

    with pytest.raises(ValueError, match="conditional route drifted"):
        _validate_policy(config)


def test_local_execution_budget_is_rejected() -> None:
    config = deepcopy(_load_config())
    policy = _mapping(config["orchestration_policy"])
    policy["max_child_agents"] = {"value": 2, "unit": "agents", "min": 1, "max": 3}

    with pytest.raises(ValueError, match="local execution budget"):
        _validate_policy(config)


def test_local_extension_budget_is_rejected() -> None:
    config = deepcopy(_load_config())
    policy = _mapping(config["orchestration_policy"])
    continuation = _mapping(policy["continuation"])
    refs = _mapping(continuation["external_policy_refs"])
    refs["max_auto_extensions"] = {
        "value": 99,
        "unit": "extensions",
        "min": 0,
        "max": 99,
    }

    with pytest.raises(ValueError, match="local execution budget"):
        _validate_policy(config)


def test_global_policy_locator_drift_is_rejected() -> None:
    config = deepcopy(_load_config())
    policy = _mapping(config["orchestration_policy"])
    external = _mapping(policy["external_execution_policy"])
    external["locator"] = "does-not-exist.yaml"

    with pytest.raises(ValueError, match="policy locator"):
        _validate_policy(config)


def test_missing_required_route_is_rejected() -> None:
    config = deepcopy(_load_config())
    policy = _mapping(config["orchestration_policy"])
    routing = _mapping(policy["document_routing"])
    routes = _mapping(routing["conditional_routes"])
    del routes["multi_agent_work"]

    with pytest.raises(ValueError, match="route set drifted"):
        _validate_policy(config)


def test_global_continuation_reference_drift_is_rejected() -> None:
    config = deepcopy(_load_config())
    policy = _mapping(config["orchestration_policy"])
    continuation = _mapping(policy["continuation"])
    refs = _mapping(continuation["external_policy_refs"])
    refs["states"] = "codex.agent-budget.v1#/continuation/wrong"

    with pytest.raises(ValueError, match="continuation references drifted"):
        _validate_policy(config)


def test_local_continuation_decision_owner_is_rejected() -> None:
    config = deepcopy(_load_config())
    policy = _mapping(config["orchestration_policy"])
    continuation = _mapping(policy["continuation"])
    continuation["decision_owner"] = "root_agent"

    with pytest.raises(ValueError, match="local execution authority"):
        _validate_policy(config)


def test_missing_required_consumer_is_rejected() -> None:
    config = deepcopy(_load_config())
    policy = _mapping(config["orchestration_policy"])
    policy["consumers"] = ["AGENTS.md"]

    with pytest.raises(ValueError, match="consumer set drifted"):
        _validate_policy(config)


def test_project_budget_outside_bounds_is_rejected() -> None:
    config = deepcopy(_load_config())
    policy = _mapping(config["orchestration_policy"])
    limits = _mapping(policy["process_limits"])
    _mapping(limits["technical_attempts_per_problem"])["value"] = 4

    with pytest.raises(ValueError, match="budget outside bounds"):
        _validate_policy(config)
