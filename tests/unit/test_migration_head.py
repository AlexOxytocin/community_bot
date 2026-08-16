"""Unit coverage for the packaged exact-single-head command."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from community_bot.bootstrap import migration_head


@pytest.mark.parametrize("heads", [[], ["0020", "branch_head"]])
def test_migration_head_rejects_zero_or_multiple_heads(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    heads: list[str],
) -> None:
    """An ambiguous packaged graph cannot publish an expected revision."""
    monkeypatch.setattr(
        migration_head.ScriptDirectory,
        "from_config",
        lambda _config: SimpleNamespace(get_heads=lambda: heads),
    )

    assert migration_head.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Packaged migration graph must have exactly one valid head.\n"


def test_migration_head_prints_one_valid_head(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The sole packaged graph head is the complete stdout contract."""
    monkeypatch.setattr(
        migration_head.ScriptDirectory,
        "from_config",
        lambda _config: SimpleNamespace(get_heads=lambda: ["0020"]),
    )

    assert migration_head.main() == 0
    captured = capsys.readouterr()
    assert captured.out == "0020\n"
    assert captured.err == ""


@pytest.mark.parametrize("head", ["", "bad head", "line\nbreak", "@invalid"])
def test_migration_head_rejects_invalid_revision_identifier(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    head: str,
) -> None:
    """Whitespace and shell-like output cannot cross the image boundary."""
    monkeypatch.setattr(
        migration_head.ScriptDirectory,
        "from_config",
        lambda _config: SimpleNamespace(get_heads=lambda: [head]),
    )

    assert migration_head.main() == 1
    assert capsys.readouterr().out == ""


def test_migration_head_fails_closed_when_graph_cannot_be_loaded(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Internal Alembic details are not leaked when graph loading fails."""

    def fail_to_load(_config: object) -> object:
        message = "private migration loader failure"
        raise RuntimeError(message)

    monkeypatch.setattr(migration_head.ScriptDirectory, "from_config", fail_to_load)

    assert migration_head.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private" not in captured.err
