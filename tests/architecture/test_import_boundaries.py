from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LayerRule:
    """Describe forbidden import prefixes for one package layer."""

    directory: str
    forbidden_prefixes: tuple[str, ...]


RULES = (
    LayerRule(
        directory="domain",
        forbidden_prefixes=(
            "aiogram",
            "sqlalchemy",
            "community_bot.application",
            "community_bot.bootstrap",
            "community_bot.infrastructure",
            "community_bot.transport",
            "community_bot.worker",
        ),
    ),
    LayerRule(
        directory="application",
        forbidden_prefixes=(
            "aiogram",
            "sqlalchemy",
            "community_bot.bootstrap",
            "community_bot.infrastructure",
            "community_bot.transport",
            "community_bot.worker",
        ),
    ),
)


def _containing_package(source_file: Path, package_root: Path) -> tuple[str, ...]:
    """Return the absolute package containing one source file."""
    relative_module = source_file.relative_to(package_root).with_suffix("")
    module_parts = ("community_bot", *relative_module.parts)
    return module_parts[:-1]


def _resolve_from_import(
    node: ast.ImportFrom,
    *,
    containing_package: tuple[str, ...],
) -> set[str]:
    """Resolve an ImportFrom node to absolute module names."""
    if node.level == 0:
        if node.module is None:
            return set()
        base_module = node.module
        return {
            base_module,
            *(f"{base_module}.{alias.name}" for alias in node.names if alias.name != "*"),
        }

    retained_parts = len(containing_package) - node.level + 1
    if retained_parts < 1:
        return set()

    base_parts = containing_package[:retained_parts]
    if node.module is not None:
        resolved_module = ".".join((*base_parts, *node.module.split(".")))
        return {
            resolved_module,
            *(f"{resolved_module}.{alias.name}" for alias in node.names if alias.name != "*"),
        }

    base_module = ".".join(base_parts)
    return {f"{base_module}.{alias.name}" for alias in node.names if alias.name != "*"}


def imported_modules(source_file: Path, package_root: Path) -> set[str]:
    """Return absolute module names imported by one Python source file."""
    syntax_tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    containing_package = _containing_package(source_file, package_root)
    modules: set[str] = set()
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.update(_resolve_from_import(node, containing_package=containing_package))
    return modules


def _matches_module_prefix(module: str, prefix: str) -> bool:
    """Return whether a module is the prefix itself or one of its children."""
    return module == prefix or module.startswith(f"{prefix}.")


def _forbidden_imports(modules: set[str], prefixes: tuple[str, ...]) -> list[str]:
    """Return forbidden imports without redundant child module entries."""
    matches = sorted(
        module
        for module in modules
        if any(_matches_module_prefix(module, prefix) for prefix in prefixes)
    )
    return [
        module
        for module in matches
        if not any(
            module != candidate and _matches_module_prefix(module, candidate)
            for candidate in matches
        )
    ]


def find_violations(package_root: Path) -> list[str]:
    """Return deterministic descriptions of forbidden layer imports."""
    violations: list[str] = []
    for rule in RULES:
        for source_file in sorted((package_root / rule.directory).rglob("*.py")):
            relative_path = source_file.relative_to(package_root).as_posix()
            violations.extend(
                f"{relative_path} imports {imported_module}"
                for imported_module in _forbidden_imports(
                    imported_modules(source_file, package_root),
                    rule.forbidden_prefixes,
                )
            )
    return violations


def test_current_source_respects_layer_boundaries() -> None:
    package_root = Path(__file__).parents[2] / "src" / "community_bot"

    assert find_violations(package_root) == []


def test_domain_violation_is_detected(tmp_path: Path) -> None:
    domain = tmp_path / "domain"
    domain.mkdir()
    (domain / "invalid.py").write_text("import sqlalchemy\n", encoding="utf-8")

    assert find_violations(tmp_path) == ["domain/invalid.py imports sqlalchemy"]


def test_application_violation_is_detected(tmp_path: Path) -> None:
    application = tmp_path / "application"
    application.mkdir()
    (application / "invalid.py").write_text(
        "from community_bot.infrastructure import db\n",
        encoding="utf-8",
    )

    assert find_violations(tmp_path) == [
        "application/invalid.py imports community_bot.infrastructure"
    ]


def test_relative_domain_violation_is_detected(tmp_path: Path) -> None:
    domain = tmp_path / "domain"
    domain.mkdir()
    (domain / "invalid.py").write_text(
        "from ..infrastructure import db\n",
        encoding="utf-8",
    )

    assert find_violations(tmp_path) == ["domain/invalid.py imports community_bot.infrastructure"]


def test_relative_alias_domain_violation_is_detected(tmp_path: Path) -> None:
    domain = tmp_path / "domain"
    domain.mkdir()
    (domain / "invalid.py").write_text(
        "from .. import infrastructure\n",
        encoding="utf-8",
    )

    assert find_violations(tmp_path) == ["domain/invalid.py imports community_bot.infrastructure"]


def test_absolute_alias_domain_violation_is_detected(tmp_path: Path) -> None:
    domain = tmp_path / "domain"
    domain.mkdir()
    (domain / "invalid.py").write_text(
        "from community_bot import infrastructure\n",
        encoding="utf-8",
    )

    assert find_violations(tmp_path) == ["domain/invalid.py imports community_bot.infrastructure"]


def test_similar_module_prefix_is_not_rejected(tmp_path: Path) -> None:
    domain = tmp_path / "domain"
    domain.mkdir()
    (domain / "valid.py").write_text(
        "import sqlalchemy_extension\nfrom community_bot import infrastructure_extension\n",
        encoding="utf-8",
    )

    assert find_violations(tmp_path) == []
