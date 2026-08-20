"""Build the planning-only CB-96 presentation contract."""

# ruff: noqa: ARG001, C901, D103, E501, INP001, PERF401, PLR0911, PLR2004, RUF001, S101, T201

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parent
BOARD = ROOT / "design" / "cb93-complete-screen-board.html"
OUTPUT = ROOT / "ui-contract.json"
INVENTORY = ROOT / "ui-inventory.md"

SCREEN_PATTERN = re.compile(
    r"S\('([^']+)','([^']+)','([^']+)','([^']+)','([^']*)','([^']*)','([^']*)'\)"
)

CORRECTIONS = {
    "G08A": {
        "primary": "Включить / выключить",
        "states": "metadata read-only · active/inactive · exact toggle",
    },
    "G09": {
        "title": "Редактор версии шаблона",
        "entry": "G08B",
        "states": "input/result JSON Schema · limits · validation",
    },
    "G19": {"states": "all snapshot fields · slots · reward 1–4 · independent reviewer"},
    "G20": {"states": "role variant · conflict checks · exact revision"},
}

ROUTE_PATTERNS = {
    "start": "#/start",
    "catalog": "#/catalog",
    "task": "#/tasks/:task_id",
    "composer": "#/compose/tasks/:draft_id?",
    "work": "#/work",
    "work_item": "#/work/:resource_id",
    "members": "#/members",
    "member": "#/members/:member_id",
    "profile": "#/profile",
    "moderation": "#/moderation/:case_id?",
    "admin": "#/admin/:resource_type?/:resource_id?",
}

ROOT_SCREENS = ("T01", "M01", "P01", "P06", "S01", "G01")

PARENTS = {
    "A02": "A01",
    "A03": "A01",
    "A04": "A03",
    "A05": "A04",
    "A05A": "A05",
    "A06": "A05A",
    "A06A": "A06",
    "A07": "A01",
    "T02": "T01",
    "T03": "T01",
    "T03A": "T03",
    "T04": "T01",
    "T04A": "T04",
    "T04B": "T04",
    "T05": "T04A",
    "T06": "T05",
    "T07": "T06",
    "T08": "M10",
    "M02": "M01",
    "M03": "M02",
    "M04": "M03",
    "M04A": "M04",
    "M05": "M04",
    "M06": "M05",
    "M07": "M03",
    "M08": "M03",
    "M09": "M01",
    "M10": "M09",
    "M11": "M10",
    "M12": "M11",
    "M13": "M10",
    "M14": "M03",
    "M14A": "M14",
    "M15": "M14",
    "M16": "M15",
    "M17": "M10",
    "M18": "M03",
    "M19": "M17",
    "P02": "P01",
    "P03": "P02",
    "P04": "P02",
    "P05": "P01",
    "P07": "P06",
    "P08": "P06",
    "P09": "P08",
    "P10": "P09",
    "S02": "S01",
    "S03": "S02",
    "S04": "S01",
    "S05": "S01",
    "S06": "S05",
    "S07": "S06",
    "S08": "S01",
    "S09": "S01",
    "S10": "S09",
    "S11": "S01",
    "S12": "S11",
    "G02": "G01",
    "G03": "G02",
    "G04": "G02",
    "G05": "G01",
    "G06": "G05",
    "G07": "G06",
    "G08": "G01",
    "G08A": "G08",
    "G08B": "G08",
    "G09": "G08B",
    "G10": "G01",
    "G11": "G06",
    "G12": "G11",
    "G13": "G01",
    "G14": "G13",
    "G14C": "G14",
    "G14A": "G06",
    "G14B": "G06",
    "G15": "G01",
    "G15A": "G15",
    "G16": "G01",
    "G16A": "G16",
    "G17": "G16",
    "G18": "G16A",
    "G19": "G01",
    "G20": "G19",
    "G21": "G01",
    "G22": "G21",
    "G22A": "G01",
    "G22B": "G22A",
    "G22C": "G22B",
    "G22D": "G22B",
    "G23": "G01",
    "G23A": "G01",
    "G24": "G23",
    "G25": "G24",
    "G26": "G01",
    "G27": "G01",
    "G28": "G27",
}

