# ruff: noqa: C901, PLR0911, PLR0912, PLR0915, RUF001
"""User-facing Telegram commands and menus for the complete MVP."""

from __future__ import annotations

from asyncio import Lock
from base64 import urlsafe_b64decode, urlsafe_b64encode
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from secrets import randbits
from typing import TYPE_CHECKING
from uuid import UUID

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    Update,
)
from aiogram.utils.deep_linking import create_start_link

from community_bot.application.catalog import CatalogQuery
from community_bot.application.member_foundation import AdministrativeChange
from community_bot.application.registration import InvitationCreateCommand
from community_bot.domain.assignments import (
    ACTIVE_ASSIGNMENT_STATUSES,
    AssignmentError,
    AssignmentStatus,
)
from community_bot.domain.catalog import CatalogError
from community_bot.domain.members import AuthorizationError, ChangeKind
from community_bot.domain.tasks import TaskError, TaskStatus
from community_bot.transport.telegram.assignments import (
    send_assignment_overview,
    send_assignment_review_overview,
)
from community_bot.transport.telegram.moderation import send_moderation_overview
from community_bot.transport.telegram.profile import (
    PROFILE_TEXT,
    own_profile_card,
    profile_edit_keyboard,
)
from community_bot.transport.telegram.reputation import send_member_catalog
from community_bot.transport.telegram.task_card import published_task_card
from community_bot.transport.telegram.tasks import (
    community_publication_approval_keyboard,
    owned_task_keyboard,
    owned_task_summary,
    send_task_draft_prompt,
)

if TYPE_CHECKING:
    from community_bot.application.assignments import AssignmentService
    from community_bot.application.catalog import CatalogPage, CatalogService
    from community_bot.application.economy import EconomyQueryService, LedgerHistoryItem
    from community_bot.application.member_foundation import MemberFoundationService
    from community_bot.application.moderation import ModerationService
    from community_bot.application.navigation import NavigationService
    from community_bot.application.registration import RegistrationService
    from community_bot.application.reputation import ReputationService
    from community_bot.application.tasks import AvailableTaskPage, OwnedTaskCard, TaskService

TASKS_TEXT = "Задания"
INSIGHTS_TEXT = "Баланс и статистика"
MEMBERS_TEXT = "Участники"
HELP_TEXT = "Помощь"
ADMIN_TEXT = "Администрирование"
_TASK_PAGE_PREFIX = "nav:tasks:"
_CREATE_PREFIX = "nav:create:"
_COMMUNITY_PREFIX = "nav:community:"
_ADMIN_PREFIX = "nav:admin:"
_MENU_PREFIX = "nav:menu:"
_LIST_PAGE_PREFIX = "nav:list:"
_LIST_PAGE_SIZE = 10
_DELETE_BATCH_SIZE = 100
_MAX_RESULT_GENERATION = 0xFFFFFFFFFFFF
_CALLBACK_LIMIT = 64
_ARCHIVE_CALLBACK_TOO_LONG = "Archive pagination callback exceeds the Telegram limit."
_ARCHIVE_CALLBACK_INVALID = "Archive pagination callback is invalid."
_UNBOUND_MESSAGE = "Telegram message is not bound to a bot."

_CREATED_STATUS_GROUPS = {
    "active": (
        TaskStatus.PUBLISHED,
        TaskStatus.CLOSED_FOR_NEW_PERFORMERS,
        TaskStatus.SETTLING,
        TaskStatus.PARTIALLY_COMPLETED,
    ),
    "completed": (TaskStatus.COMPLETED, TaskStatus.PARTIALLY_COMPLETED),
    "archive": (
        TaskStatus.COMPLETED,
        TaskStatus.PARTIALLY_COMPLETED,
        TaskStatus.CANCELLED,
        TaskStatus.EXPIRED,
    ),
}
_ASSIGNMENT_STATUS_GROUPS = {
    "active": ACTIVE_ASSIGNMENT_STATUSES,
    "completed": frozenset({AssignmentStatus.APPROVED, AssignmentStatus.PARTIALLY_APPROVED}),
    "archive": frozenset(
        {
            AssignmentStatus.APPROVED,
            AssignmentStatus.PARTIALLY_APPROVED,
            AssignmentStatus.REJECTED,
            AssignmentStatus.CANCELLED,
            AssignmentStatus.NO_SHOW,
        }
    ),
}
_STATUS_LABELS = {
    "active": "Активные",
    "completed": "Последние завершённые",
    "archive": "Архив",
}


