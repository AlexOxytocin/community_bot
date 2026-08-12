# ruff: noqa: C901, PLR0915, RUF001
"""User-facing Telegram commands and menus for the complete MVP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from aiogram import F, Router
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
from community_bot.application.registration import InvitationCreateCommand
from community_bot.domain.catalog import CatalogError
from community_bot.domain.members import AuthorizationError
from community_bot.domain.tasks import TaskError
from community_bot.transport.telegram.assignments import send_assignment_overview
from community_bot.transport.telegram.moderation import send_moderation_overview
from community_bot.transport.telegram.profile import (
    PROFILE_TEXT,
    own_profile_card,
    profile_edit_keyboard,
)
from community_bot.transport.telegram.reputation import send_member_catalog

if TYPE_CHECKING:
    from community_bot.application.assignments import AssignmentService
    from community_bot.application.catalog import CatalogPage, CatalogService
    from community_bot.application.economy import EconomyQueryService, LedgerHistoryItem
    from community_bot.application.moderation import ModerationService
    from community_bot.application.navigation import NavigationService
    from community_bot.application.registration import RegistrationService
    from community_bot.application.reputation import ReputationService
    from community_bot.application.tasks import AvailableTaskPage, TaskService

FIND_TASK_TEXT = "Найти задание"
CREATE_TASK_TEXT = "Создать задание"
MY_TASKS_TEXT = "Мои задания"
BALANCE_TEXT = "Баланс"
STATISTICS_TEXT = "Статистика"
LEADERBOARD_TEXT = "Лидерборд"
MEMBERS_TEXT = "Участники"
HELP_TEXT = "Помощь"
ADMIN_TEXT = "Администрирование"
_TASK_PAGE_PREFIX = "nav:tasks:"
_CREATE_PREFIX = "nav:create:"
_COMMUNITY_PREFIX = "nav:community:"
_ADMIN_PREFIX = "nav:admin:"


def main_menu_markup() -> ReplyKeyboardMarkup:
    """Return the canonical active-member reply keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=FIND_TASK_TEXT), KeyboardButton(text=CREATE_TASK_TEXT)],
            [KeyboardButton(text=MY_TASKS_TEXT), KeyboardButton(text=PROFILE_TEXT)],
            [KeyboardButton(text=BALANCE_TEXT), KeyboardButton(text=STATISTICS_TEXT)],
            [KeyboardButton(text=LEADERBOARD_TEXT), KeyboardButton(text=MEMBERS_TEXT)],
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
) -> Router:
    """Build exact commands, button mappings, and navigation callbacks."""
    router = Router(name="navigation")

    async def show_tasks(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            await _send_task_page(
                message, await tasks.list_available(actor_telegram_user_id=message.from_user.id)
            )
        except (PermissionError, LookupError, TaskError):
            await message.answer("Доступные задания сейчас не открываются.")

    async def next_tasks(callback: CallbackQuery) -> None:
        try:
            cursor = UUID(str(callback.data).removeprefix(_TASK_PAGE_PREFIX))
            page = await tasks.list_available(
                actor_telegram_user_id=callback.from_user.id, cursor_task_id=cursor
            )
            await callback.answer()
            if isinstance(callback.message, Message):
                await _send_task_page(callback.message, page)
        except (PermissionError, LookupError, TaskError, ValueError):
            await callback.answer("Не удалось открыть страницу заданий.", show_alert=True)

    async def show_create(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            page = await catalog.browse(
                CatalogQuery(actor_telegram_user_id=message.from_user.id, limit=20)
            )
            await _send_creation_catalog(message, page, prefix=_CREATE_PREFIX)
        except (CatalogError, PermissionError, LookupError):
            await message.answer("Каталог создания сейчас недоступен.")

    async def choose_template(callback: CallbackQuery, event_update: Update) -> None:
        try:
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
        try:
            profile = await registration.own_profile(message.from_user.id)
            history = await economy.history(
                telegram_user_id=message.from_user.id, target_member_id=profile.member_id, limit=10
            )
            lines = [f"Баланс: {profile.credit_balance} кредитов"]
            lines.extend(
                ["Операций пока нет."]
                if not history.items
                else [_ledger_line(item) for item in history.items]
            )
            await message.answer("\n".join(lines))
        except (AuthorizationError, PermissionError, LookupError, ValueError):
            await message.answer("Баланс сейчас недоступен.")

    async def show_help(message: Message) -> None:
        await message.answer(_HELP_TEXT, reply_markup=main_menu_markup())

    async def show_owned(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            owned = await tasks.list_owned(actor_telegram_user_id=message.from_user.id)
            body = (
                "У вас пока нет опубликованных заданий."
                if not owned
                else "\n".join(f"{item.title} · {item.status.value}" for item in owned)
            )
            await message.answer(body)
            await send_assignment_overview(message, assignments)
        except (PermissionError, LookupError, TaskError):
            await message.answer("Ваши задания сейчас недоступны.")

    async def show_profile(message: Message) -> None:
        if message.from_user is None:
            return
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
        try:
            value = await reputation.statistics(message.from_user.id)
            await message.answer(
                f"Выполнено: {value.completed}\nЧастично: {value.partially_completed}\n"
                f"Опыт: {value.experience_earned}"
            )
        except (PermissionError, LookupError, ValueError):
            await message.answer("Статистика сейчас недоступна.")

    async def show_leaderboard(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            page = await reputation.leaderboard(telegram_user_id=message.from_user.id)
            body = (
                "Лидерборд пока пуст."
                if not page.items
                else "\n".join(
                    f"{item.rank}. {item.display_name} — {item.experience} опыта"
                    for item in page.items
                )
            )
            await message.answer(body)
        except (PermissionError, LookupError, ValueError):
            await message.answer("Лидерборд сейчас недоступен.")

    async def show_members(message: Message) -> None:
        await send_member_catalog(message, reputation, moderation)

    async def show_admin(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            await navigation.require_active_administrator(message.from_user.id)
            await message.answer("Администрирование", reply_markup=_admin_markup())
        except PermissionError:
            try:
                await send_moderation_overview(message, moderation)
            except (PermissionError, LookupError, ValueError):
                await message.answer("Административное меню недоступно.")

    async def admin_action(callback: CallbackQuery, event_update: Update) -> None:
        try:
            await navigation.require_active_administrator(callback.from_user.id)
            action = str(callback.data).removeprefix(_ADMIN_PREFIX)
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
        except (PermissionError, LookupError, ValueError):
            await callback.answer("Административное действие недоступно.", show_alert=True)

    router.message.register(show_tasks, Command("tasks"))
    router.message.register(show_tasks, F.text == FIND_TASK_TEXT)
    router.callback_query.register(next_tasks, F.data.startswith(_TASK_PAGE_PREFIX))
    router.message.register(show_create, Command("create"))
    router.message.register(show_create, F.text == CREATE_TASK_TEXT)
    router.callback_query.register(
        choose_template,
        F.data.startswith(_CREATE_PREFIX) | F.data.startswith(_COMMUNITY_PREFIX),
    )
    router.message.register(show_balance, Command("balance"))
    router.message.register(show_balance, F.text == BALANCE_TEXT)
    router.message.register(show_help, Command("help"))
    router.message.register(show_help, F.text == HELP_TEXT)
    router.message.register(show_owned, F.text == MY_TASKS_TEXT)
    router.message.register(show_profile, F.text == PROFILE_TEXT)
    router.message.register(show_statistics, F.text == STATISTICS_TEXT)
    router.message.register(show_leaderboard, F.text == LEADERBOARD_TEXT)
    router.message.register(show_members, F.text == MEMBERS_TEXT)
    router.message.register(show_admin, Command("admin"))
    router.message.register(show_admin, F.text == ADMIN_TEXT)
    router.callback_query.register(admin_action, F.data.startswith(_ADMIN_PREFIX))
    return router


async def _send_task_page(message: Message, page: AvailableTaskPage) -> None:
    if not page.items:
        await message.answer("Доступных заданий пока нет.")
        return
    for task in page.items:
        await message.answer(
            f"{task.title}\n{task.description}\nНаграда: {task.credit_reward_per_performer} "
            f"кредита\nСрок: {task.deadline_at:%d.%m %H:%M}\nФормат: {task.format.value}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Взять", callback_data=f"task:accept:{task.id}")]
                ]
            ),
        )
    if page.next_cursor_task_id is not None:
        await message.answer(
            "Есть ещё задания.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Следующая страница",
                            callback_data=f"{_TASK_PAGE_PREFIX}{page.next_cursor_task_id}",
                        )
                    ]
                ]
            ),
        )


async def _send_creation_catalog(
    message: Message,
    page: CatalogPage,
    *,
    prefix: str,
) -> None:
    if not page.items:
        await message.answer("Доступных шаблонов пока нет.")
        return
    for template in page.items:
        await message.answer(
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


def _admin_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Создать приглашение", callback_data="nav:admin:invite")],
            [InlineKeyboardButton(text="Заявки", callback_data="registration:list")],
            [
                InlineKeyboardButton(
                    text="Создать задание сообщества",
                    callback_data="nav:admin:community",
                )
            ],
            [InlineKeyboardButton(text="Модерация", callback_data="nav:admin:moderation")],
        ]
    )


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
• /my_tasks — мои опубликованные задания;
• /profile — моя карточка;
• /balance — кредиты и последние операции;
• /stats и /leaderboard — вклад и рейтинг;
• /cancel — отменить текущий диалог;
• /help — снова открыть эту подсказку.

Модератору и администратору: /admin открывает доступную очередь модерации;
администратору также доступны приглашения, заявки и служебные разделы."""
