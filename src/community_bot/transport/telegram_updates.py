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
APP_BUTTON = "Зачем мне приложение?"
NOTIFICATIONS_BUTTON = "🔔 Уведомления"
NOMAD_SUBSCRIBE_BUTTON = "🔔 Подписаться: Цифровой кочевник"
NOMAD_SUBSCRIBED_BUTTON = "✓ Вы подписаны: Цифровой кочевник"
ACTIVITIES_BUTTON = "Активности и подписки"
HELP_BUTTON = "Справка"
ONBOARDING_INTRO = (
    "👋 Добро пожаловать!\n\n"
    "Это бот сообщества «Алло, Нейросеточная» — пространства, где участники "
    "знакомятся, помогают друг другу "
    "и развивают свои проекты.\n\n"
    "Здесь ты сможешь:\n"
    "• находить полезных людей и взаимопомощь;\n"
    "• участвовать в онлайн- и офлайн-ивентах;\n"
    "• наблюдать за экспериментами с ИИ, участвовать в них и влиять на их развитие;\n"
    "• выполнять задания, зарабатывать кредиты и создавать свои.\n\n"
    "Присоединяйся к чату — после вступления бот сам создаст твой профиль."
)
WHY_APP_HELP = (
    "📱 Зачем нужно приложение?\n\n"
    "Бот помогает не пропускать интересные активности, а приложение открывает "
    "остальные возможности сообщества.\n\n"
    "В приложении можно:\n"
    "• находить участников и узнавать, чем они занимаются;\n"
    "• смотреть статистику сообщества, свою активность, уровни и ачивки;\n"
    "• выполнять задания других участников и получать кредиты;\n"
    "• создавать задания, когда нужна помощь с проектом, соцсетями, GitHub, "
    "консультацией или знакомствами;\n"
    "• управлять кошельком и смотреть историю операций.\n\n"
    "Пользоваться приложением необязательно. Можно просто выбрать интересные "
    "подписки и получать уведомления в этом боте. Если понадобятся дополнительные "
    "возможности — приложение всегда рядом."
)
ONBOARDING_DONE = (
    "✅ Всё готово!\n\n"
    "Теперь бот будет присылать новости только по выбранным тобой направлениям.\n\n"
    "Приложение открывать необязательно — подписками можно пользоваться прямо здесь. "
    "Если захочешь узнать больше об участниках, заданиях и своей активности, "
    "приложение всегда будет доступно в меню бота."
)
APP_HELP = (
    "🤝 Задания и взаимопомощь\n\n"
    "Развиваешь проект в одиночку, продвигаешь свои соцсети или просто нуждаешься "
    "в помощи? Здесь можно обмениваться опытом и помогать друг другу — "
    "от небольшого совета до конкретной задачи.\n\n"
    "Например:\n"
    "• Для солопренёров и авторов проектов — проверить идею, протестировать продукт, "
    "получить обратную связь по сайту или презентации.\n"
    "• Для соцсетей — разобрать профиль, придумать темы публикаций, "
    "улучшить текст или обсудить продвижение.\n"
    "• Для GitHub — проверить установку проекта, найти баг, "
    "получить ревью кода или сделать README понятнее.\n"
    "• Для консультаций — разобраться в разработке, дизайне, маркетинге "
    "или другом вопросе с помощью участника с нужным опытом.\n"
    "• Для знакомств — найти единомышленников, партнёра для совместного проекта "
    "или попросить познакомить с нужным специалистом.\n"
    "• Для повседневных задач — перевести текст, выбрать инструмент "
    "или попросить о другой посильной помощи.\n\n"
    "Создай задание, опиши, какая помощь нужна и какой результат ты ожидаешь, "
    "и назначь награду в кредитах. А выполняя задания других участников "
    "и комьюнити, зарабатывай кредиты на свои задачи. "
    "Ход работы и проверка результата — в приложении.\n\n"
    "📊 Статистика сообщества\n\n"
    "Узнай, чем живёт наш чат: смотри активность за разные периоды, "
    "находи участников и сравнивай результаты в лидерборде.\n\n"
    "🏆 Ачивки и рекорды\n\n"
    "Общайся, приветствуй новичков и вовлекай других в обсуждения — "
    "за участие в жизни сообщества можно получать ачивки. "
    "В своей карточке смотри достижения и личные рекорды, "
    "а в карточках участников — их результаты.\n\n"
    "💳 Кредиты и кошелёк\n\n"
    "На старте ты получаешь 20 кредитов. Их можно тратить на задания "
    "для других участников. В кошельке доступны баланс и история операций, "
    "а после 50 кредитов, заработанных за задания, открываются переводы "
    "между участниками.\n\n"
    "👇 Найди первое задание или создай своё — начни с того, где тебе нужна помощь."
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

    async def handle(self, body: bytes) -> None:  # noqa: C901, PLR0911
        """Process allowlisted update kinds without retaining private message bodies."""
        update = Update.model_validate_json(body)
        if update.chat_member is not None:
            event = update.chat_member
            joined = event.new_chat_member
            user = joined.user
            if (
                event.chat.id == self.settings.community_telegram_chat_id
                and joined.status in {"member", "administrator", "creator"}
                and not user.is_bot
                and await self.store.onboarding_started(user.id)
            ):
                await self._private_command(
                    update.update_id, user, "/onboarding", "/start", membership_verified=True
                )
            return
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
                [
                    InlineKeyboardButton(
                        text="Я вступил — проверить", callback_data="community:check"
                    )
                ]
            )
            await self._send(
                user_id,
                (
                    "Присоединяйся к нашему чату!\n\n"
                    "Бот и приложение доступны участникам сообщества. "
                    "Вступи в чат по кнопке ниже, затем вернись сюда "
                    "и нажми «Я вступил — проверить»."
                    if self.settings.community_telegram_join_url
                    else "Бот и приложение доступны только участникам чата. "
                    "Попроси ссылку на чат у администратора, вступи "
                    "и нажми «Я вступил — проверить»."
                ),
                buttons,
            )
        return joined

    async def _private_command(  # noqa: C901, PLR0911, PLR0912 - explicit state gates.
        self,
        update_id: int,
        user: User,
        command: str,
        text: str,
        *,
        membership_verified: bool = False,
    ) -> None:
        existing = await self.store.member_for_telegram(user.id)
        if existing is not None and existing.status not in {"active", "pending"}:
            await self._send(user.id, "Доступ к приложению ограничен. Обратитесь к администратору.")
            return
        if command == "/start" and existing is None:
            await self.store.begin_onboarding(user.id, user.username, user.full_name)
            chat_id = self.settings.community_telegram_chat_id
            if chat_id is None:
                await self._send(user.id, "Онбординг временно недоступен. Попробуй позже.")
                return
            try:
                joined = await self.membership.is_member(chat_id=chat_id, telegram_user_id=user.id)
            except MembershipCheckUnavailableError:
                await self._send(user.id, "Не удалось проверить участие. Попробуй позже.")
                return
            buttons = (
                [
                    [
                        InlineKeyboardButton(
                            text="Продолжить настройку", callback_data="onboarding:continue"
                        )
                    ]
                ]
                if joined
                else [
                    *(
                        [
                            [
                                InlineKeyboardButton(
                                    text="Вступить в сообщество →",
                                    url=self.settings.community_telegram_join_url,
                                )
                            ]
                        ]
                        if self.settings.community_telegram_join_url
                        else []
                    ),
                    [
                        InlineKeyboardButton(
                            text="Я уже вступил — проверить", callback_data="community:check"
                        )
                    ],
                ]
            )
            await self._send(user.id, ONBOARDING_INTRO, buttons)
            return
        if command == "/start" and existing is not None and existing.status == "active":
            await self._send(
                user.id,
                "С возвращением! Всё готово — выбирай действие ниже.",
                reply_keyboard=home_keyboard(),
            )
            await self._send(user.id, "Открыть Human Quest", self._launch_buttons())
            return
        if not membership_verified and not await self._member_gate(user.id):
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
                "🎉 Ты в сообществе!\n\n"
                "Профиль уже создан, доступ к приложению открыт, "
                "а на баланс начислено 20 стартовых кредитов.\n\n"
                "Остался последний шаг — выбери, какие уведомления получать.",
                reply_keyboard=home_keyboard(),
            )
            await self._show_preferences(user.id, view.context.member_id)
            await self.store.complete_onboarding(user.id)
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

    async def _callback(  # noqa: C901, PLR0911 - explicit linear navigation gates.
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
        if callback.data in {"community:check", "onboarding:continue"}:
            if await self._member_gate(callback.from_user.id):
                await self._private_command(
                    update_id,
                    callback.from_user,
                    "/onboarding",
                    "/start",
                    membership_verified=True,
                )
            return
        if not (callback.data or "").startswith(
            ("activities:", "subscription:", "notifications:", "nomad:", "help:", "onboarding:")
        ):
            return
        if not await self._member_gate(callback.from_user.id):
            return
        member = await self.store.member_for_telegram(callback.from_user.id)
        if member is None or member.status != "active":
            return
        if callback.data == "onboarding:done":
            await self._edit_or_send(
                callback.from_user.id,
                ONBOARDING_DONE,
                [
                    [InlineKeyboardButton(text=APP_BUTTON, callback_data="help:why_app")],
                    [navigation("Изменить подписки", "all")],
                ],
                callback.message.message_id,
            )
            return
        parts = (callback.data or "").split(":")
        if parts[0] == "help":
            if callback.data in {"help:app", "help:why_app"}:
                await self._edit_or_send(
                    callback.from_user.id,
                    WHY_APP_HELP,
                    [
                        *self._launch_buttons(),
                        [navigation("Назад к подпискам", "all")],
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
            category = "tasks" if parts[1] in TASK_CATEGORIES else parts[1]
            page = "all"
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
        if page == "all":
            buttons.extend(
                [
                    [InlineKeyboardButton(text="Готово", callback_data="onboarding:done")],
                    [InlineKeyboardButton(text=APP_BUTTON, callback_data="help:why_app")],
                ]
            )
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