SUCCESS_TARGETS = {
    "A03": "A04",
    "A04": "A05",
    "A05": "A05A",
    "A05A": "A06",
    "A06A": "A05",
    "T03A": "M03",
    "T05": "T06",
    "T07": "T08",
    "M04": "M05",
    "M06": "M07",
    "M08": "M02",
    "M12": "M13",
    "M14": "M15",
    "M16": "M15",
    "M17": "M19",
    "M18": "M19",
    "P03": "P04",
    "P07": "P06",
    "S03": "S04",
    "S07": "S05",
    "S08": "S09",
    "S10": "S10",
    "S12": "S02",
    "G03": "G04",
    "G04": "G02",
    "G07": "G06",
    "G08A": "G08A",
    "G09": "G08B",
    "G11": "G12",
    "G12": "G14B",
    "G14C": "G14",
    "G17": "G16A",
    "G18": "G16A",
    "G19": "G20",
    "G20": "T03",
    "G22": "T03",
    "G22B": "M13",
    "G22C": "G22A",
    "G22D": "M03",
    "G24": "G24",
    "G25": "G24",
    "G26": "G26",
    "G28": "M15",
}

# Closed action classification. No class authorizes a new endpoint or adapter.
EXISTING_HTTP_CONNECTED = {
    "A01",
    "A02",
    "T01",
    "T03",
    "T03A",
    "T07",
    "T08",
    "M01",
    "M03",
    "M04",
    "M06",
    "M07",
    "M08",
    "M09",
    "M10",
    "M11",
    "M12",
    "M13",
    "M14",
    "M14A",
    "M15",
    "P01",
    "P02",
    "P03",
    "P04",
    "P05",
    "P06",
    "P07",
    "S01",
    "S02",
    "S03",
    "S04",
}

UI_LOCAL_ONLY = {"A07", "T02", "T04", "T04B", "T05", "T06", "M02", "M05", "P08"}
SUCCESS_SCREEN_IDS = {"T08", "M07", "M13", "P04", "S04"}

CAPABILITIES = {
    "AUTH": ["A01", "A02", "A07"],
    "REGISTRATION": ["A03", "A04", "A05", "A05A", "A06", "A06A", "S05", "S06", "S07"],
    "MEMBERS": ["P01", "P02", "P06", "P07", "G05", "G06", "G07"],
    "CATALOG_CONFIG": ["T04A", "T05", "M04", "G08", "G09"],
    "MEMBER_TASKS": ["T04", "T05", "T06", "T07", "T08", "M09", "M10"],
    "GROUP_TASKS": ["T04", "T05", "M10", "M17", "M18", "M19"],
    "COMMUNITY_TASKS": ["G19", "G20", "G21", "G22", "G22A", "G22B", "G22C", "G22D", "T01", "T03"],
    "ASSIGNMENT_LIFECYCLE": [
        "T03A",
        "M02",
        "M03",
        "M04",
        "M05",
        "M06",
        "M07",
        "M08",
        "M11",
        "M12",
        "M13",
    ],
    "DEADLINES": ["T03", "M03", "M07", "M11", "M14"],
    "ECONOMY": ["P08", "P09", "P10", "G11", "G12", "G14B"],
    "REVERSALS": ["G12", "G28", "S12"],
    "LEVELS_LEADERBOARD": ["P05", "P06", "P08", "G16A"],
    "KARMA": ["P02", "P03", "P04", "G13", "G14", "G14C"],
    "RELIABILITY": ["P02", "P06", "G14A", "G28"],
    "DISPUTES": ["M14", "M14A", "M15", "S01", "S02", "S03", "S04"],
    "APPEALS": ["M16", "G27", "G28"],
    "SANCTIONS": ["A07", "S08", "S09", "S10"],
    "RISK_ALERTS": ["G23", "G23A", "G24", "G25"],
    "CONFLICTS": ["S02", "S03", "G19", "G20", "G21", "G22", "G27", "G28"],
    "NOTIFICATIONS": ["A01", "M03", "M11", "M15", "M18", "G22A"],
    "AUDIT_IDEMPOTENCY": ["G15", "G15A"],
    "TASK_CREATION_DRAFT": ["T04B", "T05", "T06", "T07", "T08"],
    "SUBMISSION_DRAFT": ["M04", "M05", "M06", "M07"],
    "MODERATION_DRAFT": ["S03", "S04", "G28"],
    "FULL_IMPORT": [],
    "MINI_APP_REACHABILITY": ["A01", "A02"],
}

