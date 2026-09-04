"""Telegram admission, shared subscriptions and tagged community publications."""

# ruff: noqa: RUF001 - Russian interface copy.

from __future__ import annotations

import datetime
from contextlib import suppress
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)

from community_bot.application.membership import MembershipCheckUnavailableError
from community_bot.application.registration import RegistrationStartCommand
from community_bot.domain.community_preferences import (
    NOTIFICATION_CATEGORIES,
    PUBLICATION_CATEGORIES,
    PreferencesConflictError,
)
from community_bot.domain.members import MemberStatus
from community_bot.domain.registration import RegistrationError
from community_bot.infrastructure.db.activity_publications import ActivityPublicationStore
from community_bot.transport.activity_menu import TASK_CATEGORIES, activity_panel, navigation

if TYPE_CHECKING:
    from uuid import UUID

    from aiogram import Bot
    from aiogram.types import CallbackQuery, Message, User

    from community_bot.application.membership import TelegramMembershipChecker
    from community_bot.application.registration import RegistrationService
    from community_bot.bootstrap.settings import Settings
    from community_bot.infrastructure.db.community_preferences import CommunityPreferencesStore

START_BUTTON = "Начать"
APP_BUTTON = "Что за приложение?"
NOTIFICATIONS_BUTTON = "🔔 Уведомления"
NOMAD_SUBSCRIBE_BUTTON = "🔔 Подписаться: Цифровой кочевник"
NOMAD_SUBSCRIBED_BUTTON = "✓ Вы подписаны: Цифровой кочевник"
ACTIVITIES_BUTTON = "Активности и подписки"
HELP_BUTTON = "Справка"
APP_HELP = (
    "📊 Статистика сообщества\n\n"
    "Узнай, чем живёт наш чат: смотри активность за разные периоды, "
    "находи участников и сравнивай результаты в лидерборде.\n\n"
    "🏆 Ачивки и рекорды\n\n"
    "Общайся, приветствуй новичков и вовлекай других в обсуждения — "
    "за участие в жизни сообщества можно получать ачивки. "
    "В своей карточке смотри достижения и личные рекорды, "
    "а в карточках участников — их результаты.\n\n"
    "🤝 Задания и взаимопомощь\n\n"
    "Выполняй задания участников и комьюнити, чтобы зарабатывать кредиты. "
    "Нужна помощь самому? Создай своё задание, опиши ожидаемый результат "
    "и назначь награду. Ход работы и проверка результата — в приложении.\n\n"
    "💳 Кредиты и кошелёк\n\n"
    "На старте ты получаешь 20 кредитов. Их можно тратить на задания "
    "для других участников. В кошельке доступны баланс и история операций, "
    "а после 50 кредитов, заработанных за задания, открываются переводы "
    "между участниками.\n\n"
    "👇 Начни со своей статистики и ачивок — или найди первое задание."
)


