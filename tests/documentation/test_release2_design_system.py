from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

type JsonValue = Any

ROOT = Path(__file__).resolve().parents[2]
DESIGN_DIR = ROOT / "docs" / "release-2" / "design"
TOKENS_PATH = DESIGN_DIR / "design-tokens.json"
DESIGN_PATH = DESIGN_DIR / "DESIGN.md"
PREVIEW_PATH = DESIGN_DIR / "design-preview.html"
RELEASE_README_PATH = ROOT / "docs" / "release-2" / "README.md"

MODE_IDS = {
    "browserDark",
    "browserLight",
    "telegramDark",
    "telegramLight",
    "telegramFallbackDark",
    "telegramFallbackLight",
}

LIVE_STATE_FAMILIES = {
    "navigationItem",
    "button",
    "formField",
    "choice",
    "status",
    "routeProgress",
    "dataCard",
    "overlay",
    "systemState",
}

ALL_COMPONENTS = {
    "app-shell",
    "top-bar",
    "bottom-navigation",
    "side-navigation",
    "page-header",
    "back-action",
    "breadcrumbs",
    "tabs",
    "segmented-control",
    "route-progress",
    "sticky-action-region",
    "button",
    "link",
    "menu-action",
    "toggle",
    "checkbox",
    "radio",
    "inline-notice",
    "toast",
    "dialog",
    "bottom-sheet",
    "task-card",
    "task-status-chip",
    "task-state-timeline",
    "slot-counter",
    "reward-badge",
    "time-size-badge",
    "member-list-item",
    "profile-summary",
    "avatar",
    "role-badge",
    "karma-aggregate",
    "balance-metric",
    "level-progress",
    "stats-item",
    "ledger-row",
    "leaderboard-row",
    "data-table",
    "admin-list",
    "form-field",
    "text-field",
    "text-area",
    "select",
    "search-field",
    "date-time-field",
    "material-field",
    "character-counter",
    "reward-stepper",
    "performer-stepper",
    "task-size-select",
    "category-select",
    "preview-confirmation",
    "system-state",
}

PREVIEW_COMPONENTS = {
    "app-shell",
    "top-bar",
    "bottom-navigation",
    "side-navigation",
    "tabs",
    "segmented-control",
    "route-progress",
    "sticky-action-region",
    "button",
    "toggle",
    "checkbox",
    "radio",
    "inline-notice",
    "toast",
    "dialog",
    "bottom-sheet",
    "task-card",
    "task-status-chip",
    "profile-summary",
    "balance-metric",
    "level-progress",
    "ledger-row",
    "data-table",
    "admin-list",
    "form-field",
    "text-field",
    "text-area",
    "select",
    "character-counter",
    "preview-confirmation",
    "system-state",
}

SHARED_ALIASES = {
    "typography.screenTitleCompact",
    "typography.screenTitleWide",
    "typography.sectionHeading",
    "typography.cardHeading",
    "typography.body",
    "typography.label",
    "typography.meta",
    "typography.button",
    "typography.number",
    "typography.wordmark",
    "spacing.pageInlineCompact",
    "spacing.pageInlineWide",
    "spacing.sectionStack",
    "spacing.clusterGap",
    "spacing.cardPadding",
    "spacing.formFieldGap",
    "spacing.controlInlineGap",
    "spacing.denseRowGap",
    "radius.control",
    "radius.card",
    "radius.sheet",
    "radius.panel",
    "radius.pill",
    "shadow.surface",
    "shadow.raised",
    "shadow.overlay",
    "shadow.focusGlow",
    "size.targetMinimum",
    "size.controlHeight",
    "size.topBarHeight",
    "size.bottomNavigationHeight",
    "size.contentReadableMax",
    "size.contentCanvasMax",
    "breakpoint.compactEnd",
    "breakpoint.mediumStart",
    "breakpoint.wideStart",
    "motion.durationFast",
    "motion.durationStandard",
    "motion.durationDeliberate",
    "motion.easingStandard",
    "motion.easingEmphasized",
    "motion.distanceState",
    "icon.compactGrid",
    "icon.standardGrid",
    "icon.strokeDefault",
}


