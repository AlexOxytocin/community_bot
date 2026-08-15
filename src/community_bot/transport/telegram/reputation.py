"""Telegram routes for safe profiles, statistics, leaderboard, and karma."""

# ruff: noqa: RUF001 - Russian user-facing text is intentional.

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update

from community_bot.application.moderation import ModerateKarmaCommand
from community_bot.application.reputation import ReputationError
from community_bot.domain.reputation import ProfileUnavailableError

if TYPE_CHECKING:
    from decimal import Decimal

    from community_bot.application.conversations import TextFlow
    from community_bot.application.member_foundation import MemberFoundationService
    from community_bot.application.moderation import ModerationService
    from community_bot.application.reputation import (
        KarmaDraft,
        LeaderboardPage,
        PersonalStatistics,
        ReputationService,
        SafeProfile,
    )


def build_reputation_router(  # noqa: C901, PLR0915 - handlers share one injected service.
    service: ReputationService,
    moderation: ModerationService | None = None,
) -> Router:
    """Build the complete reputation and profile transport boundary."""
    router = Router(name="reputation")

    async def profile(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            target_id = _optional_uuid_argument(message.text)
            view = await service.profile(telegram_user_id=message.from_user.id, target_id=target_id)
            await message.answer(present_profile(view))
        except (ValueError, ProfileUnavailableError):
            await message.answer("Профиль недоступен.")

    async def statistics(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            view = await service.statistics(message.from_user.id)
            await message.answer(present_statistics(view))
        except ProfileUnavailableError:
            await message.answer("Профиль недоступен.")

    async def members(message: Message) -> None:
        await send_member_catalog(message, service, moderation)

    async def leaderboard(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            page = await service.leaderboard(telegram_user_id=message.from_user.id)
            await message.answer(present_leaderboard(page))
        except ProfileUnavailableError:
            await message.answer("Профиль недоступен.")

    async def karma_begin(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            target_id = _required_uuid_argument(message.text)
            draft = await service.begin_vote(
                update_id=event_update.update_id,
                telegram_user_id=message.from_user.id,
                target_id=target_id,
            )
            await message.answer("Выберите оценку.", reply_markup=_karma_value_keyboard(draft))
        except (ValueError, PermissionError):
            await message.answer("Оценка недоступна.")

    async def profile_callback(callback: CallbackQuery) -> None:
        try:
            target_id = UUID(hex=str(callback.data).rsplit(":", 1)[1])
            view = await service.profile(
                telegram_user_id=callback.from_user.id,
                target_id=target_id,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.answer(present_profile(view))
        except (ValueError, ProfileUnavailableError):
            await callback.answer("Профиль недоступен.", show_alert=True)

    async def karma_begin_callback(callback: CallbackQuery, event_update: Update) -> None:
        try:
            target_id = UUID(hex=str(callback.data).rsplit(":", 1)[1])
            draft = await service.begin_vote(
                update_id=event_update.update_id,
                telegram_user_id=callback.from_user.id,
                target_id=target_id,
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.answer(
                    "Выберите оценку.", reply_markup=_karma_value_keyboard(draft)
                )
        except (ValueError, PermissionError, ReputationError):
            await callback.answer("Оценка недоступна.", show_alert=True)

    async def karma_value(callback: CallbackQuery, event_update: Update) -> None:
        if callback.from_user is None or callback.data is None:
            return
        try:
            _, _, revision, raw_value = callback.data.split(":", 3)
            await service.save_value(
                update_id=event_update.update_id,
                telegram_user_id=callback.from_user.id,
                expected_revision=int(revision),
                value=int(raw_value),
            )
            await callback.answer()
            if callback.message is not None:
                await callback.message.answer("Добавьте комментарий от 10 до 300 символов.")
        except (ValueError, ReputationError):
            await callback.answer("Шаг устарел.", show_alert=True)

    async def karma_comment(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            revision, comment = _revision_and_text(message.text)
            draft = await service.save_comment(
                update_id=event_update.update_id,
                telegram_user_id=message.from_user.id,
                expected_revision=revision,
                comment=comment,
            )
            await message.answer(
                "Проверьте оценку и подтвердите.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Подтвердить",
                                callback_data=f"karma:confirm:{draft.revision}",
                            )
                        ]
                    ]
                ),
            )
        except (ValueError, ReputationError):
            await message.answer("Комментарий или шаг недействителен.")

    async def karma_confirm(callback: CallbackQuery, event_update: Update) -> None:
        if callback.from_user is None or callback.data is None:
            return
        try:
            revision = int(callback.data.rsplit(":", 1)[1])
            result = await service.confirm_vote(
                update_id=event_update.update_id,
                telegram_user_id=callback.from_user.id,
                expected_revision=revision,
            )
            await callback.answer("Оценка сохранена.")
            if callback.message is not None:
                await callback.message.answer(
                    f"Карма участника: {result.aggregate_score} ({result.aggregate_count} оценок)."
                )
        except (ValueError, PermissionError, ReputationError):
            await callback.answer("Оценка недоступна.", show_alert=True)

    async def karma_cancel(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        if await service.cancel_vote(
            update_id=event_update.update_id, telegram_user_id=message.from_user.id
        ):
            await message.answer("Оценка отменена.")
            return
        raise SkipHandler

    async def raw_karma(callback: CallbackQuery, event_update: Update) -> None:
        try:
            target_id = UUID(hex=str(callback.data).rsplit(":", 1)[1])
            rows = await service.raw_karma(
                update_id=event_update.update_id,
                telegram_user_id=callback.from_user.id,
                target_id=target_id,
            )
            await callback.answer()
            if callback.message is None:
                return
            if not rows:
                await callback.message.answer("У участника пока нет оценок.")
                return
            for row in rows:
                await callback.message.answer(
                    f"Оценка: {row.value}\nКомментарий: {row.comment}\n"
                    f"Версия: {row.revision}\nИзменений: {len(row.history)}",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="Исключить",
                                    callback_data=(f"karma:mod:{row.vote_id.hex}:{row.revision}:x"),
                                ),
                                InlineKeyboardButton(
                                    text="Вернуть",
                                    callback_data=(f"karma:mod:{row.vote_id.hex}:{row.revision}:r"),
                                ),
                            ]
                        ]
                    ),
                )
        except (ValueError, PermissionError, ReputationError, ProfileUnavailableError):
            await callback.answer("Проверка кармы недоступна.", show_alert=True)

    async def moderate_karma(callback: CallbackQuery, event_update: Update) -> None:
        if moderation is None:
            await callback.answer("Модерация кармы недоступна.", show_alert=True)
            return
        try:
            _, _, raw_id, raw_revision, action = str(callback.data).split(":", 4)
            result = await moderation.moderate_karma(
                ModerateKarmaCommand(
                    update_id=event_update.update_id,
                    actor_telegram_user_id=callback.from_user.id,
                    vote_id=UUID(hex=raw_id),
                    vote_revision=int(raw_revision),
                    command_id=UUID(int=event_update.update_id % (1 << 128)),
                    exclude=action == "x",
                    reason="Решение администратора через Telegram",
                )
            )
            await callback.answer("Оценка исключена." if result else "Оценка обновлена.")
        except (ValueError, PermissionError, LookupError):
            await callback.answer("Оценка или её версия уже изменилась.", show_alert=True)

    router.message.register(
        profile,
        Command("profile"),
        F.text.regexp(r"^/profile(?:@\w+)?\s+\S+"),
    )
    router.message.register(statistics, Command("stats"))
    router.message.register(members, Command("members"))
    router.message.register(leaderboard, Command("leaderboard"))
    router.message.register(karma_begin, Command("karma"))
    router.message.register(karma_comment, Command("karma_comment"))
    router.message.register(karma_cancel, Command("cancel"))
    router.callback_query.register(karma_value, F.data.startswith("karma:value:"))
    router.callback_query.register(karma_confirm, F.data.startswith("karma:confirm:"))
    router.callback_query.register(profile_callback, F.data.startswith("member:profile:"))
    router.callback_query.register(karma_begin_callback, F.data.startswith("karma:begin:"))
    router.callback_query.register(raw_karma, F.data.startswith("karma:raw:"))
    router.callback_query.register(moderate_karma, F.data.startswith("karma:mod:"))
    return router


