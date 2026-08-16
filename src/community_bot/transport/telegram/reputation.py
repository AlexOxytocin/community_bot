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
from community_bot.application.reputation import (
    MEMBER_SEARCH_MIN_LENGTH,
    ReputationError,
    normalize_member_search_query,
)
from community_bot.domain.reputation import ProfileUnavailableError

_MEMBER_CATALOG_PAGE_SIZE = 10
_MEMBER_CATALOG_OPEN_PREFIX = "mc:o:"
_MEMBER_CATALOG_CLOSE_PREFIX = "mc:x:"
_MEMBER_CATALOG_PAGE_PREFIX = "mc:p:"
_MEMBER_CATALOG_SEARCH_CALLBACK = "mc:s"
_MEMBER_CATALOG_RESET_CALLBACK = "mc:r"
_MEMBER_CATALOG_SEARCH_LINE_PREFIX = "Поиск: "

if TYPE_CHECKING:
    from decimal import Decimal

    from community_bot.application.conversations import TextFlow
    from community_bot.application.member_foundation import MemberFoundationService
    from community_bot.application.moderation import ModerationService
    from community_bot.application.reputation import (
        KarmaDraft,
        LeaderboardPage,
        MemberCatalogPage,
        PersonalStatistics,
        ReputationService,
        SafeProfile,
    )