def _load_tokens() -> dict[str, JsonValue]:
    return json.loads(TOKENS_PATH.read_text(encoding="utf-8"))


def _path_value(tree: dict[str, JsonValue], path: str) -> JsonValue:
    value: JsonValue = tree
    for part in path.split("."):
        value = value[part]
    return value


def _leaf_paths(tree: JsonValue, prefix: str = "") -> set[str]:
    if isinstance(tree, dict) and "$value" in tree:
        return {prefix}
    result: set[str] = set()
    if isinstance(tree, dict):
        for key, value in tree.items():
            child = f"{prefix}.{key}" if prefix else key
            result.update(_leaf_paths(value, child))
    return result


def _resolve(
    tree: dict[str, JsonValue], path: str, seen: frozenset[str] = frozenset()
) -> JsonValue:
    if path in seen:
        message = f"Циклическая ссылка токена: {path}"
        raise AssertionError(message)
    node = _path_value(tree, path)
    value = node["$value"] if isinstance(node, dict) and "$value" in node else node
    if isinstance(value, str) and re.fullmatch(r"\{[^{}]+}", value):
        return _resolve(tree, value[1:-1], seen | {path})
    return value


def _color_leaf_suffixes() -> set[str]:
    paths = {
        *(
            f"background.{name}"
            for name in ("canvas", "surface", "raised", "overlay", "header", "navigation")
        ),
        *(
            f"text.{name}"
            for name in ("primary", "secondary", "muted", "inverse", "link", "accent")
        ),
        *(f"border.{name}" for name in ("subtle", "default", "strong", "separator")),
        "focus.ring",
        "selection.background",
        "selection.foreground",
        "scrim",
        "skeleton.base",
        "skeleton.highlight",
        "chart.primary",
        "chart.secondary",
        "chart.tertiary",
        "shadow.surface",
        "shadow.raised",
        "shadow.overlay",
        "shadow.focusGlow",
        "brand.gradientStart",
        "brand.gradientEnd",
        "route.gradientStart",
        "route.gradientEnd",
        "route.current",
        "route.completed",
        "route.upcoming",
        "overlay.background",
        "overlay.foreground",
        "overlay.border",
    }
    for state in ("default", "hover", "pressed", "focusVisible", "selected", "disabled"):
        paths.update(
            f"navigation.item.{state}.{name}" for name in ("background", "foreground", "border")
        )
    for variant in ("primary", "secondary", "tertiary", "destructive", "iconOnly"):
        for state in ("default", "hover", "pressed", "focusVisible", "disabled", "loading"):
            paths.update(
                f"action.{variant}.{state}.{name}"
                for name in ("background", "foreground", "border", "progress")
            )
    for state in ("default", "hover", "focused", "invalid", "disabled", "filled"):
        paths.update(
            f"form.field.{state}.{name}"
            for name in ("background", "foreground", "border", "placeholder", "message")
        )
    for state in ("unchecked", "checked", "focusVisible", "disabled"):
        paths.update(
            f"form.choice.{state}.{name}"
            for name in ("background", "foreground", "border", "indicator")
        )
    for state in ("default", "selected", "loading"):
        paths.update(
            f"data.card.{state}.{name}"
            for name in ("background", "foreground", "border", "skeleton")
        )
    for variant in ("info", "success", "warning", "danger", "neutral"):
        paths.update(
            f"status.{variant}.{name}" for name in ("background", "text", "icon", "border")
        )
    for variant in (
        "loading",
        "empty",
        "offline",
        "expired",
        "forbidden",
        "notFound",
        "conflict",
        "featureDisabled",
        "genericError",
    ):
        paths.update(
            f"system.{variant}.{name}"
            for name in ("background", "text", "icon", "border", "action")
        )
    return paths