def main_menu_markup() -> ReplyKeyboardMarkup:
    """Return the canonical active-member reply keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=TASKS_TEXT), KeyboardButton(text=MEMBERS_TEXT)],
            [KeyboardButton(text=PROFILE_TEXT), KeyboardButton(text=INSIGHTS_TEXT)],
            [KeyboardButton(text=HELP_TEXT), KeyboardButton(text=ADMIN_TEXT)],
        ],
        resize_keyboard=True,
    )


def build_navigation_router(  # noqa: PLR0913
    *,
    navigation: NavigationService,
    catalog: CatalogService,
    tasks: TaskService,
    economy: EconomyQueryService,
    registration: RegistrationService,
    reputation: ReputationService,
    moderation: ModerationService,
    assignments: AssignmentService,
    foundation: MemberFoundationService | None = None,
) -> Router:
    """Build exact commands, button mappings, and navigation callbacks."""
    router = Router(name="navigation")
    task_result_message_ids: dict[int, list[int]] = {}
    task_result_views: dict[int, tuple[str, int]] = {}
    task_result_generations: dict[int, int] = {}
    consumed_pagination_callbacks: dict[int, set[str]] = {}
    task_result_locks: dict[int, Lock] = {}
    generation_seed = randbits(48)

    async def clear_task_results(message: Message) -> None:
        task_result_views.pop(message.chat.id, None)
        consumed_pagination_callbacks.pop(message.chat.id, None)
        message_ids = task_result_message_ids.pop(message.chat.id, [])
        if not message_ids:
            return
        bot = message.bot
        if bot is None:
            raise RuntimeError(_UNBOUND_MESSAGE)
        for offset in range(0, len(message_ids), _DELETE_BATCH_SIZE):
            try:
                await bot.delete_messages(
                    chat_id=message.chat.id,
                    message_ids=message_ids[offset : offset + _DELETE_BATCH_SIZE],
                )
            except TelegramAPIError:
                continue

    def current_task_results(message: Message) -> list[int]:
        return task_result_message_ids.setdefault(message.chat.id, [])

    def start_task_results(message: Message, view: str) -> list[int]:
        generation = (
            task_result_generations.get(message.chat.id, generation_seed) + 1
        ) & _MAX_RESULT_GENERATION
        task_result_generations[message.chat.id] = generation
        task_result_views[message.chat.id] = (view, generation)
        return current_task_results(message)

    def current_task_generation(message: Message) -> int:
        return task_result_generations[message.chat.id]

    def task_result_lock(message: Message) -> Lock:
        return task_result_locks.setdefault(message.chat.id, Lock())

    async def show_task_menu(message: Message) -> None:
        if not await _require_private_message(message):
            return
        async with task_result_lock(message):
            await clear_task_results(message)
            await message.answer("Задания", reply_markup=_task_menu_markup())

    async def show_tasks(message: Message) -> None:
        if message.from_user is None:
            return
        if not await _require_private_message(message):
            return
        async with task_result_lock(message):
            await clear_task_results(message)
            await send_available_tasks(
                message,
                message.from_user.id,
                sent_message_ids=start_task_results(message, "find"),
                result_generation=current_task_generation(message),
            )

    async def send_available_tasks(
        message: Message,
        actor_telegram_user_id: int,
        *,
        sent_message_ids: list[int] | None = None,
        result_generation: int | None = None,
    ) -> None:
        try:
            await _send_task_page(
                message,
                await tasks.list_available(actor_telegram_user_id=actor_telegram_user_id),
                sent_message_ids=sent_message_ids,
                result_generation=result_generation,
            )
        except (PermissionError, LookupError, TaskError):
            sent = await message.answer("Доступные задания сейчас не открываются.")
            _capture_message_id(sent_message_ids, sent)

    async def next_tasks(callback: CallbackQuery) -> None:
        message = callback.message
        if not isinstance(message, Message):
            return
        lock = task_result_lock(message)
        await lock.acquire()
        try:
            if message.chat.type != "private":
                await callback.answer("Откройте задания в личном чате с ботом.", show_alert=True)
                return
            callback_data = str(callback.data)
            cursor, generation = _parse_task_cursor(callback_data)
            if task_result_views.get(message.chat.id) != ("find", generation):
                await callback.answer("Этот список уже обновлён.", show_alert=True)
                return
            consumed = consumed_pagination_callbacks.setdefault(message.chat.id, set())
            if callback_data in consumed:
                await callback.answer("Эта страница уже открыта.", show_alert=True)
                return
            consumed.add(callback_data)
            page = await tasks.list_available(
                actor_telegram_user_id=callback.from_user.id, cursor_task_id=cursor
            )
            await callback.answer()
            await _send_task_page(
                message,
                page,
                sent_message_ids=current_task_results(message),
                result_generation=generation,
            )
        except (PermissionError, LookupError, TaskError, TelegramAPIError, ValueError):
            consumed_pagination_callbacks.get(message.chat.id, set()).discard(str(callback.data))
            await callback.answer("Не удалось открыть страницу заданий.", show_alert=True)
        finally:
            lock.release()

    async def show_create(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        if not await _require_private_message(
            message,
            error="Создание заданий доступно только в личном чате с ботом.",
        ):
            return
        async with task_result_lock(message):
            await clear_task_results(message)
            sent_message_ids = start_task_results(message, "create")
            try:
                draft = await tasks.start(
                    update_id=event_update.update_id,
                    actor_telegram_user_id=message.from_user.id,
                    template_id=None,
                )
                if draft is None:
                    sent = await message.answer("Создание задания сейчас недоступно.")
                    _capture_message_id(sent_message_ids, sent)
                    return
                await send_task_draft_prompt(
                    message,
                    draft,
                    service=tasks,
                    actor_telegram_user_id=message.from_user.id,
                )
            except (TaskError, PermissionError, LookupError, ValueError):
                sent = await message.answer("Создание задания сейчас недоступно.")
                _capture_message_id(sent_message_ids, sent)

    async def send_creation_catalog(
        message: Message,
        actor_telegram_user_id: int,
        *,
        sent_message_ids: list[int] | None = None,
    ) -> None:
        try:
            page = await catalog.browse(
                CatalogQuery(actor_telegram_user_id=actor_telegram_user_id, limit=20)
            )
            await _send_creation_catalog(
                message,
                page,
                prefix=_CREATE_PREFIX,
                sent_message_ids=sent_message_ids,
            )
        except (CatalogError, PermissionError, LookupError):
            sent = await message.answer("Каталог создания сейчас недоступен.")
            _capture_message_id(sent_message_ids, sent)

    async def choose_template(callback: CallbackQuery, event_update: Update) -> None:
        try:
            if not isinstance(callback.message, Message) or callback.message.chat.type != "private":
                await callback.answer("Создавайте задания в личном чате с ботом.", show_alert=True)
                return
            raw_data = str(callback.data)
            community = raw_data.startswith(_COMMUNITY_PREFIX)
            prefix = _COMMUNITY_PREFIX if community else _CREATE_PREFIX
            template_id = UUID(hex=raw_data.removeprefix(prefix))
            draft = await tasks.start(
                update_id=event_update.update_id,
                actor_telegram_user_id=callback.from_user.id,
                template_id=template_id,
                origin="community" if community else "member",
            )
            if draft is None:
                await callback.answer("Шаблон недоступен.", show_alert=True)
                return
            await callback.answer("Шаблон выбран.")
            if isinstance(callback.message, Message):
                if community:
                    reviewers = await tasks.community_reviewers(callback.from_user.id)
                    if not reviewers:
                        await callback.message.answer(
                            "Нужен второй активный администратор для независимой проверки."
                        )
                    else:
                        await callback.message.answer(
                            "Выберите независимого проверяющего.",
                            reply_markup=InlineKeyboardMarkup(
                                inline_keyboard=[
                                    [
                                        InlineKeyboardButton(
                                            text=item.display_name,
                                            callback_data=f"task:reviewer:{item.id.hex}",
                                        )
                                    ]
                                    for item in reviewers
                                ]
                            ),
                        )
                else:
                    await callback.message.answer(
                        "Черновик создан. Опишите задачу обычным сообщением. Для отмены — /cancel."
                    )
        except (CatalogError, PermissionError, LookupError, TaskError, ValueError):
            await callback.answer("Шаблон недоступен.", show_alert=True)

    async def show_balance(message: Message) -> None:
        if message.from_user is None:
            return
        async with task_result_lock(message):
            await clear_task_results(message)
            try:
                await message.answer(await balance_text(message.from_user.id))
            except (AuthorizationError, PermissionError, LookupError, ValueError):
                await message.answer("Баланс сейчас недоступен.")

    async def balance_text(actor_telegram_user_id: int) -> str:
        profile = await registration.own_profile(actor_telegram_user_id)
        history = await economy.history(
            telegram_user_id=actor_telegram_user_id,
            target_member_id=profile.member_id,
            limit=10,
        )
        lines = [f"Баланс: {profile.credit_balance} кредитов"]
        lines.extend(
            ["Операций пока нет."]
            if not history.items
            else [_ledger_line(item) for item in history.items]
        )
        return "\n".join(lines)

    async def show_insights(message: Message) -> None:
        if not await _require_private_message(message):
            return
        async with task_result_lock(message):
            await clear_task_results(message)
            await message.answer(INSIGHTS_TEXT, reply_markup=_insights_menu_markup())

    async def show_help(message: Message) -> None:
        async with task_result_lock(message):
            await clear_task_results(message)
            await message.answer(_HELP_TEXT, reply_markup=main_menu_markup())

    async def show_owned(message: Message) -> None:
        if message.from_user is None:
            return
        if not await _require_private_message(message):
            return
        async with task_result_lock(message):
            await clear_task_results(message)
            await send_owned_tasks(
                message,
                message.from_user.id,
                sent_message_ids=start_task_results(message, "created:all"),
            )

    async def send_owned_tasks(  # noqa: PLR0913
        message: Message,
        actor_telegram_user_id: int,
        *,
        status_group: str | None = None,
        cursor: tuple[datetime, UUID] | None = None,
        sent_message_ids: list[int] | None = None,
        result_generation: int | None = None,
    ) -> None:
        try:
            if status_group is None:
                owned = await tasks.list_owned_cards(
                    actor_telegram_user_id=actor_telegram_user_id,
                    creator_only=True,
                )
                has_more = False
            else:
                page_limit = _LIST_PAGE_SIZE if status_group in {"completed", "archive"} else 20
                fetch_limit = page_limit + 1 if status_group == "archive" else page_limit
                owned_items = []
                for status in _CREATED_STATUS_GROUPS[status_group]:
                    owned_items.extend(
                        await _list_created_status_cards(
                            tasks,
                            actor_telegram_user_id=actor_telegram_user_id,
                            status_group=status_group,
                            status=status,
                            cursor=cursor,
                            fetch_limit=fetch_limit,
                        )
                    )
                page = tuple(
                    sorted(
                        owned_items,
                        key=lambda item: (
                            item.task.updated_at
                            if status_group == "completed"
                            else item.task.created_at,
                            item.task.id,
                        ),
                        reverse=True,
                    )[:fetch_limit]
                )
                has_more = status_group == "archive" and len(page) > page_limit
                owned = page[:page_limit]
            for item in owned:
                sent = await message.answer(
                    owned_task_summary(item),
                    parse_mode=None,
                    reply_markup=owned_task_keyboard(item),
                )
                _capture_message_id(sent_message_ids, sent)
            review_sent = status_group in {
                None,
                "active",
            } and await send_assignment_review_overview(
                message,
                assignments,
                sent_message_ids=sent_message_ids,
            )
            if not owned and not review_sent:
                label = "" if status_group is None else f" {_STATUS_LABELS[status_group].lower()}"
                sent = await message.answer(f"У вас пока нет{label} созданных заданий.")
                _capture_message_id(sent_message_ids, sent)
            elif has_more:
                last = owned[-1].task
                await _send_archive_next(
                    message,
                    list_kind="created",
                    cursor_at=last.created_at,
                    cursor_id=last.id,
                    sent_message_ids=sent_message_ids,
                    result_generation=result_generation,
                )
        except (AssignmentError, PermissionError, LookupError, TaskError):
            sent = await message.answer("Задания, созданные вами, сейчас недоступны.")
            _capture_message_id(sent_message_ids, sent)

    async def show_assignments(message: Message) -> None:
        if message.from_user is None:
            return
        if not await _require_private_message(message):
            return
        async with task_result_lock(message):
            await clear_task_results(message)
            await send_assignments(
                message,
                message.from_user.id,
                sent_message_ids=start_task_results(message, "taken:all"),
            )

    async def send_assignments(  # noqa: PLR0913
        message: Message,
        actor_telegram_user_id: int,
        *,
        status_group: str | None = None,
        cursor: tuple[datetime, UUID] | None = None,
        sent_message_ids: list[int] | None = None,
        result_generation: int | None = None,
    ) -> None:
        try:
            statuses = None if status_group is None else _ASSIGNMENT_STATUS_GROUPS[status_group]
            label = "" if status_group is None else f" {_STATUS_LABELS[status_group].lower()}"
            page_limit = _LIST_PAGE_SIZE if status_group in {"completed", "archive"} else 50
            next_card = await send_assignment_overview(
                message,
                assignments,
                actor_telegram_user_id=actor_telegram_user_id,
                statuses=statuses,
                limit=page_limit,
                cursor=cursor,
                order_by_reviewed_at=status_group == "completed",
                empty_message=f"У вас пока нет{label} взятых заданий.",
                sent_message_ids=sent_message_ids,
            )
            if status_group == "archive" and next_card is not None:
                await _send_archive_next(
                    message,
                    list_kind="taken",
                    cursor_at=next_card.assignment.accepted_at,
                    cursor_id=next_card.assignment.id,
                    sent_message_ids=sent_message_ids,
                    result_generation=result_generation,
                )
        except (AssignmentError, PermissionError, LookupError, TaskError):
            sent = await message.answer("Задания, взятые вами, сейчас недоступны.")
            _capture_message_id(sent_message_ids, sent)

    async def show_profile(message: Message) -> None:
        if message.from_user is None:
            return
        async with task_result_lock(message):
            await clear_task_results(message)
            try:
                profile = await registration.own_profile(message.from_user.id)
                await message.answer(
                    own_profile_card(profile),
                    reply_markup=profile_edit_keyboard(),
                )
            except (PermissionError, LookupError, ValueError):
                await message.answer("Карточка сейчас недоступна.")

    async def show_statistics(message: Message) -> None:
        if message.from_user is None:
            return
        async with task_result_lock(message):
            await clear_task_results(message)
            try:
                await message.answer(await statistics_text(message.from_user.id))
            except (PermissionError, LookupError, ValueError):
                await message.answer("Статистика сейчас недоступна.")

    async def statistics_text(actor_telegram_user_id: int) -> str:
        value = await reputation.statistics(actor_telegram_user_id)
        return (
            f"Выполнено: {value.completed}\nЧастично: {value.partially_completed}\n"
            f"Опыт: {value.experience_earned}"
        )

    async def show_leaderboard(message: Message) -> None:
        if message.from_user is None:
            return
        async with task_result_lock(message):
            await clear_task_results(message)
            try:
                await message.answer(await leaderboard_text(message.from_user.id))
            except (PermissionError, LookupError, ValueError):
                await message.answer("Лидерборд сейчас недоступен.")

    async def leaderboard_text(actor_telegram_user_id: int) -> str:
        page = await reputation.leaderboard(telegram_user_id=actor_telegram_user_id)
        return (
            "Лидерборд пока пуст."
            if not page.items
            else "\n".join(
                f"{item.rank}. {item.display_name} — {item.experience} опыта" for item in page.items
            )
        )

    async def show_members(message: Message) -> None:
        async with task_result_lock(message):
            await clear_task_results(message)
            await send_member_catalog(message, reputation, moderation, foundation)

    async def change_member_role(callback: CallbackQuery, event_update: Update) -> None:
        """Apply a superadministrator-only role change from a visible member card."""
        if foundation is None:
            await callback.answer("Изменение роли недоступно.", show_alert=True)
            return
        try:
            raw_role, raw_member_id = str(callback.data).removeprefix("member:role:").split(":", 1)
            await foundation.change_member(
                AdministrativeChange(
                    update_id=event_update.update_id,
                    telegram_user_id=callback.from_user.id,
                    target_member_id=UUID(hex=raw_member_id),
                    kind=ChangeKind.ROLE,
                    requested_value=raw_role,
                    reason="Изменение роли через Telegram",
                )
            )
            await callback.answer("Роль участника изменена.", show_alert=True)
        except (AuthorizationError, PermissionError, LookupError, ValueError):
            await callback.answer("Изменение роли недоступно.", show_alert=True)

    async def show_admin(message: Message) -> None:
        if message.from_user is None:
            return
        async with task_result_lock(message):
            await clear_task_results(message)
            try:
                await navigation.require_active_administrator(message.from_user.id)
                await message.answer(
                    "Администрирование",
                    reply_markup=_admin_markup(
                        include_task_creation=message.chat.type == "private"
                    ),
                )
            except PermissionError:
                try:
                    await send_moderation_overview(message, moderation)
                except (PermissionError, LookupError, ValueError):
                    await message.answer("Административное меню недоступно.")

    async def community_approvals_action(callback: CallbackQuery) -> None:
        try:
            await navigation.require_active_administrator(callback.from_user.id)
            requests = await tasks.pending_community_publications(
                actor_telegram_user_id=callback.from_user.id
            )
            body = (
                "Заданий на подтверждение нет."
                if not requests
                else "Задания на подтверждение:\n"
                + "\n".join(
                    "• "
                    f"{item.template_name} от {item.creator_display_name}; "
                    f"проверяет {item.reviewer_display_name}"
                    for item in requests
                )
            )
            await callback.answer()
            if isinstance(callback.message, Message):
                await callback.message.answer(
                    body,
                    reply_markup=community_publication_approval_keyboard(requests),
                )
        except (TaskError, PermissionError, LookupError, ValueError):
            await callback.answer("Административное действие недоступно.", show_alert=True)

    async def admin_action(callback: CallbackQuery, event_update: Update) -> None:
        try:
            await navigation.require_active_administrator(callback.from_user.id)
            action = str(callback.data).removeprefix(_ADMIN_PREFIX)
            if action == "community" and (
                not isinstance(callback.message, Message) or callback.message.chat.type != "private"
            ):
                await callback.answer(
                    "Создавайте задания сообщества в личном чате с ботом.",
                    show_alert=True,
                )
                return
            if action == "invite":
                result = await registration.create_invitation(
                    InvitationCreateCommand(
                        update_id=event_update.update_id,
                        actor_telegram_user_id=callback.from_user.id,
                        max_uses=1,
                        expires_at=datetime.now(UTC) + timedelta(days=7),
                    )
                )
                await callback.answer("Приглашение создано.")
                if isinstance(callback.message, Message):
                    link = (
                        f"/start {result.token}"
                        if callback.bot is None
                        else await create_start_link(callback.bot, result.token)
                    )
                    await callback.message.answer(
                        "Передайте участнику эту одноразовую ссылку:\n"
                        f"{link}\n\n"
                        f"Если ссылка не открывается: /start {result.token}",
                        parse_mode=None,
                    )
                return
            if action == "community":
                page = await catalog.browse(
                    CatalogQuery(actor_telegram_user_id=callback.from_user.id, limit=20)
                )
                await callback.answer()
                if isinstance(callback.message, Message):
                    await _send_creation_catalog(
                        callback.message,
                        page,
                        prefix=_COMMUNITY_PREFIX,
                    )
                return
            if action == "registrations":
                applications = await registration.submitted_registrations(
                    actor_telegram_user_id=callback.from_user.id
                )
                body = (
                    "Новых заявок нет."
                    if not applications
                    else "\n".join(
                        str(item.payload.get("display_name", "Без имени")) for item in applications
                    )
                )
            elif action == "moderation":
                await callback.answer()
                if isinstance(callback.message, Message):
                    await send_moderation_overview(callback.message, moderation)
                return
            else:
                await callback.answer("Административное действие недоступно.", show_alert=True)
                return
            await callback.answer()
            if isinstance(callback.message, Message):
                await callback.message.answer(body)
        except (TaskError, PermissionError, LookupError, ValueError):
            await callback.answer("Административное действие недоступно.", show_alert=True)

    async def menu_action(
        callback: CallbackQuery,
        event_update: Update,
    ) -> None:
        if not await _require_private_callback(callback):
            return
        message = callback.message
        if not isinstance(message, Message):
            return
        action = str(callback.data).removeprefix(_MENU_PREFIX)
        lock = task_result_lock(message)
        await lock.acquire()
        try:
            if action == "noop":
                await callback.answer("Этот раздел уже открыт.")
                return
            await clear_task_results(message)
            if action == "root":
                await message.edit_text("Главное меню открыто ниже.", reply_markup=None)
                await callback.answer()
                return
            if action == "tasks":
                await message.edit_text("Задания", reply_markup=_task_menu_markup())
                await callback.answer()
                return
            if action == "mine":
                await message.edit_text("Мои задания", reply_markup=_my_tasks_menu_markup())
                await callback.answer()
                return
            if action in {"created", "taken"}:
                await message.edit_text(
                    _task_list_title(action),
                    reply_markup=_task_filter_markup(action),
                )
                await callback.answer()
                return
            if action == "find":
                await message.edit_text(
                    "Задания · Найти",
                    reply_markup=_section_back_markup("tasks"),
                )
                await callback.answer()
                await send_available_tasks(
                    message,
                    callback.from_user.id,
                    sent_message_ids=start_task_results(message, "find"),
                    result_generation=current_task_generation(message),
                )
                return
            if action == "create":
                await message.edit_text(
                    "Задания · Создать",
                    reply_markup=_section_back_markup("tasks"),
                )
                await callback.answer()
                sent_message_ids = start_task_results(message, "create")
                try:
                    draft = await tasks.start(
                        update_id=event_update.update_id,
                        actor_telegram_user_id=callback.from_user.id,
                        template_id=None,
                    )
                    if draft is None:
                        sent = await message.answer("Создание задания сейчас недоступно.")
                        _capture_message_id(sent_message_ids, sent)
                        return
                    await send_task_draft_prompt(
                        message,
                        draft,
                        service=tasks,
                        actor_telegram_user_id=callback.from_user.id,
                    )
                except (TaskError, PermissionError, LookupError, ValueError):
                    sent = await message.answer("Создание задания сейчас недоступно.")
                    _capture_message_id(sent_message_ids, sent)
                return
            if action == "insights":
                await message.edit_text(INSIGHTS_TEXT, reply_markup=_insights_menu_markup())
                await callback.answer()
                return
            if action in {"balance", "statistics", "leaderboard"}:
                if action == "balance":
                    body = await balance_text(callback.from_user.id)
                elif action == "statistics":
                    body = await statistics_text(callback.from_user.id)
                else:
                    body = await leaderboard_text(callback.from_user.id)
                await message.edit_text(
                    body,
                    reply_markup=_insights_menu_markup(selected=action),
                )
                await callback.answer()
                return
            list_kind, separator, status_group = action.partition(":")
            if separator and list_kind in {"created", "taken"} and status_group in _STATUS_LABELS:
                await message.edit_text(
                    f"{_task_list_title(list_kind)} · {_STATUS_LABELS[status_group]}",
                    reply_markup=_task_filter_markup(list_kind, selected=status_group),
                )
                await callback.answer()
                if list_kind == "created":
                    sent_message_ids = start_task_results(message, f"created:{status_group}")
                    await send_owned_tasks(
                        message,
                        callback.from_user.id,
                        status_group=status_group,
                        sent_message_ids=sent_message_ids,
                        result_generation=current_task_generation(message),
                    )
                else:
                    sent_message_ids = start_task_results(message, f"taken:{status_group}")
                    await send_assignments(
                        message,
                        callback.from_user.id,
                        status_group=status_group,
                        sent_message_ids=sent_message_ids,
                        result_generation=current_task_generation(message),
                    )
                return
            await callback.answer("Раздел меню недоступен.", show_alert=True)
        except (
            AssignmentError,
            AuthorizationError,
            CatalogError,
            PermissionError,
            LookupError,
            TaskError,
            ValueError,
        ):
            await callback.answer("Не удалось открыть раздел меню.", show_alert=True)
        finally:
            lock.release()

    async def next_archive(callback: CallbackQuery) -> None:
        if not await _require_private_callback(callback):
            return
        message = callback.message
        if not isinstance(message, Message):
            return
        lock = task_result_lock(message)
        await lock.acquire()
        try:
            callback_data = str(callback.data)
            list_kind, cursor, generation = _parse_archive_cursor(callback_data)
            if task_result_views.get(message.chat.id) != (f"{list_kind}:archive", generation):
                await callback.answer("Этот список уже обновлён.", show_alert=True)
                return
            consumed = consumed_pagination_callbacks.setdefault(message.chat.id, set())
            if callback_data in consumed:
                await callback.answer("Эта страница уже открыта.", show_alert=True)
                return
            await callback.answer()
            if list_kind == "created":
                await send_owned_tasks(
                    message,
                    callback.from_user.id,
                    status_group="archive",
                    cursor=cursor,
                    sent_message_ids=current_task_results(message),
                    result_generation=generation,
                )
            else:
                await send_assignments(
                    message,
                    callback.from_user.id,
                    status_group="archive",
                    cursor=cursor,
                    sent_message_ids=current_task_results(message),
                    result_generation=generation,
                )
            consumed.add(callback_data)
            with suppress(TelegramAPIError):
                await message.edit_reply_markup(reply_markup=None)
        except (
            AssignmentError,
            PermissionError,
            LookupError,
            TaskError,
            TelegramAPIError,
            ValueError,
        ):
            consumed_pagination_callbacks.get(message.chat.id, set()).discard(str(callback.data))
            await callback.answer("Не удалось открыть следующую страницу.", show_alert=True)
        finally:
            lock.release()

    router.message.register(show_tasks, Command("tasks"))
    router.message.register(show_task_menu, F.text == TASKS_TEXT)
    router.callback_query.register(next_tasks, F.data.startswith(_TASK_PAGE_PREFIX))
    router.message.register(show_create, Command("create"))
    router.callback_query.register(
        choose_template,
        F.data.startswith(_CREATE_PREFIX) | F.data.startswith(_COMMUNITY_PREFIX),
    )
    router.message.register(show_balance, Command("balance"))
    router.message.register(show_insights, F.text == INSIGHTS_TEXT)
    router.message.register(show_owned, Command("my_tasks"))
    router.message.register(show_assignments, Command("my_assignments"))
    router.message.register(show_statistics, Command("statistics"))
    router.message.register(show_leaderboard, Command("leaderboard"))
    router.message.register(show_help, Command("help"))
    router.message.register(show_help, F.text == HELP_TEXT)
    router.message.register(show_profile, F.text == PROFILE_TEXT)
    router.message.register(show_members, F.text == MEMBERS_TEXT)
    router.message.register(show_admin, Command("admin"))
    router.message.register(show_admin, F.text == ADMIN_TEXT)
    router.callback_query.register(menu_action, F.data.startswith(_MENU_PREFIX))
    router.callback_query.register(next_archive, F.data.startswith(_LIST_PAGE_PREFIX))
    router.callback_query.register(
        community_approvals_action,
        F.data == "nav:admin:community_approvals",
    )
    router.callback_query.register(admin_action, F.data.startswith(_ADMIN_PREFIX))
    router.callback_query.register(change_member_role, F.data.startswith("member:role:"))
    return router


def _task_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _menu_button("Найти", "find"),
                _menu_button("Создать", "create"),
            ],
            [_menu_button("Мои задания", "mine")],
            [_menu_button("Назад", "root")],
        ]
    )


def _my_tasks_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_menu_button("Созданные мной", "created")],
            [_menu_button("Взятые мной", "taken")],
            [_menu_button("Назад", "tasks")],
        ]
    )


def _task_filter_markup(list_kind: str, *, selected: str | None = None) -> InlineKeyboardMarkup:
    def status_button(status: str) -> InlineKeyboardButton:
        label = _STATUS_LABELS[status]
        if status == selected:
            return _menu_button(f"✓ {label}", "noop")
        return _menu_button(label, f"{list_kind}:{status}")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [status_button("active")],
            [status_button("completed")],
            [status_button("archive")],
            [_menu_button("Назад", "mine")],
        ]
    )


def _insights_menu_markup(*, selected: str | None = None) -> InlineKeyboardMarkup:
    def insight_button(label: str, action: str) -> InlineKeyboardButton:
        if action == selected:
            return _menu_button(f"✓ {label}", "noop")
        return _menu_button(label, action)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                insight_button("Баланс", "balance"),
                insight_button("Статистика", "statistics"),
            ],
            [insight_button("Лидерборд", "leaderboard")],
            [_menu_button("Назад", "root")],
        ]
    )


def _section_back_markup(section: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_menu_button("Назад", section)]])


def _menu_button(text: str, action: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=f"{_MENU_PREFIX}{action}")


def _created_status_group_matches(card: OwnedTaskCard, status_group: str) -> bool:
    if card.task.status is not TaskStatus.PARTIALLY_COMPLETED:
        return True
    has_free_slots = len(card.assignees) < card.task.performer_slots
    return has_free_slots if status_group == "active" else not has_free_slots


async def _list_created_status_cards(  # noqa: PLR0913
    tasks: TaskService,
    *,
    actor_telegram_user_id: int,
    status_group: str,
    status: TaskStatus,
    cursor: tuple[datetime, UUID] | None,
    fetch_limit: int,
) -> tuple[OwnedTaskCard, ...]:
    """Filter mixed partial states without losing cards behind the database limit."""
    page_cursor = cursor
    matches: list[OwnedTaskCard] = []
    page_size = 20 if status is TaskStatus.PARTIALLY_COMPLETED else fetch_limit
    while len(matches) < fetch_limit:
        cards = await tasks.list_owned_cards(
            actor_telegram_user_id=actor_telegram_user_id,
            limit=page_size,
            status=status,
            cursor=page_cursor,
            creator_only=True,
            order_by_updated_at=status_group == "completed",
        )
        matches.extend(item for item in cards if _created_status_group_matches(item, status_group))
        if status is not TaskStatus.PARTIALLY_COMPLETED or len(cards) < page_size:
            break
        last = cards[-1].task
        page_cursor = (
            last.updated_at if status_group == "completed" else last.created_at,
            last.id,
        )
    return tuple(matches[:fetch_limit])


def _task_list_title(list_kind: str) -> str:
    return "Созданные мной" if list_kind == "created" else "Взятые мной"


async def _send_archive_next(  # noqa: PLR0913
    message: Message,
    *,
    list_kind: str,
    cursor_at: datetime,
    cursor_id: UUID,
    sent_message_ids: list[int] | None = None,
    result_generation: int | None = None,
) -> None:
    if result_generation is None:
        raise ValueError(_ARCHIVE_CALLBACK_INVALID)
    code = "ca" if list_kind == "created" else "ta"
    micros = int(cursor_at.timestamp() * 1_000_000)
    callback_data = (
        f"{_LIST_PAGE_PREFIX}{code}:{micros:x}:{_encode_uuid(cursor_id)}:{result_generation:012x}"
    )
    if len(callback_data.encode()) > _CALLBACK_LIMIT:
        raise ValueError(_ARCHIVE_CALLBACK_TOO_LONG)
    sent = await message.answer(
        "В архиве есть ещё задания.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Показать ещё", callback_data=callback_data)]
            ]
        ),
    )
    _capture_message_id(sent_message_ids, sent)


def _parse_archive_cursor(value: str) -> tuple[str, tuple[datetime, UUID], int]:
    code, raw_micros, raw_id, raw_generation = value.removeprefix(_LIST_PAGE_PREFIX).split(":", 3)
    if code not in {"ca", "ta"}:
        raise ValueError(_ARCHIVE_CALLBACK_INVALID)
    micros = int(raw_micros, 16)
    cursor_at = datetime.fromtimestamp(micros / 1_000_000, UTC)
    return (
        "created" if code == "ca" else "taken",
        (cursor_at, _decode_uuid(raw_id)),
        int(raw_generation, 16),
    )


def _parse_task_cursor(value: str) -> tuple[UUID, int]:
    raw_id, raw_generation = value.removeprefix(_TASK_PAGE_PREFIX).split(":", 1)
    return UUID(raw_id), int(raw_generation, 16)


def _encode_uuid(value: UUID) -> str:
    return urlsafe_b64encode(value.bytes).rstrip(b"=").decode("ascii")


def _decode_uuid(value: str) -> UUID:
    return UUID(bytes=urlsafe_b64decode(f"{value}=="))


async def _require_private_message(
    message: Message,
    *,
    error: str = "Задания доступны только в личном чате с ботом.",
) -> bool:
    if message.chat.type == "private":
        return True
    await message.answer(error)
    return False


async def _require_private_callback(callback: CallbackQuery) -> bool:
    if isinstance(callback.message, Message) and callback.message.chat.type == "private":
        return True
    await callback.answer("Откройте меню в личном чате с ботом.", show_alert=True)
    return False


async def _send_task_page(
    message: Message,
    page: AvailableTaskPage,
    *,
    sent_message_ids: list[int] | None = None,
    result_generation: int | None = None,
) -> None:
    if not page.items:
        sent = await message.answer("Доступных заданий пока нет.")
        _capture_message_id(sent_message_ids, sent)
        return
    for task in page.items:
        sent = await message.answer(
            published_task_card(task),
            parse_mode=None,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Взять", callback_data=f"task:accept:{task.id}")]
                ]
            ),
        )
        _capture_message_id(sent_message_ids, sent)
    if page.next_cursor_task_id is not None:
        if result_generation is None:
            raise ValueError(_ARCHIVE_CALLBACK_INVALID)
        sent = await message.answer(
            "Есть ещё задания.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Следующая страница",
                            callback_data=(
                                f"{_TASK_PAGE_PREFIX}{page.next_cursor_task_id}:"
                                f"{result_generation:012x}"
                            ),
                        )
                    ]
                ]
            ),
        )
        _capture_message_id(sent_message_ids, sent)


async def _send_creation_catalog(
    message: Message,
    page: CatalogPage,
    *,
    prefix: str,
    sent_message_ids: list[int] | None = None,
) -> None:
    if not page.items:
        sent = await message.answer("Доступных шаблонов пока нет.")
        _capture_message_id(sent_message_ids, sent)
        return
    for template in page.items:
        sent = await message.answer(
            f"{template.category_name} · {template.name}\n{template.description}\n"
            f"Награда: {template.credit_reward} кредита",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Создать по шаблону",
                            callback_data=f"{prefix}{template.id.hex}",
                        )
                    ]
                ]
            ),
        )
        _capture_message_id(sent_message_ids, sent)


def _capture_message_id(message_ids: list[int] | None, message: Message) -> None:
    if message_ids is not None:
        message_ids.append(message.message_id)


def _admin_markup(*, include_task_creation: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Создать приглашение", callback_data="nav:admin:invite")],
        [InlineKeyboardButton(text="Заявки", callback_data="registration:list")],
    ]
    if include_task_creation:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Создать задание сообщества",
                    callback_data="nav:admin:community",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Подтверждения заданий",
                    callback_data="nav:admin:community_approvals",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Модерация", callback_data="nav:admin:moderation")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ledger_line(item: LedgerHistoryItem) -> str:
    labels = {
        "starting_grant": "Стартовое начисление",
        "task_reward_reserved": "Резерв задания",
        "task_reward_earned": "Награда за задание",
        "task_reward_refunded": "Возврат резерва",
        "partial_task_reward": "Частичная награда",
        "community_task_reward": "Награда сообщества",
        "penalty": "Штраф",
        "admin_adjustment": "Корректировка",
        "fraud_reversal": "Отмена выплаты",
        "resolution_reversal": "Корректировка решения",
    }
    sign = "+" if item.credit_delta > 0 else ""
    label = labels.get(item.transaction_type, "Операция")
    return f"{item.created_at:%d.%m} · {label} · {sign}{item.credit_delta}"


_HELP_TEXT = """Как пользоваться ботом:
• /tasks — найти доступное задание и нажать «Взять»;
• /create — выбрать шаблон и заполнить карточку;
• /my_tasks — созданные мной задания;
• /my_assignments — принятые мной задания;
• /profile — моя карточка;
• /balance — кредиты и последние операции;
• /stats и /leaderboard — вклад и рейтинг;
• /cancel — отменить текущий диалог;
• /help — снова открыть эту подсказку.

Модератору и администратору: /admin открывает доступную очередь модерации;
администратору также доступны приглашения, заявки и служебные разделы."""