def build_reputation_router(  # noqa: C901, PLR0915 - handlers share one injected service.
    service: ReputationService,
    moderation: ModerationService | None = None,
    foundation: MemberFoundationService | None = None,
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
        await send_member_catalog(
            message,
            service,
            moderation,
            foundation,
            query=_optional_text_argument(message.text),
        )

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

    async def member_catalog_open(callback: CallbackQuery) -> None:
        await _redraw_member_catalog_callback(
            callback,
            service,
            moderation,
            foundation,
            expand=True,
        )

    async def member_catalog_close(callback: CallbackQuery) -> None:
        await _redraw_member_catalog_callback(
            callback,
            service,
            moderation,
            foundation,
            expand=False,
        )

    async def member_catalog_page(callback: CallbackQuery) -> None:
        if not isinstance(callback.message, Message):
            await callback.answer("Каталог устарел.", show_alert=True)
            return
        try:
            cursor_member_id = _catalog_cursor_id(
                str(callback.data).removeprefix(_MEMBER_CATALOG_PAGE_PREFIX)
            )
            query = _catalog_query_from_text(callback.message.text)
            page = await service.members(
                telegram_user_id=callback.from_user.id,
                limit=_MEMBER_CATALOG_PAGE_SIZE,
                cursor_member_id=cursor_member_id,
                query=query,
            )
            admin_actions, superadmin_actions = await _catalog_action_flags(
                callback.from_user.id,
                moderation,
                foundation,
            )
            await callback.message.edit_text(
                present_member_catalog(page, query=query),
                parse_mode=None,
                reply_markup=_member_catalog_keyboard(
                    page,
                    page_cursor_member_id=cursor_member_id,
                    query=query,
                    expanded_member_id=None,
                    admin_actions=admin_actions,
                    superadmin_actions=superadmin_actions,
                ),
            )
            await callback.answer()
        except (ValueError, ProfileUnavailableError):
            await callback.answer("Каталог недоступен.", show_alert=True)

    async def member_catalog_search(callback: CallbackQuery) -> None:
        await callback.answer(
            "Для поиска напишите /members <ник или имя>. "
            f"Минимум {MEMBER_SEARCH_MIN_LENGTH} символа.",
            show_alert=True,
        )

    async def member_catalog_reset(callback: CallbackQuery) -> None:
        if not isinstance(callback.message, Message):
            await callback.answer("Каталог устарел.", show_alert=True)
            return
        try:
            page = await service.members(
                telegram_user_id=callback.from_user.id,
                limit=_MEMBER_CATALOG_PAGE_SIZE,
            )
            admin_actions, superadmin_actions = await _catalog_action_flags(
                callback.from_user.id,
                moderation,
                foundation,
            )
            await callback.message.edit_text(
                present_member_catalog(page),
                parse_mode=None,
                reply_markup=_member_catalog_keyboard(
                    page,
                    page_cursor_member_id=None,
                    query=None,
                    expanded_member_id=None,
                    admin_actions=admin_actions,
                    superadmin_actions=superadmin_actions,
                ),
            )
            await callback.answer()
        except ProfileUnavailableError:
            await callback.answer("Каталог недоступен.", show_alert=True)

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
    router.callback_query.register(
        member_catalog_open, F.data.startswith(_MEMBER_CATALOG_OPEN_PREFIX)
    )
    router.callback_query.register(
        member_catalog_close, F.data.startswith(_MEMBER_CATALOG_CLOSE_PREFIX)
    )
    router.callback_query.register(
        member_catalog_page, F.data.startswith(_MEMBER_CATALOG_PAGE_PREFIX)
    )
    router.callback_query.register(member_catalog_search, F.data == _MEMBER_CATALOG_SEARCH_CALLBACK)
    router.callback_query.register(member_catalog_reset, F.data == _MEMBER_CATALOG_RESET_CALLBACK)
    return router


async def send_member_catalog(  # noqa: PLR0913 - reusable command/menu render boundary.
    message: Message,
    service: ReputationService,
    moderation: ModerationService | None = None,
    foundation: MemberFoundationService | None = None,
    *,
    query: str | None = None,
    cursor_member_id: UUID | None = None,
    expanded_member_id: UUID | None = None,
) -> None:
    """Render one compact member catalog page for the current actor."""
    if message.from_user is None:
        return
    try:
        page = await service.members(
            telegram_user_id=message.from_user.id,
            limit=_MEMBER_CATALOG_PAGE_SIZE,
            cursor_member_id=cursor_member_id,
            query=query,
        )
        admin_actions, superadmin_actions = await _catalog_action_flags(
            message.from_user.id,
            moderation,
            foundation,
        )
        await message.answer(
            present_member_catalog(page, query=query, expanded_member_id=expanded_member_id),
            reply_markup=_member_catalog_keyboard(
                page,
                page_cursor_member_id=cursor_member_id,
                query=query,
                expanded_member_id=expanded_member_id,
                admin_actions=admin_actions,
                superadmin_actions=superadmin_actions,
            ),
        )
    except ValueError:
        await message.answer(
            f"Для поиска нужно минимум {MEMBER_SEARCH_MIN_LENGTH} символа после @ и пробелов."
        )
    except ProfileUnavailableError:
        await message.answer("Профиль недоступен.")


async def _redraw_member_catalog_callback(
    callback: CallbackQuery,
    service: ReputationService,
    moderation: ModerationService | None,
    foundation: MemberFoundationService | None,
    *,
    expand: bool,
) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer("Каталог устарел.", show_alert=True)
        return
    try:
        prefix = _MEMBER_CATALOG_OPEN_PREFIX if expand else _MEMBER_CATALOG_CLOSE_PREFIX
        cursor_member_id, row_index = _catalog_toggle_payload(
            str(callback.data).removeprefix(prefix)
        )
        query = _catalog_query_from_text(callback.message.text)
        page = await service.members(
            telegram_user_id=callback.from_user.id,
            limit=_MEMBER_CATALOG_PAGE_SIZE,
            cursor_member_id=cursor_member_id,
            query=query,
        )
        expanded_member_id = _expanded_catalog_member_id(page, row_index) if expand else None
        admin_actions, superadmin_actions = await _catalog_action_flags(
            callback.from_user.id,
            moderation,
            foundation,
        )
        await callback.message.edit_text(
            present_member_catalog(page, query=query, expanded_member_id=expanded_member_id),
            parse_mode=None,
            reply_markup=_member_catalog_keyboard(
                page,
                page_cursor_member_id=cursor_member_id,
                query=query,
                expanded_member_id=expanded_member_id,
                admin_actions=admin_actions,
                superadmin_actions=superadmin_actions,
            ),
        )
        await callback.answer()
    except (ValueError, ProfileUnavailableError):
        await callback.answer("Каталог недоступен.", show_alert=True)


async def _catalog_action_flags(
    telegram_user_id: int,
    moderation: ModerationService | None,
    foundation: MemberFoundationService | None,
) -> tuple[bool, bool]:
    admin_actions = bool(
        moderation is not None and await moderation.is_administrator(telegram_user_id)
    )
    superadmin_actions = bool(
        foundation is not None and await foundation.is_active_superadministrator(telegram_user_id)
    )
    return admin_actions, superadmin_actions


def present_member_catalog(
    page: MemberCatalogPage,
    *,
    query: str | None = None,
    expanded_member_id: UUID | None = None,
) -> str:
    """Render one compact active-member catalog page."""
    normalized_query = normalize_member_search_query(query)
    lines = ["Участники"]
    if normalized_query is not None:
        lines.append(f"{_MEMBER_CATALOG_SEARCH_LINE_PREFIX}{normalized_query}")
    if not page.items:
        lines.append("")
        empty_message = (
            "По этому поиску участники не найдены." if normalized_query else "Каталог пока пуст."
        )
        lines.append(empty_message)
        return "\n".join(lines)
    lines.append("")
    for index, item in enumerate(page.items, start=1):
        expanded = item.member_id == expanded_member_id
        marker = "-" if expanded else "+"
        lines.append(f"{index:02d} {marker} {_member_catalog_row(item)}")
        if expanded:
            lines.extend(f"   {detail}" for detail in _member_catalog_details(item))
    return "\n".join(lines)


def _member_catalog_keyboard(  # noqa: PLR0913 - Telegram markup is explicit by state axes.
    page: MemberCatalogPage,
    *,
    page_cursor_member_id: UUID | None,
    query: str | None,
    expanded_member_id: UUID | None,
    admin_actions: bool,
    superadmin_actions: bool,
) -> InlineKeyboardMarkup:
    inline_keyboard: list[list[InlineKeyboardButton]] = []
    cursor_token = page_cursor_member_id.hex if page_cursor_member_id is not None else "0"
    row_buttons: list[InlineKeyboardButton] = []
    expanded_profile = None
    for index, item in enumerate(page.items):
        expanded = item.member_id == expanded_member_id
        if expanded:
            expanded_profile = item
        prefix = _MEMBER_CATALOG_CLOSE_PREFIX if expanded else _MEMBER_CATALOG_OPEN_PREFIX
        label = f"{'-' if expanded else '+'} {index + 1:02d}"
        row_buttons.append(
            InlineKeyboardButton(text=label, callback_data=f"{prefix}{cursor_token}:{index}")
        )
        if len(row_buttons) == 5:  # noqa: PLR2004 - compact Telegram grid width.
            inline_keyboard.append(row_buttons)
            row_buttons = []
    if row_buttons:
        inline_keyboard.append(row_buttons)
    if expanded_profile is not None:
        inline_keyboard.extend(
            _member_catalog_action_rows(
                expanded_profile,
                admin_actions=admin_actions,
                superadmin_actions=superadmin_actions,
            )
        )
    navigation_buttons: list[InlineKeyboardButton] = []
    if page_cursor_member_id is not None:
        navigation_buttons.append(
            InlineKeyboardButton(text="В начало", callback_data=f"{_MEMBER_CATALOG_PAGE_PREFIX}0")
        )
    if page.next_cursor is not None:
        navigation_buttons.append(
            InlineKeyboardButton(
                text="Ещё",
                callback_data=f"{_MEMBER_CATALOG_PAGE_PREFIX}{page.next_cursor.member_id.hex}",
            )
        )
    if navigation_buttons:
        inline_keyboard.append(navigation_buttons)
    utility_buttons = [
        InlineKeyboardButton(text="Поиск", callback_data=_MEMBER_CATALOG_SEARCH_CALLBACK)
    ]
    if query is not None:
        utility_buttons.append(
            InlineKeyboardButton(text="Сброс", callback_data=_MEMBER_CATALOG_RESET_CALLBACK)
        )
    inline_keyboard.append(utility_buttons)
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def _member_catalog_action_rows(
    profile: SafeProfile, *, admin_actions: bool, superadmin_actions: bool
) -> list[list[InlineKeyboardButton]]:
    rows = [
        [
            InlineKeyboardButton(
                text="Профиль", callback_data=f"member:profile:{profile.member_id.hex}"
            ),
            InlineKeyboardButton(
                text="Оценить", callback_data=f"karma:begin:{profile.member_id.hex}"
            ),
        ]
    ]
    if admin_actions:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        text="Карма", callback_data=f"karma:raw:{profile.member_id.hex}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Предупредить", callback_data=f"mod:warn:{profile.member_id.hex}"
                    ),
                    InlineKeyboardButton(
                        text="Ограничить", callback_data=f"mod:restrict:{profile.member_id.hex}"
                    ),
                ],
            ]
        )
    if superadmin_actions:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        text="Назначить админом",
                        callback_data=f"member:role:administrator:{profile.member_id.hex}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Снять админа",
                        callback_data=f"member:role:member:{profile.member_id.hex}",
                    )
                ],
            ]
        )
    return rows