def _expected_state_ids() -> set[str]:
    result = {
        f"navigationItem.{variant}.{state}"
        for variant in ("bottomNavigation", "sideNavigation", "tabs", "segmentedControl")
        for state in ("default", "hover", "pressed", "focusVisible", "selected", "disabled")
    }
    result.update(
        f"button.{variant}.{state}"
        for variant in ("primary", "secondary", "tertiary", "destructive", "iconOnly")
        for state in ("default", "hover", "pressed", "focusVisible", "disabled", "loading")
    )
    result.update(
        f"formField.{variant}.{state}"
        for variant in ("textField", "textArea", "select", "searchField")
        for state in ("default", "hover", "focused", "invalid", "disabled", "filled")
    )
    result.update(
        f"choice.{variant}.{state}"
        for variant in ("toggle", "checkbox", "radio")
        for state in ("unchecked", "checked", "focusVisible", "disabled")
    )
    result.update(
        f"status.{variant}.default"
        for variant in ("info", "success", "warning", "danger", "neutral")
    )
    result.update(f"routeProgress.route.{state}" for state in ("completed", "current", "upcoming"))
    result.update(f"dataCard.taskCard.{state}" for state in ("default", "selected", "loading"))
    result.update(
        f"overlay.{variant}.{state}"
        for variant in ("dialog", "bottomSheet")
        for state in ("open", "destructive")
    )
    result.update(
        f"systemState.{variant}.default"
        for variant in (
            "loading",
            "empty",
            "offline",
            "expired",
            "forbidden",
            "notFound",
            "conflict",
            "featureDisabled",
            "genericError",
        )
    )
    return result


def _hex_rgb(value: str) -> tuple[float, float, float]:
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), value
    return (
        int(value[1:3], 16) / 255,
        int(value[3:5], 16) / 255,
        int(value[5:7], 16) / 255,
    )


def _luminance(value: str) -> float:
    def channel(raw: float) -> float:
        return raw / 12.92 if raw <= 0.04045 else ((raw + 0.055) / 1.055) ** 2.4

    red, green, blue = _hex_rgb(value)
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def _contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _semantic_suffix(path: str, base_mode: str) -> str:
    prefix = f"semantic.{base_mode}.color."
    assert path.startswith(prefix), path
    return path.removeprefix(prefix)


def _base_palette(tokens: dict[str, JsonValue], base_mode: str) -> dict[str, str]:
    return {
        suffix: _resolve(tokens, f"semantic.{base_mode}.color.{suffix}")
        for suffix in _color_leaf_suffixes()
    }


def _failed_pairs(
    tokens: dict[str, JsonValue], mode_id: str, base_mode: str, palette: dict[str, str]
) -> list[str]:
    failures: list[str] = []
    for pair in tokens["contracts"]["contrastPairs"]:
        if mode_id not in pair["modeIds"]:
            continue
        foreground = palette[
            _semantic_suffix(
                pair["foregroundPath"].replace("{baseSemanticMode}", base_mode), base_mode
            )
        ]
        backgrounds = [pair["backgroundPath"], *pair["adjacentPaths"]]
        if any(
            _contrast(
                foreground,
                palette[_semantic_suffix(path.replace("{baseSemanticMode}", base_mode), base_mode)],
            )
            < pair["minRatio"]
            for path in backgrounds
        ):
            failures.append(pair["id"])
    return failures


def test_at_01_schema_and_references() -> None:
    tokens = _load_tokens()
    assert tokens["schemaVersion"] == "1.0.0"
    assert set(tokens) == {"schemaVersion", "primitives", "semantic", "platform", "contracts"}
    assert "system" not in tokens["semantic"]

    leaves = _leaf_paths(tokens)
    for path in leaves:
        node = _path_value(tokens, path)
        assert {"$type", "$value", "description"} <= set(node)
        value = node["$value"]
        if isinstance(value, str) and re.fullmatch(r"\{[^{}]+}", value):
            target = value[1:-1]
            assert target in leaves
            _resolve(tokens, path)

    shared_paths = _leaf_paths(tokens["semantic"]["shared"])
    assert shared_paths == SHARED_ALIASES
    for path in shared_paths:
        node = _path_value(tokens, f"semantic.shared.{path}")
        references = re.findall(r"\{([^{}]+)}", json.dumps(node, ensure_ascii=False))
        assert references
        assert all(reference.startswith("primitives.") for reference in references)

    expected_colors = _color_leaf_suffixes()
    assert _leaf_paths(tokens["semantic"]["dark"]["color"]) == expected_colors
    assert _leaf_paths(tokens["semantic"]["light"]["color"]) == expected_colors