async def send_member_catalog(
    message: Message,
    service: ReputationService,
    moderation: ModerationService | None = None,
    foundation: MemberFoundationService | None = None,
) -> None:
    """Render member cards and the actions available to the current actor."""
    if message.from_user is None:
        return
    try:
        page = await service.members(telegram_user_id=message.from_user.id)
        admin_actions = bool(
            moderation is not None and await moderation.is_administrator(message.from_user.id)
        )
        superadmin_actions = bool(
            foundation is not None
            and await foundation.is_active_superadministrator(message.from_user.id)
        )
        if not page.items:
            await message.answer("Каталог участников пока пуст.")
            return
        for item in page.items:
            buttons = [
                InlineKeyboardButton(
                    text="Открыть профиль", callback_data=f"member:profile:{item.member_id.hex}"
                ),
                InlineKeyboardButton(
                    text="Оценить", callback_data=f"karma:begin:{item.member_id.hex}"
                ),
            ]
            if admin_actions:
                buttons.extend(
                    [
                        InlineKeyboardButton(
                            text="Проверить карму",
                            callback_data=f"karma:raw:{item.member_id.hex}",
                        ),
                        InlineKeyboardButton(
                            text="Предупредить",
                            callback_data=f"mod:warn:{item.member_id.hex}",
                        ),
                        InlineKeyboardButton(
                            text="Ограничить на 7 дней",
                            callback_data=f"mod:restrict:{item.member_id.hex}",
                        ),
                    ]
                )
            if superadmin_actions:
                buttons.extend(
                    [
                        InlineKeyboardButton(
                            text="Назначить администратором",
                            callback_data=f"member:role:administrator:{item.member_id.hex}",
                        ),
                        InlineKeyboardButton(
                            text="Снять права администратора",
                            callback_data=f"member:role:member:{item.member_id.hex}",
                        ),
                    ]
                )
            await message.answer(
                f"{item.display_name}\nУровень: {item.level_number}\n"
                f"Карма: {item.karma.score} ({item.karma.count})",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button] for button in buttons]),
            )
    except ProfileUnavailableError:
        await message.answer("Профиль недоступен.")