def _member_catalog_row(profile: SafeProfile) -> str:
    identity = _member_catalog_identity(profile)
    karma = _signed(profile.karma.score)
    return f"{identity} · ур.{profile.level_number} · карма {karma} ({profile.karma.count})"


def _member_catalog_details(profile: SafeProfile) -> tuple[str, ...]:
    return (
        f"Город: {_clip(profile.city or 'не указан', 80)}",
        f"О себе: {_clip(profile.short_bio or 'не указано', 80)}",
        f"Цель: {_clip(profile.current_goal or 'не указана', 80)}",
        f"Помощь: {_clip(_joined(profile.help_categories) or 'не указана', 80)}",
        f"Навыки: {_clip(_joined(profile.skill_tags) or 'не указаны', 80)}",
        f"Доступность: {_clip(profile.availability or 'не указана', 80)}",
        f"Опыт: {profile.experience_total}",
        f"Надёжность: {_rate(profile.reliability.rate)}",
    )


def _member_catalog_identity(profile: SafeProfile) -> str:
    username = _public_username(profile.telegram_username)
    if username is None:
        return _clip(profile.display_name, 48)
    return _clip(f"{username} · {profile.display_name}", 64)


def _public_username(value: str | None) -> str | None:
    normalized = (value or "").strip().lstrip("@")
    return f"@{normalized}" if normalized else None


