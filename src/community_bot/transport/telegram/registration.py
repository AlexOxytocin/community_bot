"""Telegram routes for invitations, registration moderation, and own profiles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)

from community_bot.application.registration import (
    InvitationCreateCommand,
    ModerationCommand,
    RegistrationAnswerCommand,
    RegistrationStartCommand,
    RegistrationView,
)
from community_bot.domain.registration import (
    ModerationDecision,
    ProfileField,
    RegistrationError,
    RegistrationStep,
    TimezoneResolutionError,
)
from community_bot.transport.telegram.navigation import main_menu_markup
from community_bot.transport.telegram.profile import own_profile_card, profile_edit_keyboard

if TYPE_CHECKING:
    from community_bot.application.registration import RegistrationService

_STEP_PROMPTS: dict[RegistrationStep, str] = {
    RegistrationStep.CONSENT: "Подтвердите согласие с правилами и обработкой данных.",
    RegistrationStep.DISPLAY_NAME: "Как вас называть в сообществе?",
    RegistrationStep.CITY: "В каком городе вы живёте?",
    RegistrationStep.TIMEZONE: (
        "Не удалось однозначно определить часовой пояс по городу. "
        "Напишите ближайший крупный город, например Москва или Buenos Aires."
    ),
    RegistrationStep.SHORT_BIO: "Коротко расскажите о себе — от 10 до 500 символов.",
    RegistrationStep.CURRENT_GOAL: "Какая у вас сейчас основная цель?",
    RegistrationStep.HELP_CATEGORIES: "В чём вы можете помогать? Перечислите через запятую.",
    RegistrationStep.SKILL_TAGS: "Перечислите навыки через запятую.",
    RegistrationStep.AVAILABILITY: "Когда и в каком объёме вы обычно доступны?",
}
_MAX_INVITE_LIFETIME_DAYS = 365
_INTENDED_ID_ARGUMENT_INDEX = 2


def build_registration_router(
    service: RegistrationService,
    *,
    include_text_fallback: bool = True,
) -> Router:
    """Build the complete invitation, onboarding, moderation, and profile router."""
    router = Router(name="registration")

    async def handle_start(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        token = _command_tail(message.text)
        try:
            view = await service.start(
                RegistrationStartCommand(
                    update_id=event_update.update_id,
                    telegram_user_id=message.from_user.id,
                    telegram_username=message.from_user.username,
                    telegram_display_name=message.from_user.full_name,
                    invitation_token=token,
                )
            )
            await _send_registration_view(message, view)
        except (RegistrationError, PermissionError, LookupError) as error:
            await message.answer(_friendly_error(error), reply_markup=ReplyKeyboardRemove())

    async def handle_invite_create(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            max_uses, lifetime_days, intended_id = _parse_invite_create(message.text)
            result = await service.create_invitation(
                InvitationCreateCommand(
                    update_id=event_update.update_id,
                    actor_telegram_user_id=message.from_user.id,
                    max_uses=max_uses,
                    expires_at=datetime.now(UTC) + timedelta(days=lifetime_days),
                    intended_telegram_user_id=intended_id,
                )
            )
            await message.answer(
                "Приглашение создано. Передайте человеку эту команду:\n"
                f"`/start {result.token}`\n\n"
                f"ID приглашения для отзыва: `{result.invitation_id}`",
                parse_mode="Markdown",
            )
        except (RegistrationError, PermissionError, LookupError, ValueError) as error:
            await message.answer(_friendly_error(error))

    async def handle_invite_revoke(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            invitation_id = UUID(_required_command_tail(message.text))
            await service.revoke_invitation(
                update_id=event_update.update_id,
                actor_telegram_user_id=message.from_user.id,
                invitation_id=invitation_id,
            )
            await message.answer("Приглашение отозвано.")
        except (RegistrationError, PermissionError, LookupError, ValueError) as error:
            await message.answer(_friendly_error(error))

    async def handle_registrations(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            applications = await service.submitted_registrations(
                actor_telegram_user_id=message.from_user.id
            )
            if not applications:
                await message.answer("Новых заявок нет.")
                return
            for application in applications:
                await message.answer(
                    _moderation_card(application.payload, application.member_id),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="Одобрить",
                                    callback_data=f"registration:approve:{application.member_id}",
                                ),
                                InlineKeyboardButton(
                                    text="Отклонить",
                                    callback_data=f"registration:reject_help:{application.member_id}",
                                ),
                            ]
                        ]
                    ),
                )
        except (RegistrationError, PermissionError, LookupError) as error:
            await message.answer(_friendly_error(error))

    async def handle_registration_reject(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            member_id, reason = _parse_rejection(message.text)
            await service.moderate(
                ModerationCommand(
                    update_id=event_update.update_id,
                    actor_telegram_user_id=message.from_user.id,
                    target_member_id=member_id,
                    decision=ModerationDecision.REJECT,
                    comment=reason,
                )
            )
            await message.answer("Заявка отклонена. Участник сможет исправить анкету.")
        except (RegistrationError, PermissionError, LookupError, ValueError) as error:
            await message.answer(_friendly_error(error))

    async def handle_profile(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            profile = await service.own_profile(message.from_user.id)
            await message.answer(
                own_profile_card(profile),
                reply_markup=profile_edit_keyboard(),
            )
        except (RegistrationError, PermissionError, LookupError) as error:
            await message.answer(_friendly_error(error))

    async def handle_cancel(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        await service.cancel(
            update_id=event_update.update_id,
            telegram_user_id=message.from_user.id,
        )
        await message.answer(
            "Диалог остановлен. Сохранённая анкета продолжится после следующего /start.",
            reply_markup=ReplyKeyboardRemove(),
        )

    async def handle_consent(callback: CallbackQuery, event_update: Update) -> None:
        try:
            view = await service.answer(
                RegistrationAnswerCommand(
                    update_id=event_update.update_id,
                    telegram_user_id=callback.from_user.id,
                    expected_step=RegistrationStep.CONSENT,
                    raw_value="yes",
                )
            )
            await _answer_callback_with_view(callback, view)
        except (RegistrationError, PermissionError, LookupError) as error:
            await callback.answer(_friendly_error(error), show_alert=True)

    async def handle_submit(callback: CallbackQuery, event_update: Update) -> None:
        try:
            view = await service.submit(
                update_id=event_update.update_id,
                telegram_user_id=callback.from_user.id,
            )
            await _answer_callback_with_view(callback, view)
        except (RegistrationError, PermissionError, LookupError) as error:
            await callback.answer(_friendly_error(error), show_alert=True)

    async def handle_reopen(callback: CallbackQuery, event_update: Update) -> None:
        try:
            view = await service.reopen_rejected(
                update_id=event_update.update_id,
                telegram_user_id=callback.from_user.id,
            )
            await _answer_callback_with_view(callback, view)
        except (RegistrationError, PermissionError, LookupError) as error:
            await callback.answer(_friendly_error(error), show_alert=True)

    async def handle_approve(callback: CallbackQuery, event_update: Update) -> None:
        try:
            target_id = UUID(str(callback.data).rsplit(":", 1)[1])
            await service.moderate(
                ModerationCommand(
                    update_id=event_update.update_id,
                    actor_telegram_user_id=callback.from_user.id,
                    target_member_id=target_id,
                    decision=ModerationDecision.APPROVE,
                )
            )
            await callback.answer("Заявка одобрена.", show_alert=True)
            if isinstance(callback.message, Message):
                await callback.message.edit_reply_markup(reply_markup=None)
        except (RegistrationError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_friendly_error(error), show_alert=True)

    async def handle_reject_help(callback: CallbackQuery) -> None:
        target_id = str(callback.data).rsplit(":", 1)[1]
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.answer(
                "Чтобы отклонить заявку с объяснением, отправьте:\n"
                f"`/registration_reject {target_id} причина`",
                parse_mode="Markdown",
            )

    async def handle_profile_edit(callback: CallbackQuery, event_update: Update) -> None:
        try:
            field = ProfileField(str(callback.data).rsplit(":", 1)[1])
            await service.begin_profile_field_edit(
                update_id=event_update.update_id,
                telegram_user_id=callback.from_user.id,
                field=field,
            )
            await callback.answer()
            if isinstance(callback.message, Message):
                await callback.message.answer(_profile_edit_prompt(field))
        except (RegistrationError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_friendly_error(error), show_alert=True)

    async def handle_expected_text(message: Message, event_update: Update) -> None:
        if not await handle_registration_text(service, message, event_update):
            raise SkipHandler

    router.message.register(handle_start, CommandStart())
    router.message.register(handle_invite_create, Command("invite_create"))
    router.message.register(handle_invite_revoke, Command("invite_revoke"))
    router.message.register(handle_registrations, Command("registrations"))
    router.message.register(handle_registration_reject, Command("registration_reject"))
    router.message.register(
        handle_profile,
        Command("profile"),
        F.text.regexp(r"^/profile(?:@\w+)?\s*$"),
    )
    router.message.register(handle_cancel, Command("cancel"))
    router.callback_query.register(handle_consent, F.data == "registration:consent")
    router.callback_query.register(handle_submit, F.data == "registration:submit")
    router.callback_query.register(handle_reopen, F.data == "registration:reopen")
    router.callback_query.register(handle_approve, F.data.startswith("registration:approve:"))
    router.callback_query.register(
        handle_reject_help,
        F.data.startswith("registration:reject_help:"),
    )
    router.callback_query.register(handle_profile_edit, F.data.startswith("profile:edit:"))
    if include_text_fallback:
        router.message.register(handle_expected_text, F.text & ~F.text.startswith("/"))
    return router


async def handle_registration_text(
    service: RegistrationService,
    message: Message,
    event_update: Update,
) -> bool:
    """Handle the active registration/profile flow, or return false when none owns the text."""
    if message.from_user is None or message.text is None:
        return False
    expectation = await service.expected_input(message.from_user.id)
    if expectation is None:
        return False
    flow_type, raw_step = expectation
    try:
        if flow_type == "registration":
            step = RegistrationStep(raw_step)
            if step in {RegistrationStep.PREVIEW, RegistrationStep.SUBMITTED}:
                return True
            view = await service.answer(
                RegistrationAnswerCommand(
                    update_id=event_update.update_id,
                    telegram_user_id=message.from_user.id,
                    expected_step=step,
                    raw_value=message.text,
                )
            )
            await _send_registration_view(message, view)
            return True
        if flow_type == "profile_edit":
            field = ProfileField(raw_step)
            await service.save_profile_field(
                update_id=event_update.update_id,
                telegram_user_id=message.from_user.id,
                expected_field=field,
                raw_value=message.text,
            )
            await message.answer("Карточка обновлена.")
    except (RegistrationError, PermissionError, LookupError, ValueError) as error:
        await message.answer(_friendly_error(error))
    return True


async def _send_registration_view(message: Message, view: RegistrationView) -> None:
    text, markup = _registration_presentation(view)
    await message.answer(text, reply_markup=markup)


async def _answer_callback_with_view(
    callback: CallbackQuery,
    view: RegistrationView,
) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _send_registration_view(callback.message, view)


def _registration_presentation(
    view: RegistrationView,
) -> tuple[str, InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None]:
    context = view.context
    if view.outcome_code == "invitation_required":
        return "Для регистрации откройте ссылку-приглашение от администратора.", None
    if view.outcome_code == "main_menu":
        return "Регистрация подтверждена. Главное меню уже доступно.", main_menu_markup()
    if view.outcome_code == "registration_pending":
        return "Анкета отправлена и ожидает подтверждения.", None
    if view.outcome_code == "registration_rejected":
        reason = (
            ""
            if context is None or not context.review_comment
            else f"\nПричина: {context.review_comment}"
        )
        return (
            f"Анкету нужно исправить.{reason}",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Исправить анкету", callback_data="registration:reopen"
                        )
                    ]
                ]
            ),
        )
    if context is None:
        return "Не удалось восстановить регистрацию.", None
    if context.current_step is RegistrationStep.CONSENT:
        return (
            _STEP_PROMPTS[RegistrationStep.CONSENT],
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Согласен", callback_data="registration:consent")]
                ]
            ),
        )
    if context.current_step is RegistrationStep.PREVIEW:
        return (
            _draft_preview(context.payload),
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Отправить на проверку", callback_data="registration:submit"
                        )
                    ]
                ]
            ),
        )
    prompt = _STEP_PROMPTS.get(context.current_step, "Анкета сохранена.")
    return prompt, ReplyKeyboardRemove()


def _draft_preview(payload: dict[str, object]) -> str:
    return (
        "Проверьте анкету:\n\n"
        f"Имя: {payload.get('display_name', '—')}\n"
        f"Город: {payload.get('city', '—')}\n"
        f"Часовой пояс: {payload.get('timezone', '—')}\n"
        f"О себе: {payload.get('short_bio', '—')}\n"
        f"Цель: {payload.get('current_goal', '—')}\n"
        f"Помощь: {_joined(payload.get('help_categories'))}\n"
        f"Навыки: {_joined(payload.get('skill_tags'))}\n"
        f"Доступность: {payload.get('availability', '—')}"
    )


def _profile_edit_prompt(field: ProfileField) -> str:
    step = RegistrationStep(field.value)
    return _STEP_PROMPTS[step]


def _moderation_card(payload: dict[str, object], member_id: UUID) -> str:
    return f"Заявка {member_id}\n\n{_draft_preview(payload)}"


def _parse_invite_create(text: str | None) -> tuple[int, int, int | None]:
    parts = _command_tail(text).split() if _command_tail(text) else []
    max_uses = int(parts[0]) if parts else 1
    lifetime_days = int(parts[1]) if len(parts) > 1 else 7
    intended_id = (
        int(parts[_INTENDED_ID_ARGUMENT_INDEX])
        if len(parts) > _INTENDED_ID_ARGUMENT_INDEX
        else None
    )
    if lifetime_days < 1 or lifetime_days > _MAX_INVITE_LIFETIME_DAYS:
        message = "Invite lifetime must be between 1 and 365 days."
        raise ValueError(message)
    return max_uses, lifetime_days, intended_id


def _parse_rejection(text: str | None) -> tuple[UUID, str]:
    tail = _required_command_tail(text)
    raw_id, separator, reason = tail.partition(" ")
    if not separator or not reason.strip():
        message = "Use /registration_reject <member_id> <reason>."
        raise ValueError(message)
    return UUID(raw_id), reason.strip()


def _required_command_tail(text: str | None) -> str:
    tail = _command_tail(text)
    if not tail:
        message = "Command arguments are required."
        raise ValueError(message)
    return tail


def _command_tail(text: str | None) -> str:
    if not text:
        return ""
    _, separator, tail = text.partition(" ")
    return tail.strip() if separator else ""


def _joined(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return "—" if value is None else str(value)


def _friendly_error(error: Exception) -> str:
    if isinstance(error, TimezoneResolutionError):
        return (
            "Не удалось определить часовой пояс. Напишите ближайший крупный город, "
            "например Москва или Buenos Aires."
        )
    if isinstance(error, PermissionError):
        return "Это действие вам недоступно."
    if isinstance(error, LookupError):
        return "Запись не найдена или уже недоступна."
    return "Не удалось сохранить данные. Проверьте формат и попробуйте ещё раз."