# Only explicit product/user edges from the approved concept-05 board and
# key-flow map. Back/reload/deep-link/system-state rules are invariants below,
# not hundreds of synthetic edges.
PRODUCT_EDGES = [
    # Launch/onboarding/status.
    ("A01", "A02", "auth_failure", "replace", "auth_state", "error"),
    ("A01", "A03", "valid_invitation", "replace", "invitation_present", "content"),
    ("A01", "A07", "restricted_status", "replace", "status_restricted", "permission_closed"),
    ("A01", "T01", "active_member", "replace", "member_active", "loading"),
    ("A03", "A04", "continue", "push", "fixture_or_connection", "content"),
    ("A04", "A05", "accept_consent", "push", "fixture_or_connection", "content"),
    ("A05", "A05A", "preview_application", "push", "fixture_or_connection", "content"),
    ("A05A", "A06", "submit_application", "replace", "fixture_or_connection", "success"),
    ("A06", "T01", "registration_approved", "replace", "fresh_status", "loading"),
    ("A06", "A06A", "registration_rejected", "replace", "fresh_status", "content"),
    ("A06A", "A05", "reopen_application", "replace", "fixture_or_connection", "content"),
    # Catalog/task creation.
    ("T01", "T02", "open_filters", "push", "local_navigation", "content"),
    ("T01", "T03", "open_task", "push", "resource_available", "loading"),
    ("T01", "T04", "create_task", "push", "member_active", "content"),
    ("T03", "T03A", "accept_task", "push", "action_available", "confirm"),
    ("T04", "T04A", "choose_template_path", "push", "local_navigation", "content"),
    ("T04", "T04B", "resume_draft_path", "push", "local_navigation", "content"),
    ("T04A", "T05", "use_template_or_freeform", "push", "local_navigation", "content"),
    ("T04B", "T05", "resume_draft", "push", "local_navigation", "content"),
    ("T05", "T06", "preview_task", "push", "valid_local_form", "content"),
    ("T06", "T07", "publish_task", "push", "action_available", "confirm"),
    ("T07", "T08", "authoritative_publish_success", "replace", "authoritative_outcome", "success"),
    ("T08", "M10", "open_published_task", "replace", "resource_available", "loading"),
    # Assignment/result/review/dispute/appeal.
    ("T03A", "M03", "authoritative_accept_success", "replace", "authoritative_outcome", "loading"),
    ("M01", "M02", "open_accepted_tab", "stay", "local_navigation", "content"),
    ("M01", "M09", "open_created_tab", "stay", "local_navigation", "content"),
    ("M02", "M03", "open_assignment", "push", "resource_available", "loading"),
    ("M03", "M04", "create_or_extend_submission", "push", "action_available", "content"),
    ("M03", "M08", "withdraw_assignment", "push", "action_available", "content"),
    ("M04", "M04A", "open_result_versions", "push", "versions_available", "content"),
    ("M04A", "M04", "continue_submission", "pop", "local_navigation", "content"),
    ("M04", "M05", "preview_result", "push", "valid_local_form", "content"),
    ("M05", "M06", "submit_result", "push", "action_available", "confirm"),
    ("M06", "M07", "authoritative_submit_success", "replace", "authoritative_outcome", "success"),
    ("M07", "M03", "open_assignment", "replace", "resource_available", "loading"),
    ("M08", "M02", "withdrawal_outcome", "replace", "authoritative_outcome", "loading"),
    ("M09", "M10", "open_created_task", "push", "resource_available", "loading"),
    ("M10", "M11", "open_review", "push", "review_available", "loading"),
    ("M11", "M12", "choose_review_decision", "push", "action_available", "content"),
    ("M12", "M13", "authoritative_review_success", "replace", "authoritative_outcome", "success"),
    ("M13", "M10", "open_created_task", "replace", "resource_available", "loading"),
    ("M13", "M03", "open_assignment", "replace", "resource_available", "loading"),
    ("M13", "M14", "open_reject_dispute", "push", "rejected_outcome", "content"),
    ("M14", "M14A", "open_dispute_materials", "push", "resource_available", "content"),
    ("M14A", "M15", "open_dispute_status", "replace", "resource_available", "loading"),
    ("M15", "M16", "open_appeal", "push", "appeal_available", "content"),
    ("M16", "G27", "submit_appeal", "replace", "fixture_or_connection", "loading"),
    ("G27", "G28", "open_appeal", "push", "resource_available", "loading"),
    ("G28", "M15", "open_dispute_outcome", "replace", "resource_available", "loading"),
    ("G28", "M03", "open_assignment_outcome", "replace", "resource_available", "loading"),
    # Group cancellation.
    ("M10", "M17", "request_group_cancellation", "push", "action_available", "content"),
    ("M17", "M18", "notify_performer_response", "replace", "fixture_or_connection", "content"),
    ("M18", "M19", "save_cancellation_response", "replace", "fixture_or_connection", "content"),
    ("M19", "M10", "open_created_task_outcome", "replace", "resource_available", "loading"),
    ("M19", "M03", "open_assignment_outcome", "replace", "resource_available", "loading"),
    # Participants/profile/economy.
    ("P01", "P02", "open_member", "push", "resource_available", "loading"),
    ("P01", "P05", "open_leaderboard", "stay", "local_navigation", "loading"),
    ("P02", "P03", "rate_karma", "push", "karma_eligible", "content"),
    ("P03", "P04", "authoritative_karma_success", "replace", "authoritative_outcome", "success"),
    ("P04", "P02", "return_to_member", "replace", "resource_available", "loading"),
    ("P06", "P07", "edit_profile", "push", "self", "content"),
    ("P06", "P08", "open_balance", "push", "self", "content"),
    ("P07", "P06", "authoritative_profile_success", "replace", "authoritative_outcome", "loading"),
    ("P08", "P09", "open_ledger", "push", "resource_available", "loading"),
    ("P09", "P10", "open_operation", "push", "resource_available", "loading"),
    # Moderation/registration/fraud/sanctions.
    ("S01", "S02", "open_case", "push", "case_available", "loading"),
    ("S02", "S03", "preview_resolution", "push", "action_available", "content"),
    (
        "S03",
        "S04",
        "authoritative_resolution_success",
        "replace",
        "authoritative_outcome",
        "success",
    ),
    ("S04", "S01", "return_to_case_queue", "replace", "staff_allowed", "loading"),
    ("S01", "S05", "open_registration_queue", "stay", "staff_allowed", "loading"),
    ("S05", "S06", "open_application", "push", "resource_available", "loading"),
    ("S06", "S07", "choose_registration_decision", "push", "action_available", "content"),
    ("S07", "S05", "registration_decision_outcome", "replace", "fixture_or_connection", "loading"),
    ("S01", "S11", "open_paid_assignments", "stay", "admin_allowed", "loading"),
    ("S11", "S12", "open_fraud_case", "push", "resource_available", "content"),
    ("S12", "S02", "fraud_case_created", "replace", "fixture_or_connection", "loading"),
    ("G06", "S08", "issue_sanction", "push", "sanction_allowed", "content"),
    ("S02", "S08", "issue_case_sanction", "push", "sanction_allowed", "content"),
    ("S08", "S09", "sanction_saved_to_list", "replace", "fixture_or_connection", "loading"),
    ("S08", "S10", "sanction_saved_to_detail", "replace", "fixture_or_connection", "loading"),
    ("S09", "S10", "open_sanction", "push", "resource_available", "loading"),
    # Administration/config/community/alerts.
    ("G01", "G02", "open_invitations", "push", "capability_visible", "loading"),
    ("G02", "G03", "create_invitation", "push", "action_available", "content"),
    ("G02", "G04", "open_invitation", "push", "resource_available", "loading"),
    ("G01", "G05", "open_member_admin", "push", "capability_visible", "loading"),
    ("G05", "G06", "open_admin_member", "push", "resource_available", "loading"),
    ("G06", "G07", "change_role_or_status", "push", "action_available", "content"),
    ("G01", "G08", "open_catalog_admin", "push", "capability_visible", "loading"),
    ("G08", "G08A", "open_category", "push", "resource_available", "loading"),
    ("G08", "G08B", "open_template", "push", "resource_available", "loading"),
    ("G08B", "G09", "create_template_version", "push", "action_available", "content"),
    ("G01", "G10", "open_all_tasks", "push", "capability_visible", "loading"),
    ("G06", "G11", "correct_member_ledger", "push", "action_available", "content"),
    ("G14B", "G11", "correct_ledger", "push", "action_available", "content"),
    ("G11", "G12", "preview_ledger_change", "push", "valid_local_form", "confirm"),
    ("G12", "G14B", "ledger_change_outcome", "replace", "fixture_or_connection", "loading"),
    ("G01", "G13", "open_raw_karma", "push", "capability_visible", "loading"),
    ("G13", "G14", "open_karma_vote", "push", "resource_available", "loading"),
    ("G14", "G14C", "moderate_karma_version", "push", "action_available", "content"),
    ("G06", "G14A", "open_reliability_history", "push", "resource_available", "loading"),
    ("G06", "G14B", "open_member_ledger", "push", "resource_available", "loading"),
    ("G01", "G15", "open_audit", "push", "capability_visible", "loading"),
    ("G15", "G15A", "open_audit_record", "push", "resource_available", "loading"),
    ("G01", "G16", "open_config_versions", "push", "capability_visible", "loading"),
    ("G16", "G16A", "open_config_version", "push", "resource_available", "loading"),
    ("G16", "G17", "upload_config", "push", "action_available", "content"),
    ("G16A", "G18", "activate_config", "push", "action_available", "confirm"),
    ("G17", "G18", "activate_validated_config", "push", "valid_local_form", "confirm"),
    ("G01", "G19", "create_community_task", "push", "capability_visible", "content"),
    ("G19", "G20", "preview_community_task", "push", "valid_local_form", "content"),
    ("G20", "T03", "super_publish_success", "replace", "super_allowed", "loading"),
    ("G20", "G21", "request_super_approval", "replace", "admin_not_super", "loading"),
    ("G21", "G22", "open_publication_request", "push", "resource_available", "loading"),
    ("G22", "T03", "publication_approved", "replace", "fixture_or_connection", "loading"),
    ("G01", "G22A", "open_community_reviews", "push", "capability_visible", "loading"),
    ("G22A", "G22B", "open_community_result", "push", "resource_available", "loading"),
    ("G22B", "M12", "choose_community_decision", "push", "action_available", "content"),
    (
        "G22B",
        "M13",
        "open_community_outcome",
        "replace",
        "authoritative_or_fixture_outcome",
        "success",
    ),
    ("G22B", "G22C", "replace_invalid_reviewer", "push", "reviewer_invalid", "content"),
    ("G22B", "G22D", "cancel_community_assignment", "push", "action_available", "content"),
    ("G01", "G23", "open_interaction_alerts", "push", "capability_visible", "loading"),
    ("G01", "G23A", "open_risk_signals", "push", "capability_visible", "loading"),
    ("G23", "G24", "open_interaction_alert", "push", "resource_available", "loading"),
    (
        "G24",
        "G24",
        "save_legitimate_or_monitor_outcome",
        "replace",
        "fixture_or_connection",
        "content",
    ),
    ("G24", "G25", "choose_penalty", "push", "penalty_outcome_selected", "content"),
    ("G25", "G24", "penalty_outcome_saved", "replace", "fixture_or_connection", "content"),
    ("G01", "G26", "open_administrators", "push", "super_allowed", "loading"),
    ("G01", "G27", "open_appeals", "push", "capability_visible", "loading"),
]

