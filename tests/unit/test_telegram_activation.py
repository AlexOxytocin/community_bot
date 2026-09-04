"""Bounded configuration activation and rollback, without any Telegram traffic."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from ops import telegram_activation as activation

if TYPE_CHECKING:
    from pathlib import Path


def test_environment_changes_only_scoped_values() -> None:
    before = "# retained\nBOT_TOKEN=private\nUNRELATED=x\nNOMAD_TELEGRAM_TOPIC_ID=1\n"
    after = activation.environment_content(before, "new-secret").decode()
    assert "BOT_TOKEN=private\nUNRELATED=x\n" in after
    assert "NOMAD_TELEGRAM_TOPIC_ID=1\n" not in after
    assert after.count("NOMAD_TELEGRAM_TOPIC_ID=") == 1
    assert "NOMAD_TELEGRAM_TOPIC_ID=24962" in after
    assert after.count("COMMUNITY_ENTRY_TOPIC_ID=") == 1
    assert "COMMUNITY_ENTRY_TOPIC_ID=21568" in after
    compile(activation.RUNTIME, "runtime-probe", "exec")


@pytest.mark.parametrize("failure", [None, "recreate", "verify", "edge", "apply"])
def test_activation_recovers_configuration_and_menu(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str | None,
) -> None:
    events = []
    old = {
        "commands": [],
        "url": "https://example.test/api/telegram/webhook",
        "menu": {},
        "webhook": {"url": ""},
    }
    state = {
        "telegram": old,
        "phase": "prepared",
        "env_sha256": "digest",
        "new_env_sha256": "digest",
    }
    pending = failure

    def event(name: str) -> None:
        nonlocal pending
        events.append(name)
        if name == pending:
            pending = None
            message = "injected"
            raise activation.CutoverError(message)

    def runtime(action: str, data: dict | None = None) -> dict:
        del data
        event(action)
        return old

    monkeypatch.setattr(activation, "validate", lambda _: event("validate"))
    monkeypatch.setattr(activation, "digest", lambda _: "digest")
    monkeypatch.setattr(activation, "save", lambda *_: None)
    monkeypatch.setattr(activation, "runtime", runtime)
    monkeypatch.setattr(activation, "replace_env", lambda path: event(path.name))
    monkeypatch.setattr(activation, "compose", lambda *_: event("recreate"))
    monkeypatch.setattr(activation, "verify", lambda _: event("verify"))
    monkeypatch.setattr(
        activation,
        "edge",
        lambda *_, **kwargs: event("edge_restore" if kwargs.get("old") else "edge"),
    )
    if failure:
        with pytest.raises(activation.CutoverError, match="injected"):
            activation.apply(state, tmp_path / "receipt.json")
        assert events[-5:] == ["old.env", "recreate", "verify", "edge_restore", "restore"]
        assert state["phase"] == "rolled_back"
    else:
        activation.apply(state, tmp_path / "receipt.json")
        assert state["phase"] == "ready"
        assert "restore" not in events


def test_nginx_adds_only_exact_webhook_and_is_idempotent() -> None:
    original = (
        "server {\n    server_name allo.godmodetools.com;\n"
        "    location /api/v1/ {\n    }\n    location / { return 404; }\n}\n"
    )
    changed = activation.nginx_content(original).decode()
    assert changed.replace(activation.WEBHOOK_LOCATION, "") == original
    assert activation.nginx_content(changed).decode() == changed
    with pytest.raises(activation.CutoverError, match="Ambiguous nginx"):
        activation.nginx_content(original + original)
