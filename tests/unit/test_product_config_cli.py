"""Direct coverage for the retained product-config bootstrap CLI."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from community_bot.bootstrap import product_config_cli
from community_bot.domain.economy import ProductConfigError


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("success", 0), ("rejected", 2), ("failed", 1)],
)
def test_product_config_cli_maps_safe_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    expected: int,
) -> None:
    async def bootstrap(_url: str, _candidate: object) -> int:
        if outcome == "rejected":
            raise ProductConfigError
        if outcome == "failed":
            raise RuntimeError
        return 2

    monkeypatch.setattr(
        product_config_cli,
        "get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://db",
            log_level="INFO",
            sentry_dsn=None,
            environment="test",
            release="test",
        ),
    )
    monkeypatch.setattr(product_config_cli, "configure_logging", lambda _level: None)
    monkeypatch.setattr(
        product_config_cli,
        "configure_sentry",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(product_config_cli, "_bootstrap", bootstrap)

    assert product_config_cli.main([]) == expected
