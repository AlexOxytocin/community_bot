"""Explicit one-time menu delivery; never run on startup or retry ambiguous sends."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select

from community_bot.application.membership import MembershipCheckUnavailableError
from community_bot.bootstrap.settings import get_settings
from community_bot.infrastructure.db.community_preferences import CommunityPreferencesStore
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import MemberModel
from community_bot.infrastructure.telegram_membership import AiogramTelegramMembershipChecker
from community_bot.transport.telegram_updates import home_keyboard

if TYPE_CHECKING:
    from uuid import UUID

    from community_bot.application.membership import TelegramMembershipChecker

CAMPAIGN = "bottom-menu-nomad-v1"
MENU_UPDATED = (
    "Меню обновлено.\n\n"
    "Теперь можно подписаться на активность «Цифрового кочевника» кнопкой внизу. "
    "«Начать» запускает меню без ввода команды.\n\n"
    "Твои настройки уведомлений сохранены."
)


def claim_receipt(path: Path) -> bool:
    """Reserve a durable attempt exclusively before contacting Telegram."""
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write("attempted")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        return False
    return True


async def deliver_menu(  # noqa: PLR0911, PLR0913 - explicit eligibility gates and dependencies.
    *,
    bot: Bot,
    store: CommunityPreferencesStore,
    membership: TelegramMembershipChecker,
    chat_id: int,
    member_id: UUID,
    telegram_user_id: int,
    receipts: Path,
    apply: bool,
) -> str:
    """Recheck eligibility and preferences; report no private identities or API errors."""
    receipt = receipts / f"{member_id}.receipt"
    if receipt.exists():
        return "already_attempted"
    member = await store.member_for_telegram(telegram_user_id)
    if member is None or member.id != member_id or member.status != "active":
        return "ineligible"
    try:
        if not await membership.is_member(chat_id=chat_id, telegram_user_id=telegram_user_id):
            return "not_in_chat"
    except MembershipCheckUnavailableError:
        return "membership_unavailable"
    preferences = await store.preferences(member_id)
    if not apply:
        return "eligible"
    if not claim_receipt(receipt):
        return "already_attempted"
    try:
        await bot.send_message(
            chat_id=telegram_user_id,
            text=MENU_UPDATED,
            reply_markup=home_keyboard(nomad=bool(preferences["nomad"])),
            disable_notification=True,
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        outcome = "unreachable"
    except (TelegramAPIError, TimeoutError):
        outcome = "uncertain"
    else:
        outcome = "sent"
    with receipt.open("w", encoding="utf-8") as stream:
        stream.write(outcome)
        stream.flush()
        os.fsync(stream.fileno())
    return outcome


async def refresh(*, receipt_root: Path, apply: bool) -> dict[str, object]:
    """Dry run by default; receipts must be on a persistent mounted directory."""
    settings = get_settings()
    if settings.bot_token is None or settings.community_telegram_chat_id is None:
        message = "Bot and community identity are required"
        raise RuntimeError(message)
    receipts = receipt_root / CAMPAIGN
    if apply:
        receipts.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = settings.bot_token.get_secret_value()
    database = Database(settings.database_url)
    store = CommunityPreferencesStore(database.session_factory)
    membership = AiogramTelegramMembershipChecker(token)
    counts: Counter[str] = Counter()
    try:
        async with Bot(token) as bot:
            identity = await bot.get_me()
            if identity.username != settings.telegram_bot_username:
                message = "Bot identity mismatch"
                raise RuntimeError(message)
            async with database.session_factory() as session:
                members = (
                    await session.execute(
                        select(MemberModel.id, MemberModel.telegram_user_id)
                        .where(MemberModel.status == "active", MemberModel.telegram_user_id > 0)
                        .order_by(MemberModel.id)
                    )
                ).all()
            for member_id, telegram_user_id in members:
                outcome = await deliver_menu(
                    bot=bot,
                    store=store,
                    membership=membership,
                    chat_id=settings.community_telegram_chat_id,
                    member_id=member_id,
                    telegram_user_id=telegram_user_id,
                    receipts=receipts,
                    apply=apply,
                )
                counts[outcome] += 1
                await asyncio.sleep(0.1)
    finally:
        await membership.close()
        await database.dispose()
    return {"campaign": CAMPAIGN, "applied": apply, "counts": dict(counts)}


def main() -> None:
    """Print aggregate delivery outcomes only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    try:
        result = asyncio.run(refresh(receipt_root=arguments.receipt_root, apply=arguments.apply))
    except Exception:  # noqa: BLE001 - CLI boundary must never print secrets from transport errors.
        # Transport/database exceptions may contain credentials; receipts survive interruption.
        message = "Menu refresh failed; inspect private receipts before any retry."
        raise SystemExit(message) from None
    print(json.dumps(result))  # noqa: T201 - safe operational summary.


if __name__ == "__main__":
    main()
