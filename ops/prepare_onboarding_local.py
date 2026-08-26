"""Prepare one invitation for a new user in the isolated local review database."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os

from sqlalchemy import select
from sqlalchemy.engine import make_url

from community_bot.application.registration import (
    InvitationCreateCommand,
    InviteTokenCodec,
    RegistrationService,
)
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import MemberModel

_DATABASE_URL = (
    "postgresql+asyncpg://community_bot_local:community_bot_local@"
    "127.0.0.1:55432/community_bot_local"
)
_DEFAULT_ADMIN_TELEGRAM_USER_ID = 900000000001
_DEFAULT_NEW_TELEGRAM_USER_ID = 900000000099
_DEFAULT_LOCAL_SECRET = "community-bot-local-onboarding-secret-v1"  # noqa: S105
_MAX_UPDATE_ID = 2**63 - 1


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", _DATABASE_URL)
    parsed = make_url(value)
    if (
        parsed.drivername != "postgresql+asyncpg"
        or parsed.host not in {"127.0.0.1", "localhost"}
        or parsed.port != 55432
        or parsed.database != "community_bot_local"
    ):
        message = (
            "Refusing to prepare onboarding outside the isolated local review database at "
            "127.0.0.1:55432/community_bot_local."
        )
        raise RuntimeError(message)
    return value


def invitation_update_id(telegram_user_id: int) -> int:
    """Return a stable non-secret receipt ID for one local review identity."""
    digest = hashlib.sha256(f"local-onboarding-invite-v1:{telegram_user_id}".encode()).digest()
    return (int.from_bytes(digest[:8], "big") & _MAX_UPDATE_ID) or 1


async def prepare(*, admin_telegram_user_id: int, new_telegram_user_id: int) -> int:
    """Create or replay the exact intended invitation without exposing its token."""
    database = Database(_database_url())
    secret = os.environ.get("INVITE_TOKEN_SECRET", _DEFAULT_LOCAL_SECRET)
    try:
        async with database.session_factory() as session:
            existing = await session.scalar(
                select(MemberModel).where(MemberModel.telegram_user_id == new_telegram_user_id)
            )
            if existing is not None:
                message = (
                    "The selected local Telegram identity already exists. "
                    "Choose another --new-user-id to test a clean registration."
                )
                raise RuntimeError(message)
        update_id = invitation_update_id(new_telegram_user_id)
        service = RegistrationService(database.unit_of_work, InviteTokenCodec(secret))
        await service.create_invitation(
            InvitationCreateCommand(
                update_id=update_id,
                actor_telegram_user_id=admin_telegram_user_id,
                intended_telegram_user_id=new_telegram_user_id,
            )
        )
        return update_id
    finally:
        await database.dispose()


def main() -> None:
    """Prepare one exact local invitation from command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-user-id", type=int, default=_DEFAULT_ADMIN_TELEGRAM_USER_ID)
    parser.add_argument("--new-user-id", type=int, default=_DEFAULT_NEW_TELEGRAM_USER_ID)
    args = parser.parse_args()
    update_id = asyncio.run(
        prepare(
            admin_telegram_user_id=args.admin_user_id,
            new_telegram_user_id=args.new_user_id,
        )
    )
    print(f"Prepared local onboarding identity {args.new_user_id}; invite receipt {update_id}.")


if __name__ == "__main__":
    main()