REQUIRED_KEY_EDGES = {
    ("T04B", "T05"),
    ("T08", "M10"),
    ("M07", "M03"),
    ("M13", "M10"),
    ("M13", "M03"),
    ("M13", "M14"),
    ("M17", "M18"),
    ("M19", "M10"),
    ("M19", "M03"),
    ("P04", "P02"),
    ("S04", "S01"),
    ("G17", "G18"),
    ("G20", "G21"),
    ("G22B", "M12"),
    ("G06", "S08"),
    ("S02", "S08"),
}

FORBIDDEN_EDGES = {
    ("T08", "T07", "back"),
    ("M07", "M06", "back"),
    ("M13", "M12", "back"),
    ("P04", "P03", "back"),
    ("S04", "S03", "back"),
}


def route_key(screen_id: str) -> str:
    if screen_id.startswith("A"):
        return "start"
    if screen_id in {"T01", "T02"}:
        return "catalog"
    if screen_id in {"T03", "T03A"}:
        return "task"
    if screen_id.startswith("T"):
        return "composer"
    if screen_id in {"M01", "M02", "M09"}:
        return "work"
    if screen_id.startswith("M"):
        return "work_item"
    if screen_id in {"P01", "P05"}:
        return "members"
    if screen_id in {"P02", "P03", "P04"}:
        return "member"
    if screen_id.startswith("P"):
        return "profile"
    if screen_id.startswith("S"):
        return "moderation"
    return "admin"