def test_at_02_alias_and_platform_contract() -> None:
    tokens = _load_tokens()
    contracts = tokens["contracts"]
    modes = contracts["paletteModes"]
    assert {mode["modeId"] for mode in modes} == MODE_IDS
    assert all(mode["baseSemanticMode"] in {"dark", "light"} for mode in modes)
    assert all("semantic.telegram" not in mode["expectedEffectivePaletteSource"] for mode in modes)

    expected_keys = {
        "bg_color",
        "secondary_bg_color",
        "section_bg_color",
        "header_bg_color",
        "bottom_bar_bg_color",
        "text_color",
        "hint_color",
        "subtitle_text_color",
        "section_header_text_color",
        "accent_text_color",
        "link_color",
        "button_color",
        "button_text_color",
        "destructive_text_color",
        "section_separator_color",
    }
    theme_map = tokens["platform"]["telegram"]["themeParamMap"]
    assert {record["telegramKey"] for record in theme_map} == expected_keys
    assert tokens["platform"]["telegram"]["providerPolicy"] == "atomicValidatedOverlay"

    projection = contracts["controlProjection"]
    assert projection["policy"] == "canonicalTuplesOnly"
    assert projection["browserPresetControl"] == "disabledNotApplicable"
    rules = {
        (rule["platform"], rule["theme"]): (
            tuple(rule["allowedProviderPresetIds"]),
            set(rule["resultModeIds"]),
        )
        for rule in projection["rules"]
    }
    assert rules == {
        ("browser", "dark"): ((None,), {"browserDark"}),
        ("browser", "light"): ((None,), {"browserLight"}),
        ("browser", "system"): ((None,), {"browserDark", "browserLight"}),
        (
            "telegram",
            "dark",
        ): (
            ("telegram-dark-valid", "telegram-dark-low-contrast"),
            {"telegramDark", "telegramFallbackDark"},
        ),
        (
            "telegram",
            "light",
        ): (
            ("telegram-light-valid", "telegram-light-low-contrast"),
            {"telegramLight", "telegramFallbackLight"},
        ),
        (
            "telegram",
            "system",
        ): (
            (
                "telegram-dark-valid",
                "telegram-dark-low-contrast",
                "telegram-light-valid",
                "telegram-light-low-contrast",
            ),
            {
                "telegramDark",
                "telegramFallbackDark",
                "telegramLight",
                "telegramFallbackLight",
            },
        ),
    }

    html = PREVIEW_PATH.read_text(encoding="utf-8")
    assert 'data-diagnostic-id="resolver-trace"' in html
    style = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert style is not None
    assert "var(--primitive" not in style.group(1)
    assert "var(--platform" not in style.group(1)