def _joined(values: tuple[str, ...]) -> str:
    return ", ".join(values)


def _signed(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}…"


def _catalog_toggle_payload(value: str) -> tuple[UUID | None, int]:
    raw_cursor, raw_index = value.split(":", 1)
    row_index = int(raw_index)
    if row_index < 0:
        raise ValueError
    return _catalog_cursor_id(raw_cursor), row_index


def _expanded_catalog_member_id(page: MemberCatalogPage, row_index: int) -> UUID:
    if row_index >= len(page.items):
        raise ValueError
    return page.items[row_index].member_id


def _catalog_cursor_id(value: str) -> UUID | None:
    return None if value == "0" else UUID(hex=value)


def _catalog_query_from_text(text: str | None) -> str | None:
    for line in (text or "").splitlines():
        if line.startswith(_MEMBER_CATALOG_SEARCH_LINE_PREFIX):
            return line.removeprefix(_MEMBER_CATALOG_SEARCH_LINE_PREFIX).strip() or None
    return None


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


def _optional_text_argument(text: str | None) -> str | None:
    parts = (text or "").split(maxsplit=1)
    if len(parts) != 2:  # noqa: PLR2004
        return None
    value = parts[1].strip()
    return value or None


def _revision_and_text(text: str | None) -> tuple[int, str]:
    parts = (text or "").split(maxsplit=2)
    if len(parts) != 3:  # noqa: PLR2004
        message = "Revision and comment are required."
        raise ValueError(message)
    return int(parts[1]), parts[2]


def _rate(value: Decimal | None) -> str:
    return "недостаточно данных" if value is None else f"{value:.0%}"