def connection_class(screen_id: str) -> str:
    if screen_id not in SUCCESS_TARGETS:
        return "ui_local_only"
    if screen_id in EXISTING_HTTP_CONNECTED:
        return "existing_http_connected"
    if screen_id in UI_LOCAL_ONLY:
        return "ui_local_only"
    return "disabled_unavailable"


def data_mode(screen_id: str) -> str:
    if screen_id in EXISTING_HTTP_CONNECTED:
        return "existing_http_connected"
    if screen_id in UI_LOCAL_ONLY:
        return "local_view_state"
    return "unavailable_without_fixture"


def applicable_states(
    screen_id: str,
    kind: str,
    classification: str,
    screen_data_mode: str,
) -> list[str]:
    states = ["loading", "content", "error", "permission_closed"]
    if kind in {"list", "tabs", "dashboard"}:
        states.append("empty")
    if kind == "form":
        states.extend(["validation", "confirm"])
    if kind == "dialog":
        states.append("confirm")
    if screen_id in SUCCESS_SCREEN_IDS:
        states.append("success")
    if (
        classification == "disabled_unavailable"
        or screen_data_mode == "unavailable_without_fixture"
    ):
        states.append("disabled_reason")
    return states


def semantic_layout(screen_id: str, title: str, kind: str) -> str:
    lowered = title.casefold()
    if kind == "dashboard":
        return "hub"
    if kind == "dialog":
        return "confirm"
    if kind == "state":
        return "outcome"
    if kind == "form":
        return "editor"
    if "preview" in lowered or "предпросмотр" in lowered:
        return "preview"
    if "истори" in lowered or "журнал" in lowered or "ledger" in lowered:
        return "history"
    if kind in {"list", "tabs"}:
        return "list"
    return "detail"


