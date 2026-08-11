"""CLI entry point for the idempotent first product configuration bootstrap."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

import structlog
from sqlalchemy import select

from community_bot.application.economy import ProductConfigBootstrapCoordinator
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.bootstrap.settings import get_settings
from community_bot.domain.economy import ProductConfigError
from community_bot.domain.members import AuthorizationError
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.db.models import MemberModel
from community_bot.infrastructure.observability import configure_logging, configure_sentry

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Create the first active product config or return exact replay success."""
    parser = argparse.ArgumentParser(prog="community-bootstrap-product-config")
    parser.add_argument(
        "--candidate",
        type=Path,
        default=Path("config/product-config.v2.json"),
    )
    arguments = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_sentry(
        settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release,
    )
    try:
        version = asyncio.run(_bootstrap(settings.database_url, arguments.candidate))
    except (AuthorizationError, ProductConfigError, ValueError):
        structlog.get_logger(process="community-bootstrap-product-config").error(
            "product_config_bootstrap_rejected"
        )
        return 2
    except Exception:  # noqa: BLE001 - CLI must fail closed with a safe log.
        structlog.get_logger(process="community-bootstrap-product-config").error(
            "product_config_bootstrap_failed"
        )
        return 1
    structlog.get_logger(process="community-bootstrap-product-config").info(
        "product_config_bootstrap_succeeded",
        version=version,
    )
    return 0


async def _bootstrap(database_url: str, candidate_path: Path) -> int:
    database = Database(database_url)
    coordinator = ProductConfigBootstrapCoordinator(
        database.unit_of_work,
        load_product_config_candidate,
    )
    try:
        try:
            return (
                await coordinator.prepare(
                    candidate_path=None,
                    actor_member_id=None,
                    activation_command_id=None,
                )
            ).version
        except ProductConfigError:
            pass

        async with database.session_factory() as session:
            administrators = (
                await session.scalars(
                    select(MemberModel).where(
                        MemberModel.role == "administrator",
                        MemberModel.status == "active",
                    )
                )
            ).all()
        if len(administrators) != 1:
            message = (
                "The first product config bootstrap requires exactly one active administrator."
            )
            raise AuthorizationError(message)
        candidate = load_product_config_candidate(candidate_path)
        active = await coordinator.prepare(
            candidate_path=candidate_path,
            actor_member_id=administrators[0].id,
            activation_command_id=uuid5(
                NAMESPACE_URL,
                f"community-bot:product-config-bootstrap:{candidate.content_hash}",
            ),
        )
        return active.version
    finally:
        await database.dispose()
