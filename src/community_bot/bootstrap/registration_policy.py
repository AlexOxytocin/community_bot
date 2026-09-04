"""Explicit audited registration-policy activation during an authorized release."""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select

from community_bot.bootstrap.settings import get_settings
from community_bot.infrastructure.db.community_preferences import CommunityPreferencesStore
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import MemberModel


async def configure(*, apply: bool) -> dict[str, object]:
    """Dry-run by default; require a unique active owner and preserve optimistic concurrency."""
    database = Database(get_settings().database_url)
    try:
        async with database.session_factory() as session:
            owners = (
                await session.scalars(
                    select(MemberModel.id).where(
                        MemberModel.status == "active",
                        MemberModel.role == "administrator",
                        MemberModel.permissions_json.contains(["superadministrator"]),
                    )
                )
            ).all()
        if len(owners) != 1:
            message = "A unique active superadministrator is required for release activation."
            raise RuntimeError(message)
        store = CommunityPreferencesStore(database.session_factory)
        before = await store.policy(owners[0])
        revision = before["revision"]
        if not isinstance(revision, int):
            message = "Invalid policy revision."
            raise TypeError(message)
        after = await store.set_policy(owners[0], "simplified", revision) if apply else before
        return {"applied": apply, "before": before, "after": after}
    finally:
        await database.dispose()


def main() -> None:
    """Enable only the already approved simplified mode, never weaken membership checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(configure(apply=args.apply))))  # noqa: T201


if __name__ == "__main__":
    main()