def edge_scope(source: str, guard: str) -> str:
    if guard in {"local_navigation", "valid_local_form"}:
        return "production_ui_local"
    classification = connection_class(source)
    if classification == "existing_http_connected":
        return "production_existing_api"
    if classification == "ui_local_only" and guard not in {
        "fixture_or_connection",
        "authoritative_or_fixture_outcome",
    }:
        return "production_ui_local"
    return "dev_test_fixture_only"


def build() -> dict[str, object]:
    raw = BOARD.read_text(encoding="utf-8")
    parsed: list[dict[str, str]] = []
    for match in SCREEN_PATTERN.finditer(raw):
        screen_id, title, role, kind, entry, primary, states = match.groups()
        values = {
            "id": screen_id,
            "title": title,
            "role": role,
            "kind": kind,
            "entry": entry,
            "primary": primary,
            "states": states,
        }
        values.update(CORRECTIONS.get(screen_id, {}))
        parsed.append(values)

    screens: list[dict[str, object]] = []
    no_ui: list[dict[str, str]] = []
    for item in parsed:
        screen_id = item["id"]
        if screen_id.startswith("N"):
            no_ui.append(
                {
                    "id": screen_id,
                    "title": item["title"],
                    "reason": item["states"],
                    "connection_class": "no_ui",
                    "production_ui": "forbidden_or_not_in_contract",
                    "test_node": f"tests/architecture/test_ui_manifest.py::test_no_ui[{screen_id}]",
                }
            )
            continue
        key = route_key(screen_id)
        classification = connection_class(screen_id)
        screen_data_mode = data_mode(screen_id)
        screens.append(
            {
                "id": screen_id,
                "title": item["title"],
                "route_key": key,
                "route_pattern": ROUTE_PATTERNS[key],
                "view_state": screen_id.lower(),
                "component_family": item["kind"],
                "semantic_layout": semantic_layout(screen_id, item["title"], item["kind"]),
                "role_variant": item["role"],
                "entry": item["entry"],
                "logical_parent": PARENTS.get(screen_id),
                "primary_action": item["primary"],
                "visual_contract": item["states"].split(" · "),
                "system_states": applicable_states(
                    screen_id, item["kind"], classification, screen_data_mode
                ),
                "connection_class": classification,
                "data_mode": screen_data_mode,
                "authoritative_success": (
                    "existing_api_response_only"
                    if classification == "existing_http_connected"
                    else (
                        "not_applicable_local_transition"
                        if classification == "ui_local_only"
                        else "forbidden_in_production_fixture_only"
                    )
                ),
                "fixture_policy": "dev_test_screenshot_only",
                "navigation_class": (
                    "root"
                    if screen_id in ROOT_SCREENS
                    else (
                        "success"
                        if screen_id in SUCCESS_SCREEN_IDS
                        else ("dialog" if item["kind"] == "dialog" else "context")
                    )
                ),
                "reload_class": "bootstrap_then_revalidate_or_safe_fallback",
                "deep_link_class": "target_hint_then_access_resource_state_check",
                "test_nodes": [
                    f"tests/browser/test_ui_manifest.py::test_screen[{screen_id}]",
                    f"tests/browser/test_ui_transitions.py::test_edges_for_screen[{screen_id}]",
                ],
            }
        )

    screen_by_id = {str(item["id"]): item for item in screens}
    transitions: list[dict[str, object]] = []
    for index, (source, target, trigger, history, guard, target_state) in enumerate(
        PRODUCT_EDGES, start=1
    ):
        source_screen = screen_by_id[source]
        target_screen = screen_by_id[target]
        scope = edge_scope(source, guard)
        fallback = PARENTS.get(target) or "A02"
        request_count = "1_authoritative" if scope == "production_existing_api" else "0"
        transitions.append(
            {
                "id": f"PE-{index:03d}",
                "source_id": source,
                "source_view_state": source_screen["view_state"],
                "target_id": target,
                "target_route_pattern": target_screen["route_pattern"],
                "target_view_state": target_screen["view_state"],
                "trigger": trigger,
                "target_state": target_state,
                "history": history,
                "runtime_scope": scope,
                "guard": guard,
                "browser_oracle": {
                    "screen_marker": target,
                    "state": target_state,
                    "history": history,
                    "focus": "target_heading",
                    "safe_fallback": fallback,
                    "request_count": request_count,
                },
            }
        )

    edge_pairs = {(item["source_id"], item["target_id"]) for item in transitions}
    edge_triplets = {
        (item["source_id"], item["target_id"], item["trigger"]) for item in transitions
    }
    assert edge_pairs >= REQUIRED_KEY_EDGES
    assert not (FORBIDDEN_EDGES & edge_triplets)

    connected = sum(
        1 for screen in screens if screen["connection_class"] == "existing_http_connected"
    )
    local_only = sum(1 for screen in screens if screen["connection_class"] == "ui_local_only")
    unavailable = sum(
        1 for screen in screens if screen["connection_class"] == "disabled_unavailable"
    )
    result = {
        "schema": "community_bot.ui_presentation_contract.v2",
        "issue": "CB-96",
        "scope": "presentation_only_no_backend_changes",
        "base_sha": "949c837dccaea9c3549737d6f14e782947a291ff",
        "counts": {
            "ui": len(screens),
            "no_ui": len(no_ui),
            "capabilities": len(CAPABILITIES),
            "route_patterns": len(ROUTE_PATTERNS),
            "transitions": len(transitions),
            "existing_http_connected": connected,
            "ui_local_only": local_only,
            "disabled_unavailable": unavailable,
        },
        "route_patterns": [
            {"key": key, "pattern": pattern} for key, pattern in ROUTE_PATTERNS.items()
        ],
        "global_contracts": {
            "production_fixtures": "forbidden",
            "unconnected_action": "disabled_reason; no authoritative success",
            "root_navigation": {
                "screens": list(ROOT_SCREENS),
                "history": "replace",
                "visibility": "role_shaped",
                "browser_test_scope": "once_per_distinct_root_route_pattern_and_role_variant",
            },
            "context_back": {
                "history": "pop_to_logical_parent",
                "focus": "opening_control",
                "dirty_form": "confirm_before_pop",
                "dialog": "Back_or_Escape_closes_and_restores_focus",
            },
            "success_history": {
                "screens": sorted(SUCCESS_SCREEN_IDS),
                "history": "replace",
                "forbidden_target": "preceding_mutation_editor_or_confirm",
            },
            "reload": {
                "behavior": "bootstrap_then_revalidate_same_view_or_safe_fallback",
                "browser_test_scope": "once_per_11_route_patterns_and_navigation_classes",
            },
            "deep_link": {
                "behavior": "target_hint_then_access_resource_state_check",
                "safe_fallback": "logical_parent_or_A02",
                "browser_test_scope": "once_per_11_route_patterns_and_guard_classes",
            },
            "system_states": {
                "values": [
                    "loading",
                    "content",
                    "empty",
                    "error",
                    "permission_closed",
                    "validation",
                    "confirm",
                    "success",
                    "disabled_reason",
                ],
                "browser_test_scope": "once_per_semantic_layout_and_distinct_state_behavior",
            },
            "architecture": "native HTML/CSS/ES modules; no generic screen/form framework; no new dependency",
        },
        "screens": screens,
        "transitions": transitions,
        "no_ui": no_ui,
        "capabilities": [
            {
                "id": capability,
                "screens": ids,
                "disposition": "ui" if ids else "ops_no_user_ui",
                "test_node": f"tests/architecture/test_ui_manifest.py::test_capability[{capability}]",
            }
            for capability, ids in CAPABILITIES.items()
        ],
        "next_task_handoff": "next-task-engine-handoff.md",
    }
    assert result["counts"]["ui"] == 103
    assert result["counts"]["no_ui"] == 17
    assert result["counts"]["capabilities"] == 26
    assert result["counts"]["route_patterns"] == 11
    assert result["counts"]["transitions"] == 128
    assert result["counts"]["existing_http_connected"] == 10
    assert result["counts"]["ui_local_only"] == 61
    assert result["counts"]["disabled_unavailable"] == 32
    assert connected + local_only + unavailable == 103
    assert len({screen["id"] for screen in screens}) == 103
    assert len({item["id"] for item in no_ui}) == 17
    assert len({item["id"] for item in transitions}) == len(transitions)
    signatures = {
        (item["source_id"], item["target_id"], item["trigger"], item["runtime_scope"])
        for item in transitions
    }
    assert len(signatures) == len(transitions)
    assert all(
        item["source_id"] in screen_by_id and item["target_id"] in screen_by_id
        for item in transitions
    )
    return result


