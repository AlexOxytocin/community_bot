"""Explicit, non-startup setup of the minimal Telegram webhook and bot menu."""

from __future__ import annotations

import argparse
import asyncio
import json

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import BotCommand

from community_bot.bootstrap.settings import get_settings


async def configure(*, apply: bool) -> dict[str, object]:
    """Preflight by default; never take over a different webhook or discard updates."""
    settings = get_settings()
    if (
        settings.bot_token is None
        or settings.telegram_webhook_secret is None
        or settings.mini_app_origin is None
        or not settings.mini_app_origin.startswith("https://")
        or settings.community_telegram_chat_id is None
    ):
        message = "Configure HTTPS origin, bot, webhook secret and community first"
        raise ValueError(message)
    url = settings.mini_app_origin.rstrip("/") + "/api/telegram/webhook"
    async with Bot(token=settings.bot_token.get_secret_value()) as bot:
        identity, webhook = await asyncio.gather(bot.get_me(), bot.get_webhook_info())
        if identity.username != settings.telegram_bot_username:
            message = "Configured bot username does not match the token"
            raise ValueError(message)
        if webhook.url and webhook.url != url:
            message = "Another webhook is installed; explicit coordinated cutover is required"
            raise ValueError(message)
        core = await bot.get_chat_member(settings.community_telegram_chat_id, identity.id)
        if core.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
            message = "Community bot must be an administrator for reliable membership checks"
            raise ValueError(message)
        commands = {command.command: command for command in await bot.get_my_commands()}
        commands.update(
            start=BotCommand(command="start", description="Запустить приложение"),
            notifications=BotCommand(command="notifications", description="Настройки уведомлений"),
            help=BotCommand(command="help", description="Справка"),
        )
        if len(commands) > 100:  # noqa: PLR2004 - Telegram Bot API command limit.
            message = "Bot command list is full"
            raise ValueError(message)
        if apply:
            await bot.set_webhook(
                url=url,
                secret_token=settings.telegram_webhook_secret.get_secret_value(),
                allowed_updates=sorted(
                    set(webhook.allowed_updates or ["message", "callback_query"])
                    | {"message", "edited_message", "callback_query", "chat_member"}
                ),
                drop_pending_updates=False,
            )
            await bot.set_my_commands(list(commands.values()))
            verified = await bot.get_webhook_info()
            if verified.url != url or not {"edited_message", "chat_member"} <= set(
                verified.allowed_updates or []
            ):
                message = "Webhook verification failed"
                raise RuntimeError(message)
        return {
            "preflight": "passed",
            "applied": apply,
            "source_chat": settings.community_telegram_chat_id,
        }


def main() -> None:
    """Run only during an explicitly authorized Telegram release."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Install webhook and merge bot commands"
    )
    arguments = parser.parse_args()
    print(json.dumps(asyncio.run(configure(apply=arguments.apply))))  # noqa: T201 - safe CLI summary.


if __name__ == "__main__":
    main()
