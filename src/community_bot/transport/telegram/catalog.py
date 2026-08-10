"""Telegram routes for catalog browsing and minimal administration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update

from community_bot.application.catalog import CatalogQuery
from community_bot.domain.catalog import CatalogCursor, CatalogError, TaskFormat

if TYPE_CHECKING:
    from community_bot.application.catalog import CatalogPage, CatalogService, CatalogTemplate

_FORMAT_CODES = {None: "-", TaskFormat.ONLINE: "o", TaskFormat.OFFLINE: "f"}
_CODE_FORMATS = {"-": None, "o": TaskFormat.ONLINE, "f": TaskFormat.OFFLINE}
_TELEGRAM_CALLBACK_LIMIT = 64
_ARGUMENT_PAIR_SIZE = 2
_PAGE_CALLBACK_PARTS = 6


def build_catalog_router(service: CatalogService) -> Router:
    """Build catalog list, pagination, and focused admin commands."""
    router = Router(name="catalog")

    async def handle_catalog(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            category, task_format = _parse_catalog_filters(message.text)
            page = await service.browse(
                CatalogQuery(
                    actor_telegram_user_id=message.from_user.id,
                    category_code=category,
                    format=task_format,
                )
            )
            await _send_page(message, page, category=category, task_format=task_format)
        except (CatalogError, PermissionError, LookupError, ValueError) as error:
            await message.answer(_friendly_error(error))

    async def handle_page(callback: CallbackQuery) -> None:
        try:
            category, task_format, cursor = _parse_page_callback(str(callback.data))
            page = await service.browse(
                CatalogQuery(
                    actor_telegram_user_id=callback.from_user.id,
                    category_code=category,
                    format=task_format,
                    cursor=cursor,
                )
            )
            await callback.answer()
            if isinstance(callback.message, Message):
                await _send_page(
                    callback.message,
                    page,
                    category=category,
                    task_format=task_format,
                )
        except (CatalogError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_friendly_error(error), show_alert=True)

    async def handle_category_toggle(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            code, enabled = _parse_toggle(message.text)
            await service.set_category_active(
                update_id=event_update.update_id,
                actor_telegram_user_id=message.from_user.id,
                code=code,
                enabled=enabled,
            )
            await message.answer("Категория включена." if enabled else "Категория отключена.")
        except (CatalogError, PermissionError, LookupError, ValueError) as error:
            await message.answer(_friendly_error(error))

    async def handle_template_toggle(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            code, enabled = _parse_toggle(message.text)
            await service.set_template_active(
                update_id=event_update.update_id,
                actor_telegram_user_id=message.from_user.id,
                code=code,
                enabled=enabled,
            )
            await message.answer("Шаблон включён." if enabled else "Шаблон отключён.")
        except (CatalogError, PermissionError, LookupError, ValueError) as error:
            await message.answer(_friendly_error(error))

    async def handle_reward_change(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            code, reward = _parse_reward(message.text)
            template = await service.change_reward(
                update_id=event_update.update_id,
                actor_telegram_user_id=message.from_user.id,
                code=code,
                credit_reward=reward,
            )
            await message.answer(
                f"Опубликована версия {template.version}: {template.credit_reward} кредитов."
            )
        except (CatalogError, PermissionError, LookupError, ValueError) as error:
            await message.answer(_friendly_error(error))

    router.message.register(handle_catalog, Command("catalog"))
    router.callback_query.register(handle_page, F.data.startswith("catalog:p:"))
    router.message.register(handle_category_toggle, Command("catalog_category"))
    router.message.register(handle_template_toggle, Command("catalog_template"))
    router.message.register(handle_reward_change, Command("catalog_template_reward"))
    return router


async def _send_page(
    message: Message,
    page: CatalogPage,
    *,
    category: str | None,
    task_format: TaskFormat | None,
) -> None:
    if not page.items:
        await message.answer("Доступных шаблонов пока нет.")
        return
    text = "\n\n".join(_template_card(item) for item in page.items)
    markup = None
    if page.next_cursor is not None:
        callback_data = _page_callback(category, task_format, page.next_cursor)
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Следующая страница", callback_data=callback_data)]
            ]
        )
    await message.answer(text, reply_markup=markup)


def _template_card(template: CatalogTemplate) -> str:
    moderation = " · с модерацией" if template.moderation_required else ""
    return (
        f"{template.category_name} · {template.name}\n"
        f"{template.description}\n"
        f"{template.credit_reward} кредита · {template.estimated_minutes} мин. · "
        f"{template.format.value} · уровень {template.minimum_level}{moderation}"
    )


def _parse_catalog_filters(text: str | None) -> tuple[str | None, TaskFormat | None]:
    parts = _command_tail(text).split()
    if len(parts) > _ARGUMENT_PAIR_SIZE:
        message = "Use /catalog [category_code] [online|offline]."
        raise ValueError(message)
    category = parts[0] if parts else None
    task_format = TaskFormat(parts[1]) if len(parts) == _ARGUMENT_PAIR_SIZE else None
    if task_format is TaskFormat.ANY:
        task_format = None
    return category, task_format


def _parse_toggle(text: str | None) -> tuple[str, bool]:
    parts = _command_tail(text).split()
    if len(parts) != _ARGUMENT_PAIR_SIZE or parts[1] not in {"on", "off"}:
        message = "Use command with <code> <on|off>."
        raise ValueError(message)
    return parts[0], parts[1] == "on"


def _parse_reward(text: str | None) -> tuple[str, int]:
    parts = _command_tail(text).split()
    if len(parts) != _ARGUMENT_PAIR_SIZE:
        message = "Use /catalog_template_reward <code> <reward>."
        raise ValueError(message)
    return parts[0], int(parts[1])


def _page_callback(
    category: str | None,
    task_format: TaskFormat | None,
    cursor: CatalogCursor,
) -> str:
    value = f"catalog:p:{category or '-'}:{_FORMAT_CODES[task_format]}:{cursor.encode()}"
    if len(value.encode()) > _TELEGRAM_CALLBACK_LIMIT:
        message = "Catalog callback exceeds the Telegram limit."
        raise CatalogError(message)
    return value


def _parse_page_callback(
    value: str,
) -> tuple[str | None, TaskFormat | None, CatalogCursor]:
    parts = value.split(":", 5)
    if (
        len(parts) != _PAGE_CALLBACK_PARTS
        or parts[:2] != ["catalog", "p"]
        or parts[3] not in _CODE_FORMATS
    ):
        message = "Catalog callback is invalid."
        raise CatalogError(message)
    return (
        None if parts[2] == "-" else parts[2],
        _CODE_FORMATS[parts[3]],
        CatalogCursor.decode(f"{parts[4]}:{parts[5]}"),
    )


def _command_tail(text: str | None) -> str:
    if not text:
        return ""
    _command, separator, tail = text.partition(" ")
    return tail.strip() if separator else ""


def _friendly_error(error: Exception) -> str:
    if isinstance(error, PermissionError):
        return "Это действие вам недоступно."
    if isinstance(error, LookupError):
        return "Категория или шаблон не найдены."
    return "Не удалось обработать каталог. Проверьте параметры и попробуйте ещё раз."