async def handle_karma_text(
    service: ReputationService,
    owner: TextFlow,
    message: Message,
    event_update: Update,
) -> bool:
    """Consume a comment only for the selected karma flow."""
    if owner.flow_type != "karma" or owner.step != "comment" or message.from_user is None:
        return False
    try:
        draft = await service.save_comment(
            update_id=event_update.update_id,
            telegram_user_id=message.from_user.id,
            expected_revision=owner.revision,
            comment=message.text or "",
        )
        await message.answer(
            "Проверьте оценку и подтвердите.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Подтвердить",
                            callback_data=f"karma:confirm:{draft.revision}",
                        )
                    ]
                ]
            ),
        )
    except (ValueError, ReputationError):
        await message.answer("Комментарий должен содержать от 10 до 300 символов.")
    return True


def present_profile(profile: SafeProfile) -> str:
    """Render a privacy-safe Russian profile card."""
    reliability = _rate(profile.reliability.rate)
    return (
        f"{profile.display_name}\n"
        f"Город: {profile.city or 'не указан'}\n"
        f"О себе: {profile.short_bio or 'не указано'}\n"
        f"Цель: {profile.current_goal or 'не указана'}\n"
        f"Опыт: {profile.experience_total}\n"
        f"Уровень: {profile.level_number}\n"
        f"Карма: {profile.karma.score} ({profile.karma.count} оценок)\n"
        f"Надёжность: {reliability}"
    )


def present_statistics(statistics: PersonalStatistics) -> str:
    """Render personal contribution statistics."""
    return (
        f"Выполнено: {statistics.completed}\n"
        f"Частично выполнено: {statistics.partially_completed}\n"
        f"Опыт: {statistics.experience_earned}\n"
        f"Получателей помощи: {statistics.unique_recipients}\n"
        f"Пропуски: {statistics.no_show}\n"
        f"Надёжность: {_rate(statistics.reliability.rate)}"
    )


def present_leaderboard(page: LeaderboardPage) -> str:
    """Render one main leaderboard page without credits or karma."""
    if not page.items:
        return "Лидерборд пока пуст."
    return "\n".join(
        f"{item.rank}. {item.display_name} — {item.experience} опыта" for item in page.items
    )


def _karma_value_keyboard(draft: KarmaDraft) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"karma:value:{draft.revision}:{value}",
                )
                for label, value in (("+1", 1), ("0", 0), ("-1", -1))
            ]
        ]
    )


def _required_uuid_argument(text: str | None) -> UUID:
    value = _optional_uuid_argument(text)
    if value is None:
        message = "Member identifier is required."
        raise ValueError(message)
    return value


def _optional_uuid_argument(text: str | None) -> UUID | None:
    parts = (text or "").split(maxsplit=1)
    return None if len(parts) != 2 else UUID(parts[1].strip())  # noqa: PLR2004


def _revision_and_text(text: str | None) -> tuple[int, str]:
    parts = (text or "").split(maxsplit=2)
    if len(parts) != 3:  # noqa: PLR2004
        message = "Revision and comment are required."
        raise ValueError(message)
    return int(parts[1]), parts[2]


def _rate(value: Decimal | None) -> str:
    return "недостаточно данных" if value is None else f"{value:.0%}"