def home_keyboard() -> ReplyKeyboardMarkup:
    """Keep a compact native menu visible without changing secure Mini App launch."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ACTIVITIES_BUTTON)],
            [KeyboardButton(text=HELP_BUTTON)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder="Выберите действие в меню",
    )


class TelegramUpdates:
    """Telegram identities are accepted only after the secret-checked webhook boundary."""

    def __init__(
        self,
        *,
        bot: Bot,
        settings: Settings,
        store: CommunityPreferencesStore,
        registration: RegistrationService,
        membership: TelegramMembershipChecker,
    ) -> None:
        """Compose the private menu and configured community publication listener."""
        self.bot, self.settings, self.store = bot, settings, store
        self.registration, self.membership = registration, membership
        self.publications = ActivityPublicationStore(store.sessions)

    async def handle(self, body: bytes) -> None:
        """Process allowlisted update kinds without retaining private message bodies."""
        update = Update.model_validate_json(body)
        if update.callback_query is not None:
            await self._callback(update.update_id, update.callback_query)
            return
        message = update.message or update.edited_message
        if message is None:
            return  # Channel posts and unrelated update types never create a campaign.
        if message.chat.type == "private":
            if update.edited_message is not None:
                return
            if message.from_user is None or message.from_user.is_bot:
                return
            text = message.text or ""
            command = text.split(maxsplit=1)[0].split("@")[0] if text else ""
            aliases = {
                START_BUTTON: "/start",
                APP_BUTTON: "/app",
                "📱 Приложение": "/app",
                NOTIFICATIONS_BUTTON: "/notifications",
                NOMAD_SUBSCRIBE_BUTTON: "/nomad_subscribe",
                NOMAD_SUBSCRIBED_BUTTON: "/nomad",
                ACTIVITIES_BUTTON: "/notifications",
                HELP_BUTTON: "/help",
            }
            if text in aliases:
                command = text = aliases[text]
            if command in {
                "/start",
                "/notifications",
                "/app",
                "/help",
                "/nomad",
                "/nomad_subscribe",
            }:
                await self._private_command(update.update_id, message.from_user, command, text)
            return
        if (
            message.chat.id != self.settings.community_telegram_chat_id
            or message.sender_chat is not None
            or message.from_user is None
            or message.from_user.is_bot
            or message.forward_origin is not None
            or not self._is_publication(message)
        ):
            return
        text = message.text or message.caption or ""
        encoded = text.encode("utf-16-le")
        tags = {
            encoded[entity.offset * 2 : (entity.offset + entity.length) * 2]
            .decode("utf-16-le", errors="ignore")
            .casefold()
            .removeprefix("#")
            for entity in (message.entities or message.caption_entities or [])
            if entity.type == "hashtag"
        }
        edited = message.edit_date
        occurred_at = (
            datetime.datetime.fromtimestamp(edited, datetime.UTC)
            if isinstance(edited, int)
            else edited or message.date
        )
        await self.publications.observe(
            update_id=update.update_id,
            author_id=message.from_user.id,
            chat_id=message.chat.id,
            topic_id=message.message_thread_id,
            message_id=message.message_id,
            occurred_at=occurred_at,
            categories=tags & PUBLICATION_CATEGORIES,
            album_id=message.media_group_id,
        )

    @staticmethod
    def _is_publication(message: Message) -> bool:
        return bool(
            message.text
            or message.photo
            or message.video
            or message.document
            or message.audio
            or message.voice
            or message.poll
        )

    async def _member_gate(self, user_id: int) -> bool:
        chat_id = self.settings.community_telegram_chat_id
        if chat_id is None:
            await self._send(user_id, "Проверка участия пока не настроена. Попробуйте позже.")
            return False
        try:
            joined = await self.membership.is_member(chat_id=chat_id, telegram_user_id=user_id)
        except MembershipCheckUnavailableError:
            await self._send(user_id, "Не удалось проверить участие в чате. Попробуйте позже.")
            return False
        if not joined:
            buttons = []
            if self.settings.community_telegram_join_url:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text="Вступить в чат", url=self.settings.community_telegram_join_url
                        )
                    ]
                )
            buttons.append(
                [InlineKeyboardButton(text="Проверить участие", callback_data="community:check")]
            )
            await self._send(user_id, "Бот и приложение доступны только участникам чата.", buttons)
        return joined

    async def _private_command(  # noqa: PLR0911 - explicit membership, status and menu gates.
        self,
        update_id: int,
        user: User,
        command: str,
        text: str,
    ) -> None:
        if not await self._member_gate(user.id):
            return
        existing = await self.store.member_for_telegram(user.id)
        if existing is not None and existing.status not in {"active", "pending"}:
            await self._send(user.id, "Доступ к приложению ограничен. Обратитесь к администратору.")
            return
        if command in {"/notifications", "/nomad", "/nomad_subscribe", "/help"}:
            if existing is None or existing.status != "active":
                await self._send(
                    user.id,
                    "Сначала завершите регистрацию — нажмите кнопку ниже.",
                    [[InlineKeyboardButton(text="Продолжить", callback_data="community:check")]],
                )
                return
            if command == "/help":
                await self._show_help(user.id)
            else:
                await self._show_preferences(
                    user.id, existing.id, page="nomad" if command.startswith("/nomad") else "all"
                )
            return
        if command == "/app" and existing is not None and existing.status == "active":
            await self._send(
                user.id,
                APP_HELP,
                self._launch_buttons(),
            )
            return
        parts = text.split(maxsplit=1)
        invitation = parts[1] if len(parts) == 2 and len(parts[1]) <= 256 else None  # noqa: PLR2004
        try:
            view = await self.registration.start(
                RegistrationStartCommand(
                    update_id=update_id,
                    telegram_user_id=user.id,
                    telegram_username=user.username,
                    telegram_display_name=user.full_name,
                    invitation_token=invitation,
                    community_membership_verified=True,
                )
            )
        except RegistrationError:
            await self._send(user.id, "Приглашение недействительно. Обратитесь к администратору.")
            return
        if view.context is None:
            await self._send(
                user.id, "Сейчас вход по приглашению. Получите ссылку у администратора."
            )
            return
        active = view.context.member_status is MemberStatus.ACTIVE
        if active:
            await self._send(
                user.id,
                "Добро пожаловать!\n\n"
                "Статистика, ачивки и задания — в приложении.\n\n"
                "Выбери интересные активности ниже. Подписки добровольные, "
                "их можно изменить в любой момент.",
                reply_keyboard=home_keyboard(),
            )
            await self._show_preferences(user.id, view.context.member_id)
        else:
            await self._send(
                user.id,
                "Продолжите регистрацию в приложении.",
                self._launch_buttons("Продолжить регистрацию"),
            )

    def _launch_buttons(self, label: str = "Открыть приложение") -> list:
        # A regular reply-keyboard web_app does not provide the user initData
        # required by our auth. Keep the main-app Telegram launch instead.
        if not self.settings.telegram_bot_username:
            return []
        return [
            [
                InlineKeyboardButton(
                    text=label,
                    url=f"https://t.me/{self.settings.telegram_bot_username}?startapp",
                )
            ]
        ]

    async def _callback(  # noqa: C901, PLR0911 - gated navigation, confirmation and revisioned writes.
        self, update_id: int, callback: CallbackQuery
    ) -> None:
        # Ignore inline/forwarded keyboards and callbacks from outside the bot's private dialog.
        if (
            callback.message is None
            or callback.message.chat.type != "private"
            or callback.message.chat.id != callback.from_user.id
            or callback.from_user.is_bot
        ):
            return
        with suppress(TelegramBadRequest):
            await self.bot.answer_callback_query(callback.id)
        if callback.data == "community:check":
            await self._private_command(update_id, callback.from_user, "/start", "/start")
            return
        if not (callback.data or "").startswith(
            ("activities:", "subscription:", "confirm:", "notifications:", "nomad:", "help:")
        ):
            return
        if not await self._member_gate(callback.from_user.id):
            return
        member = await self.store.member_for_telegram(callback.from_user.id)
        if member is None or member.status != "active":
            return
        parts = (callback.data or "").split(":")
        if parts[0] == "help":
            if callback.data == "help:app":
                await self._edit_or_send(
                    callback.from_user.id,
                    APP_HELP,
                    [
                        *self._launch_buttons(),
                        [InlineKeyboardButton(text="Назад к справке", callback_data="help:all")],
                    ],
                    callback.message.message_id,
                )
            else:
                await self._show_help(callback.from_user.id, callback.message.message_id)
            return
        page = parts[1] if parts[0] == "activities" and len(parts) == 2 else "all"  # noqa: PLR2004
        note = ""
        if (
            len(parts) == 4  # noqa: PLR2004 - versioned callback's four explicit fields.
            and parts[0] in {"subscription", "confirm", "notifications", "nomad"}
            and parts[1] in NOTIFICATION_CATEGORIES
            and parts[2] in {"0", "1"}
            and parts[3].isdigit()
        ):
            category = parts[1]
            page = "tasks_group" if category in TASK_CATEGORIES else category
            if (
                parts[0] != "confirm"
                and parts[2] == "0"
                and category in {"task_updates", "task_reminders", "disputes"}
            ):
                await self._edit_or_send(
                    callback.from_user.id,
                    "Отключить уведомления?\n\nМожно пропустить изменения или сроки "
                    "по своим заданиям и спорам. "
                    "Сами события останутся доступны в приложении.",
                    [
                        [
                            InlineKeyboardButton(
                                text="Отключить", callback_data=f"confirm:{category}:0:{parts[3]}"
                            )
                        ],
                        [navigation("Оставить включёнными", page)],
                    ],
                    callback.message.message_id,
                )
                return
            try:
                await self.store.set_preference(member.id, category, parts[2] == "1", int(parts[3]))
            except PreferencesConflictError:
                note = (
                    "Настройки уже изменились. Показываю актуальное состояние — повтори выбор.\n\n"
                )
        await self._show_preferences(
            callback.from_user.id, member.id, callback.message.message_id, page=page, note=note
        )

    async def _show_help(self, user_id: int, message_id: int | None = None) -> None:
        await self._edit_or_send(
            user_id,
            "Справка\n\nЧто хочешь узнать?",
            [
                [navigation("Об активностях и подписках", "help")],
                [InlineKeyboardButton(text=APP_BUTTON, callback_data="help:app")],
            ],
            message_id,
        )

    async def _show_preferences(
        self,
        user_id: int,
        member_id: UUID,
        message_id: int | None = None,
        *,
        page: str = "all",
        note: str = "",
    ) -> None:
        preferences = await self.store.preferences(member_id)
        text, buttons = activity_panel(preferences, page)
        await self._edit_or_send(user_id, note + text, buttons, message_id)

    async def _edit_or_send(
        self, user_id: int, text: str, buttons: list, message_id: int | None
    ) -> None:
        if message_id is not None:
            try:
                await self.bot.edit_message_text(
                    text=text,
                    chat_id=user_id,
                    message_id=message_id,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                )
            except TelegramBadRequest as error:
                if "message is not modified" in error.message.casefold():
                    return
            else:
                return
        await self._send(user_id, text, buttons)

    async def _send(
        self,
        user_id: int,
        text: str,
        buttons: list | None = None,
        *,
        reply_keyboard: ReplyKeyboardMarkup | None = None,
    ) -> None:
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_keyboard
                or (
                    InlineKeyboardMarkup(inline_keyboard=buttons)
                    if buttons
                    else ReplyKeyboardRemove()
                ),
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            return