def test_at_03_contrast_contract() -> None:  # noqa: C901, PLR0912, PLR0915
    tokens = _load_tokens()
    contracts = tokens["contracts"]
    state_records = contracts["componentStateTokens"]
    state_ids = {record["recordId"] for record in state_records}
    assert len(state_records) == 114
    assert state_ids == _expected_state_ids()
    assert all(
        record["recordId"] == f"{record['family']}.{record['variantId']}.{record['stateId']}"
        for record in state_records
    )

    allowed_fields = {
        "background",
        "foreground",
        "border",
        "icon",
        "indicator",
        "placeholder",
        "message",
        "progress",
        "action",
        "focusRing",
    }
    for record in state_records:
        assert set(record["tokenPaths"]) == allowed_fields
        for path in record["tokenPaths"].values():
            if path is None:
                continue
            assert "{baseSemanticMode}" in path
            for base_mode in ("dark", "light"):
                resolved_path = path.replace("{baseSemanticMode}", base_mode)
                assert resolved_path in _leaf_paths(tokens)

    pairs = contracts["contrastPairs"]
    pair_ids = {pair["id"] for pair in pairs}
    assert len(pair_ids) == len(pairs)
    referenced_states: set[str] = set()
    for pair in pairs:
        assert {
            "id",
            "foregroundPath",
            "backgroundPath",
            "adjacentPaths",
            "modeIds",
            "stateTokenRecordIds",
            "minRatio",
            "purpose",
        } == set(pair)
        assert set(pair["modeIds"]) == MODE_IDS
        assert pair["minRatio"] in {3.0, 4.5}
        assert pair["purpose"]
        assert set(pair["stateTokenRecordIds"]) <= state_ids
        referenced_states.update(pair["stateTokenRecordIds"])
    assert referenced_states == state_ids

    presets = {preset["presetId"]: preset for preset in tokens["platform"]["telegram"]["presets"]}
    theme_map = tokens["platform"]["telegram"]["themeParamMap"]
    for mode in contracts["paletteModes"]:
        base_mode = mode["baseSemanticMode"]
        palette = _base_palette(tokens, base_mode)
        if mode["providerPresetId"] is not None:
            candidate = dict(palette)
            provider_values = presets[mode["providerPresetId"]]["themeParams"]
            malformed = False
            for mapping in theme_map:
                value = provider_values.get(mapping["telegramKey"])
                if value is None:
                    continue
                if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
                    malformed = True
                    break
                for target in mapping["targetPaths"]:
                    candidate[target] = value.upper()
            candidate_failures = (
                ["malformed-provider-value"]
                if malformed
                else _failed_pairs(tokens, mode["modeId"], base_mode, candidate)
            )
            if candidate_failures:
                assert mode["expectedProviderResult"] == "providerRejected"
                assert mode["expectedFallbackResult"] == "fullSemanticFallback"
            else:
                assert mode["expectedProviderResult"] == "providerAccepted"
                assert mode["expectedFallbackResult"] == "none"
                palette = candidate
        assert not _failed_pairs(tokens, mode["modeId"], base_mode, palette)

    assert contracts["gradientPolicy"]["actionFillPolicy"] == "solidOnly"
    assert contracts["gradientPolicy"]["allowedSemanticRoots"] == ["brand", "route"]


def test_at_04_assets_and_autonomy() -> None:
    tokens = _load_tokens()
    html = PREVIEW_PATH.read_text(encoding="utf-8")
    provenance = tokens["contracts"]["fontProvenance"]
    assert {font["family"] for font in provenance} == {"Manrope", "Unbounded"}
    for font in provenance:
        assert "raw.githubusercontent.com/google/fonts/352f6b7" in font["sourceUrl"]
        assert font["licenseId"] == "OFL-1.1"
        assert font["subset"]["reproductionClaim"] == "provenanceAndArtifactIntegrity"
        assert font["subset"]["bitReproducible"] is False
        family_slug = font["family"].lower()
        match = re.search(
            rf'data-font-family="{font["family"]}"[^>]*data-font-base64="([A-Za-z0-9+/=]+)"',
            html,
        )
        assert match is not None, family_slug
        raw = base64.b64decode(match.group(1))
        assert len(raw) == font["subset"]["outputBytes"]
        assert hashlib.sha256(raw).hexdigest() == font["subset"]["outputSha256"]

    assert 'id="font-license-notice"' in html
    assert "SIL OPEN FONT LICENSE Version 1.1" in html
    assert "Copyright 2018 The Manrope Project Authors" in html
    assert "Copyright 2022 The Unbounded Project Authors" in html

    embedded = re.search(
        r'<script id="design-tokens" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert embedded is not None
    assert json.loads(embedded.group(1)) == tokens
    assert re.search(r"<(?:script|link|img|source)[^>]+(?:src|href)=[\"']https?://", html) is None
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "localStorage",
        "sessionStorage",
        "serviceWorker",
        "analytics",
    ):
        assert forbidden not in html


