"""Minimal Telegram ingress: admission, shared subscriptions, and one topic."""

# ruff: noqa: RUF001 - Russian interface copy.

from __future__ import annotations

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
from community_bot.domain.community_preferences import PreferencesConflictError
from community_bot.domain.members import MemberStatus
from community_bot.domain.registration import RegistrationError

if TYPE_CHECKING:
    from uuid import UUID

    from aiogram import Bot
    from aiogram.types import CallbackQuery, Message, User

    from community_bot.application.membership import TelegramMembershipChecker
    from community_bot.application.registration import RegistrationService
    from community_bot.bootstrap.settings import Settings
    from community_bot.infrastructure.db.community_preferences import CommunityPreferencesStore

APP_BUTTON = "Что за приложение?"
NOTIFICATIONS_BUTTON = "🔔 Уведомления"
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
        keyboard=[[KeyboardButton(text=APP_BUTTON), KeyboardButton(text=NOTIFICATIONS_BUTTON)]],
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
        """Compose one private menu and the configured forum-topic listener."""
        self.bot, self.settings, self.store = bot, settings, store
        self.registration, self.membership = registration, membership

    async def handle(self, body: bytes) -> None:
        """Process allowlisted update kinds without retaining private message bodies."""
        update = Update.model_validate_json(body)
        if update.callback_query is not None:
            await self._callback(update.update_id, update.callback_query)
            return
        message = update.message
        if message is None:
            return  # Edits, channel posts and service updates never create a campaign.
        if message.chat.type == "private":
            if message.from_user is None or message.from_user.is_bot:
                return
            text = message.text or ""
            command = text.split(maxsplit=1)[0].split("@")[0] if text else ""
            if text in {APP_BUTTON, "📱 Приложение"}:
                command, text = "/app", "/app"
            elif text == NOTIFICATIONS_BUTTON:
                command, text = "/notifications", "/notifications"
            if command in {"/start", "/notifications", "/app"}:
                await self._private_command(update.update_id, message.from_user, command, text)
            return
        if (
            message.chat.id != self.settings.nomad_telegram_chat_id
            or message.message_thread_id is None
            or message.message_thread_id != self.settings.nomad_telegram_topic_id
            or not message.is_topic_message
            or message.sender_chat is not None
            or message.from_user is None
            or message.from_user.is_bot
            or not self._is_publication(message)
        ):
            return
        await self.store.publish_nomad(
            author_id=message.from_user.id,
            chat_id=message.chat.id,
            topic_id=message.message_thread_id,
            message_id=message.message_id,
            published_at=message.date,
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
        if command == "/notifications":
            if existing is None or existing.status != "active":
                await self._send(
                    user.id,
                    "Сначала завершите регистрацию — нажмите кнопку ниже.",
                    [[InlineKeyboardButton(text="Продолжить", callback_data="community:check")]],
                )
                return
            await self._show_preferences(user.id, existing.id)
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
                "Задания, сообщество и кошелёк — в приложении.\n"
                "Настройки уведомлений — в меню ниже.",
                reply_keyboard=home_keyboard(),
            )
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

    async def _callback(self, update_id: int, callback: CallbackQuery) -> None:
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
        if not (callback.data or "").startswith("notifications:"):
            return
        if not await self._member_gate(callback.from_user.id):
            return
        member = await self.store.member_for_telegram(callback.from_user.id)
        if member is None or member.status != "active":
            return
        parts = (callback.data or "").split(":")
        if (
            len(parts) == 4  # noqa: PLR2004 - versioned callback's four explicit fields.
            and parts[1] in {"tasks", "nomad"}
            and parts[2] in {"0", "1"}
            and parts[3].isdigit()
        ):
            with suppress(PreferencesConflictError):
                await self.store.set_preference(member.id, parts[1], parts[2] == "1", int(parts[3]))
        await self._show_preferences(callback.from_user.id, member.id, callback.message.message_id)

    async def _show_preferences(
        self, user_id: int, member_id: UUID, message_id: int | None = None
    ) -> None:
        preferences = await self.store.preferences(member_id)
        buttons = [
            [
                InlineKeyboardButton(
                    text=f"{'☑' if preferences[key] else '☐'} {label}",
                    callback_data=(
                        f"notifications:{key}:{int(not preferences[key])}:{preferences['revision']}"
                    ),
                )
            ]
            for key, label in (("tasks", "Задания"), ("nomad", "Цифровой кочевник"))
        ]
        text = (
            "Уведомления\n\n"
            "Подписаться на события Цифрового кочевника\n"
            "Новые публикации суперадминистратора со ссылкой на сообщение.\n\n"
            "Задания\nНовые задания, изменения и напоминания. По умолчанию выключены.\n\n"
            "Выберите нужные подписки кнопками ниже. Настройки общие с приложением."
        )
        if message_id is not None:
            try:
                await self.bot.edit_message_text(
                    text=text,
                    chat_id=user_id,
                    message_id=message_id,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                )
            except TelegramBadRequest:
                pass
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
