from __future__ import annotations

import pytest

from community_bot.application.initial_admin import (
    InitialAdministratorCommand,
    InitialAdministratorReason,
)
from community_bot.bootstrap.initial_admin import main


@pytest.mark.parametrize("telegram_user_id", [0, -1, 9_223_372_036_854_775_808])
def test_bootstrap_command_rejects_invalid_postgresql_identity(telegram_user_id: int) -> None:
    with pytest.raises(ValueError, match="positive PostgreSQL BIGINT"):
        InitialAdministratorCommand(
            telegram_user_id=telegram_user_id,
            reason=InitialAdministratorReason.INITIAL_INSTALL,
        )


def test_bootstrap_cli_help_is_available() -> None:
    with pytest.raises(SystemExit) as error:
        main(["--help"])
    assert error.value.code == 0


def test_bootstrap_cli_rejects_reason_outside_allowlist(
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_input = "BOT_TOKEN=private-value"
    with pytest.raises(SystemExit) as error:
        main(["--telegram-user-id", "100", "--reason", private_input])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert private_input not in captured.err
    assert "invalid arguments" in captured.err