def test_at_05_component_partition_and_samples() -> None:
    tokens = _load_tokens()
    html = PREVIEW_PATH.read_text(encoding="utf-8")
    design = DESIGN_PATH.read_text(encoding="utf-8")
    inventory = tokens["contracts"]["componentInventory"]
    records = inventory["records"]
    record_ids = {record["componentId"] for record in records}
    assert set(inventory["all"]) == ALL_COMPONENTS == record_ids
    assert len(inventory["all"]) == len(record_ids) == 53
    assert set(inventory["previewRequired"]) == PREVIEW_COMPONENTS
    documented = set(inventory["documentedOnly"])
    assert documented == ALL_COMPONENTS - PREVIEW_COMPONENTS
    assert not PREVIEW_COMPONENTS & documented

    record_by_id = {record["componentId"]: record for record in records}
    for component_id, record in record_by_id.items():
        assert record["requiredVariantStateCases"]
        if component_id in PREVIEW_COMPONENTS:
            assert record["coverage"] == "previewRequired"
            assert record["sampleIds"]
        else:
            assert record["coverage"] == "documentedOnly"
            assert record["sampleIds"] == []
            assert f'<a id="{record["documentationAnchor"]}"></a>' in design

    sample_ids: set[str] = set()
    required_dom_cases: set[tuple[str, str, str, str, str]] = set()
    for sample in tokens["contracts"]["previewSamples"]:
        sample_ids.add(sample["id"])
        assert sample["sceneIds"]
        assert sample["evidenceScenarioIds"]
        assert all(
            evidence.startswith("AT-") or re.fullmatch(r"TP-\d{2}", evidence)
            for evidence in sample["evidenceScenarioIds"]
        )
        for requirement in sample["componentRequirements"]:
            for case in requirement["requiredCases"]:
                state_record = case["stateTokenRecordId"] or "none"
                required_dom_cases.add(
                    (
                        sample["id"],
                        requirement["componentId"],
                        case["variantId"],
                        case["stateId"],
                        state_record,
                    )
                )
    assert len(sample_ids) == 17

    actual_dom_cases = {
        tuple(match)
        for match in re.findall(
            r'data-sample-id="([^"]+)"\s+data-component-id="([^"]+)"\s+'
            r'data-variant="([^"]+)"\s+data-state="([^"]+)"\s+'
            r'data-state-token-record-id="([^"]+)"',
            html,
        )
    }
    assert required_dom_cases <= actual_dom_cases

    live_state_ids = {
        record["recordId"]
        for record in tokens["contracts"]["componentStateTokens"]
        if record["family"] in LIVE_STATE_FAMILIES
    }
    actual_live_state_ids = set(re.findall(r'data-live-state-record-id="([^"]+)"', html))
    actual_style_target_ids = set(re.findall(r'data-state-style-target="([^"]+)"', html))
    assert len(live_state_ids) == 114
    assert actual_live_state_ids == live_state_ids
    assert actual_style_target_ids == live_state_ids
    assert 'data-live-state-gallery="componentStateTokens"' in html
    assert "data-bound-base-mode" in html


def test_at_06_static_scope() -> None:
    html = PREVIEW_PATH.read_text(encoding="utf-8")
    release_readme = RELEASE_README_PATH.read_text(encoding="utf-8")
    for frame in ("320×568", "390×844", "1440×900"):  # noqa: RUF001
        assert frame in html
    for contract_marker in (
        "--semantic-size-safe-area-top",
        "--semantic-size-safe-area-bottom",
        "prefers-reduced-motion: reduce",
        'data-diagnostic-id="resolver-trace"',
        'id="scene-catalog"',
        'id="scene-admin"',
    ):
        assert contract_marker in html
    assert "[дизайн-система Release 2](design/DESIGN.md)" in release_readme
    assert not re.search(r"\b(?:React|Vite|Telegram\.WebApp|initData)\b", html)
    for expected_product_fact in (
        "3 кредита",
        "⭐ S · 15\N{EN DASH}40 минут",
        "Сообщество · понятный результат",
        "4 кредита",
        "💎 M · 40\N{EN DASH}75 минут",
        'maxlength="1200"',
        "из 1200 символов",
        "Практическая помощь",
    ):
        assert expected_product_fact in html
    for forbidden_product_fact in (
        "25 кредитов</span><span>≈ 40 минут",
        "Участница Б · понятный результат",
        'maxlength="800"',
        "из 800 символов",
        "Помощь сообществу",
    ):
        assert forbidden_product_fact not in html
    style = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert style is not None
    assert re.search(r"#[0-9A-Fa-f]{3,8}\b", style.group(1)) is None
    assert math.isfinite(float(_load_tokens()["schemaVersion"].split(".")[0]))