contract = build()
OUTPUT.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
lines = [
    "# CB-96 — полный screen/state/transition inventory",
    "",
    "Этот файл детерминированно генерируется из `build_ui_contract.py`.",
    "",
    "## Экраны",
    "",
    "| ID | Экран | Route pattern | view_state | family | role | action class | data mode | parent |",
    "|---|---|---|---|---|---|---|---|---|",
]
for screen in cast("list[dict[str, object]]", contract["screens"]):
    lines.append(
        f"| {screen['id']} | {screen['title']} | `{screen['route_pattern']}` | "
        f"`{screen['view_state']}` | `{screen['component_family']}` | "
        f"`{screen['role_variant']}` | `{screen['connection_class']}` | "
        f"`{screen['data_mode']}` | "
        f"{screen['logical_parent'] or '—'} |"
    )
lines.extend(
    [
        "",
        "## Переходы",
        "",
        "| ID | Source | Trigger | Target route/view | State | History | Scope | Guard |",
        "|---|---|---|---|---|---|---|---|",
    ]
)
for transition in cast("list[dict[str, object]]", contract["transitions"]):
    lines.append(
        f"| {transition['id']} | {transition['source_id']}/`{transition['source_view_state']}` | "
        f"`{transition['trigger']}` | {transition['target_id']} "
        f"`{transition['target_route_pattern']}`/`{transition['target_view_state']}` | "
        f"`{transition['target_state']}` | "
        f"`{transition['history']}` | `{transition['runtime_scope']}` | "
        f"`{transition['guard']}` |"
    )
lines.extend(
    [
        "",
        "## No-UI",
        "",
        "| ID | Механизм | Причина |",
        "|---|---|---|",
    ]
)
for item in cast("list[dict[str, object]]", contract["no_ui"]):
    lines.append(
        f"| {item['id']} | {item['title']} (`{item['connection_class']}`) | {item['reason']} |"
    )
INVENTORY.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(json.dumps(contract["counts"], ensure_ascii=False))
