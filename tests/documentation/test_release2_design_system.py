from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

# ruff: noqa: RUF001

ROOT = Path(__file__).resolve().parents[2]
DESIGN_DIR = ROOT / "docs" / "release-2" / "design"
TOKENS_PATH = DESIGN_DIR / "design-tokens.json"
DESIGN_PATH = DESIGN_DIR / "DESIGN.md"
PREVIEW_PATH = DESIGN_DIR / "design-preview.html"
FONT_PATH = DESIGN_DIR / "assets" / "Manrope[wght].ttf"
FONT_LICENSE_PATH = DESIGN_DIR / "assets" / "Manrope-OFL.txt"


def _tokens() -> dict[str, object]:
    value = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _rgb(hex_color: str) -> tuple[int, int, int]:
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", hex_color)
    return (
        int(hex_color[1:3], 16),
        int(hex_color[3:5], 16),
        int(hex_color[5:7], 16),
    )


def _luminance(hex_color: str) -> float:
    channels = []
    for channel in _rgb(hex_color):
        value = channel / 255
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (_luminance(foreground), _luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def _normalize_css_value(value: str) -> str:
    normalized = re.sub(r"\s+", "", value.lower())
    if re.fullmatch(r"#[0-9a-f]{3}", normalized):
        return "#" + "".join(character * 2 for character in normalized[1:])
    return normalized


def test_token_contract_is_small_and_complete() -> None:
    tokens = _tokens()

    assert tokens["schemaVersion"] == "1.0.0"
    themes = tokens["themes"]
    primitives = tokens["primitives"]
    components = tokens["components"]
    assert isinstance(themes, dict)
    assert isinstance(primitives, dict)
    assert isinstance(components, dict)
    assert set(themes) == {"dark", "light"}
    assert {"color", "space", "radius", "font", "motion"} <= set(primitives)
    assert {"control", "card", "chip", "navigation"} == set(components)
    assert TOKENS_PATH.stat().st_size < 15_000

    required_roles = {
        "background",
        "surface",
        "surfaceRaised",
        "text",
        "textMuted",
        "border",
        "accent",
        "accentStrong",
        "accentHover",
        "accentPressed",
        "accentText",
        "brandSecondary",
        "focus",
        "success",
        "warning",
        "danger",
        "dangerHover",
        "dangerPressed",
        "dangerText",
        "info",
        "surfaceHover",
        "surfacePressed",
        "overlay",
        "shadow",
    }
    for theme in themes.values():
        assert isinstance(theme, dict)
        assert set(theme) == required_roles

    control = components["control"]
    radius = primitives["radius"]
    assert isinstance(control, dict)
    assert isinstance(radius, dict)
    assert control["radius"] == "{primitives.radius.md}"
    assert radius["md"] == "12px"


def test_theme_contrast_meets_wcag_aa() -> None:
    tokens = _tokens()
    themes = tokens["themes"]
    assert isinstance(themes, dict)

    for theme in themes.values():
        assert isinstance(theme, dict)
        assert all(isinstance(value, str) for value in theme.values())
        assert _contrast(theme["text"], theme["background"]) >= 4.5
        assert _contrast(theme["text"], theme["surface"]) >= 4.5
        assert _contrast(theme["textMuted"], theme["surface"]) >= 4.5
        assert _contrast(theme["accentText"], theme["accent"]) >= 4.5
        assert _contrast(theme["accentText"], theme["accentHover"]) >= 4.5
        assert _contrast(theme["accentText"], theme["accentPressed"]) >= 4.5
        assert _contrast(theme["text"], theme["surfaceHover"]) >= 4.5
        assert _contrast(theme["text"], theme["surfacePressed"]) >= 4.5
        assert _contrast(theme["dangerText"], theme["dangerHover"]) >= 4.5
        assert _contrast(theme["dangerText"], theme["dangerPressed"]) >= 4.5
        assert _contrast(theme["focus"], theme["background"]) >= 3
        assert _contrast(theme["focus"], theme["surface"]) >= 3
        for role in ("success", "warning", "danger", "info"):
            assert _contrast(theme[role], theme["surface"]) >= 4.5


def test_interaction_and_platform_contract() -> None:
    tokens = _tokens()
    components = tokens["components"]
    platform = tokens["platform"]
    assert isinstance(components, dict)
    assert isinstance(platform, dict)
    control = components["control"]
    navigation = components["navigation"]
    mapping = platform["telegramThemeMapping"]
    safe_areas = platform["safeAreaVariables"]
    policy = platform["contrastPolicy"]
    assert isinstance(control, dict)
    assert isinstance(navigation, dict)
    assert isinstance(mapping, dict)
    assert isinstance(safe_areas, list)
    assert isinstance(policy, dict)

    assert control["minHeight"] == "44px"
    assert navigation["itemMinSize"] == "44px"
    assert mapping["--app-background"] == "--tg-theme-bg-color"
    assert "--tg-safe-area-inset-bottom" in safe_areas
    assert policy["fallbackMode"] == "atomic-base-theme"

    pairs = policy["validatedPairs"]
    themes = tokens["themes"]
    assert isinstance(themes, dict)
    assert isinstance(pairs, list)
    provider_cases = (
        (
            "dark",
            {
                "background": "#777777",
                "surface": "#777777",
                "text": "#777777",
                "textMuted": "#777777",
                "accent": "#777777",
                "accentText": "#777777",
            },
        ),
        (
            "dark",
            {
                "background": "#BE123C",
                "surface": "#BE123C",
                "text": "#FFFFFF",
                "textMuted": "#FFFFFF",
                "accent": "#000000",
                "accentText": "#FFFFFF",
            },
        ),
        ("dark", {"background": "#454545"}),
        ("light", {"background": "#A9A9A9"}),
        ("dark", {"accent": "#777777"}),
    )
    for base_theme_name, provider_palette in provider_cases:
        base_theme = themes[base_theme_name]
        assert isinstance(base_theme, dict)
        candidate = base_theme | provider_palette
        valid = all(
            _contrast(candidate[pair["foreground"]], candidate[pair["background"]])
            >= pair["minimum"]
            for pair in pairs
        )
        resolved = candidate if valid else base_theme
        assert not valid
        assert resolved == base_theme

    design = DESIGN_PATH.read_text(encoding="utf-8")
    for phrase in (
        "PlatformBridge",
        "WCAG AA",
        "44 × 44 CSS px",
        "prefers-reduced-motion",
        "Telegram SDK внутри React components",
        "имитация успеха до ответа API",
    ):
        assert phrase in design
    assert DESIGN_PATH.stat().st_size < 20_000
    assert hashlib.sha256(FONT_PATH.read_bytes()).hexdigest() == (
        "d0639be45d0af36e798172419d7bd173c4bd4f29e2b76cbb69db1d11bf8b0a40"
    )
    assert FONT_PATH.stat().st_size <= 170_000
    assert FONT_LICENSE_PATH.stat().st_size <= 5_000
    assert "SIL OPEN FONT LICENSE Version 1.1" in FONT_LICENSE_PATH.read_text(encoding="utf-8")


def test_preview_covers_mobile_desktop_and_states() -> None:
    preview = PREVIEW_PATH.read_text(encoding="utf-8")

    for marker in (
        'data-theme="dark"',
        'data-theme="light"',
        "@media (max-width: 760px)",
        "@media (prefers-reduced-motion: reduce)",
        "mobile-nav",
        "Карточки заданий",
        "Поле с ошибкой",
        "Пока нет заданий",
        'role="status"',
        'role="alert"',
        'data-state="pressed"',
        "<dialog",
        "showModal()",
        "@font-face",
        "Manrope%5Bwght%5D.ttf",
        'aria-current="page"',
        ":focus-visible",
    ):
        assert marker in preview

    assert "Telegram.WebApp" not in preview
    assert "http://" not in preview
    assert "https://" not in preview
    assert PREVIEW_PATH.stat().st_size < 30_000


def test_preview_semantic_variables_match_tokens() -> None:
    tokens = _tokens()
    themes = tokens["themes"]
    preview = PREVIEW_PATH.read_text(encoding="utf-8")
    assert isinstance(themes, dict)

    platform = tokens["platform"]
    assert isinstance(platform, dict)
    policy = platform["contrastPolicy"]
    assert isinstance(policy, dict)
    pairs = policy["validatedPairs"]
    assert isinstance(pairs, list)
    body_match = re.search(r'<body data-contrast-inventory="([^"]+)">', preview)
    assert body_match
    live_pairs = set(body_match.group(1).split())
    validated_pairs = {f"{pair['foreground']}/{pair['background']}" for pair in pairs}
    assert live_pairs == validated_pairs

    root_match = re.search(r":root\s*{(.*?)}", preview, re.DOTALL)
    light_match = re.search(r'\[data-theme="light"\]\s*{(.*?)}', preview, re.DOTALL)
    assert root_match
    assert light_match

    css_blocks = {"dark": root_match.group(1), "light": light_match.group(1)}
    for theme_name, block in css_blocks.items():
        theme = themes[theme_name]
        assert isinstance(theme, dict)
        css_variables = dict(re.findall(r"--([a-z-]+):\s*([^;]+);", block))
        for role, value in theme.items():
            assert isinstance(role, str)
            assert isinstance(value, str)
            css_name = re.sub(r"(?<!^)(?=[A-Z])", "-", role).lower()
            assert _normalize_css_value(css_variables[css_name]) == _normalize_css_value(value)

    hover_position = preview.index(".button.primary:hover")
    pressed_position = preview.index(
        '.button.primary:active, .button.primary[data-state="pressed"]',
    )
    assert pressed_position > hover_position
