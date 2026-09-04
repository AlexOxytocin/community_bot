from __future__ import annotations

import functools
import http.server
import json
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from community_bot.application.community_stats import CommunityStatsService

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Page, Route

pytestmark = pytest.mark.browser

STATIC_DIR = Path(__file__).parents[2] / "src/community_bot/transport/static"
TELEGRAM_BRIDGE_URL = "https://telegram.org/js/telegram-web-app.js"


class _AssetsHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ANN401
        del format, args

    def translate_path(self, path: str) -> str:
        request_path = urlsplit(path).path
        relative = (
            "index.html" if request_path == "/" else request_path.removeprefix("/mini-assets/")
        )
        return str(STATIC_DIR / relative)


@pytest.fixture
def mini_app_url() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        functools.partial(_AssetsHandler, directory=STATIC_DIR),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _new_page(browser: Any, *, bridge: str = "") -> Any:  # noqa: ANN401
    page = browser.new_page()
    page.route(
        TELEGRAM_BRIDGE_URL,
        lambda route: route.fulfill(body=bridge, content_type="application/javascript"),
    )
    return page


@pytest.mark.browser_smoke
def test_wallet_root_and_recovery_keep_one_transfer_identity(mini_app_url: str) -> None:
    sent: list[dict[str, Any]] = []
    recipient = {
        "member_id": "00000000-0000-0000-0000-000000000222",
        "display_name": "Маша",
        "telegram_username": "masha",
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 390, "height": 844})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(
            "**/api/v1/**", lambda route: route.fulfill(status=403, json={"code": "forbidden"})
        )
        page.route("**/api/v1/me", lambda route: route.fulfill(json=_cache_profile()[0]))
        page.route(
            "**/api/v1/wallet",
            lambda route: route.fulfill(
                json={
                    "balance": 115,
                    "reserved": 6,
                    "earned": 95,
                    "transfer_threshold": 50,
                    "transfers_enabled": True,
                }
            ),
        )
        page.route(
            "**/api/v1/wallet/history?*",
            lambda route: route.fulfill(
                json={
                    "items": [],
                    "next_cursor": None,
                }
            ),
        )
        page.route(
            "**/api/v1/wallet/recipients?*",
            lambda route: route.fulfill(
                json={
                    "items": [recipient],
                }
            ),
        )

        def transfer(route: Route) -> None:
            sent.append(
                {
                    "key": route.request.headers["idempotency-key"],
                    "body": route.request.post_data_json,
                }
            )
            if len(sent) == 1:
                route.abort("failed")
            else:
                route.fulfill(
                    json={
                        "recipient": recipient,
                        "amount": 15,
                        "balance_after": 100,
                        "replayed": True,
                    }
                )

        page.route("**/api/v1/wallet/transfers", transfer)
        page.goto(f"{mini_app_url}#/wallet")
        expect(page.locator("#wallet-nav")).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#screen-title")).not_to_be_visible()
        expect(page.locator(".wallet-credit-guide-row")).to_have_text(
            [
                "Заработать — Выполняй задания участников и комьюнити.",
                "Потратить — Создавай свои задания и оплачивай работу участников.",
            ]
        )
        expect(page.get_by_text("Операций пока нет.")).to_be_visible()
        page.get_by_role("button", name="Перевести кредиты", exact=True).click()
        page.get_by_label("Найти получателя").fill("masha")
        page.get_by_role("button", name="Маша · @masha").click()
        page.get_by_label("Сумма", exact=True).fill("1.5")
        page.get_by_role("button", name="Продолжить", exact=True).click()
        expect(
            page.get_by_text("Выбери получателя и укажи целую сумму в пределах баланса.")
        ).to_be_visible()
        assert not sent
        page.get_by_label("Сумма", exact=True).fill("15")
        page.get_by_role("button", name="Продолжить", exact=True).click()
        expect(page.get_by_text("0 кредитов", exact=True)).to_be_visible()
        page.get_by_role("button", name="Подтвердить перевод 15", exact=True).click()
        expect(
            page.get_by_text("Не удалось подтвердить результат. Повторная проверка безопасна.")  # noqa: RUF001
        ).to_be_visible()
        page.reload()
        page.get_by_role("button", name="Проверить и завершить перевод", exact=True).click()
        expect(page.get_by_text("Отправлено 15 кредитов", exact=True)).to_be_visible()
        assert len(sent) == 2
        assert sent[0] == sent[1]
        page.get_by_role("button", name="В кошелёк", exact=True).click()  # noqa: RUF001
        expect(page.get_by_role("button", name="Перевести кредиты", exact=True)).to_be_visible()
        page.goto(f"{mini_app_url}#/wallet/history")
        expect(page.locator("#screen-title")).to_have_text("История операций")
        page.go_back()
        expect(page.locator("#screen-title")).not_to_be_visible()
        assert not errors
        browser.close()


@pytest.mark.parametrize("width", [320, 390])
def test_notification_preferences_tiles_save_restore_and_fail_safely(
    mini_app_url: str, width: int
) -> None:
    state = {
        "tasks": False,
        "nomad": False,
        "online": False,
        "offline": False,
        "important": False,
        "task_updates": False,
        "task_reminders": False,
        "disputes": False,
        "revision": 0,
    }
    fail = False
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": width, "height": 844})
        page.route("**/api/v1/**", lambda route: route.fulfill(status=403, json={}))
        page.route("**/api/v1/me", lambda route: route.fulfill(json=_cache_profile()[0]))

        def preferences(route: Route) -> None:
            if route.request.method == "PATCH":
                if fail:
                    route.fulfill(status=409, json={"detail": "settings_changed"})
                    return
                body = route.request.post_data_json
                assert isinstance(body, dict)
                assert body["expected_revision"] == state["revision"]
                state[body["category"]] = body["enabled"]
                state["revision"] += 1
            route.fulfill(json=state)

        page.route("**/api/v1/notification-preferences", preferences)
        page.goto(mini_app_url + "#/settings")
        page.get_by_role(
            "button", name="Активности и подписки Встречи, кочевник, задания и споры"
        ).click()
        expect(page.get_by_role("checkbox", name="Новые задания", exact=True)).not_to_be_checked()
        expect(
            page.get_by_role("checkbox", name="Важные обновления чата", exact=True)
        ).not_to_be_checked()
        nomad = page.get_by_role("checkbox", name="Цифровой кочевник", exact=True)
        expect(nomad).not_to_be_checked()
        nomad.check()
        expect(page.get_by_role("status")).to_have_text("Сохранено")
        page.reload()
        expect(nomad).to_be_checked()
        assert (
            page.locator("#screen-title").evaluate("el => getComputedStyle(el).fontSize") == "18px"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        fail = True
        nomad.uncheck()
        expect(page.get_by_role("status")).to_contain_text("Настройки изменились")
        expect(nomad).to_be_checked()
        page.get_by_role("button", name="Назад", exact=True).click()
        expect(
            page.get_by_role(
                "button", name="Активности и подписки Встречи, кочевник, задания и споры"
            )
        ).to_be_visible()
        page.goto(mini_app_url + "#/settings/notifications")
        expect(nomad).to_be_checked()
        browser.close()


def test_registration_policy_requires_explicit_confirmation(mini_app_url: str) -> None:
    state = {"mode": "standard", "revision": 0}
    changes = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 320, "height": 844})
        page.route("**/api/v1/**", lambda route: route.fulfill(status=403, json={}))
        page.route("**/api/v1/me", lambda route: route.fulfill(json=_cache_profile()[0]))

        def policy(route: Route) -> None:
            if route.request.method == "PATCH":
                changes.append(route.request.post_data_json)
                state.update(mode="simplified", revision=1)
            route.fulfill(json=state)

        page.route("**/api/v1/administration/registration-policy", policy)
        page.goto(mini_app_url + "#/settings")
        expect(page.locator(".settings-list")).to_be_visible()
        page.goto(mini_app_url + "#/moderation/registration")
        page.get_by_role("radio", name="Упрощённая", exact=True).check()
        assert not changes
        page.get_by_role("button", name="Отмена", exact=True).click()
        expect(page.get_by_role("radio", name="Стандартная", exact=True)).to_be_checked()
        page.get_by_role("radio", name="Упрощённая", exact=True).check()
        page.get_by_role("button", name="Подтвердить изменение", exact=True).click()
        expect(page.get_by_role("status")).to_have_text("Сохранено")
        assert changes == [{"mode": "simplified", "confirmed": True, "expected_revision": 0}]
        page.reload()
        expect(page.get_by_role("radio", name="Упрощённая", exact=True)).to_be_checked()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


def test_wallet_guide_links_open_catalog_and_creation(mini_app_url: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 320, "height": 740})
        page.route("**/api/v1/**", lambda route: route.fulfill(status=403, json={}))
        page.route("**/api/v1/me", lambda route: route.fulfill(json=_cache_profile()[0]))
        page.route(
            "**/api/v1/wallet",
            lambda route: route.fulfill(
                json={
                    "balance": 20,
                    "reserved": 0,
                    "earned": 0,
                    "transfer_threshold": 50,
                    "transfers_enabled": False,
                }
            ),
        )
        page.route(
            "**/api/v1/wallet/history?*",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route(
            "**/api/v1/task-creation",
            lambda route: route.fulfill(
                json={
                    "categories": [],
                    "time_sizes": [],
                    "draft": None,
                    "preview": None,
                    "needs_edit": False,
                }
            ),
        )
        page.goto(f"{mini_app_url}#/wallet")
        expect(page.get_by_role("link", name="Выполняй", exact=True)).to_have_attribute(
            "href", "#/catalog?view_state=t01"
        )
        expect(page.get_by_role("link", name="Создавай", exact=True)).to_have_attribute(
            "href", "#/compose/tasks?view_state=t04b"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.get_by_role("link", name="Выполняй", exact=True).click()
        page.locator('[data-screen-id="T01"]').wait_for()
        page.go_back()
        page.get_by_role("link", name="Создавай", exact=True).click()
        page.locator('[data-screen-id="T05"]').wait_for()
        expect(page.locator("#screen-title")).to_have_text("Новое задание")
        page.go_back()
        expect(page.get_by_role("link", name="Создавай", exact=True)).to_be_visible()
        browser.close()


@pytest.mark.browser_smoke
def test_wallet_locked_deeplink_and_history_retry(mini_app_url: str) -> None:
    history_calls = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 390, "height": 844})
        page.route(
            "**/api/v1/**", lambda route: route.fulfill(status=403, json={"code": "forbidden"})
        )
        page.route("**/api/v1/me", lambda route: route.fulfill(json=_cache_profile()[0]))
        page.route(
            "**/api/v1/wallet",
            lambda route: route.fulfill(
                json={
                    "balance": 20,
                    "reserved": 2,
                    "earned": 0,
                    "transfer_threshold": 50,
                    "transfers_enabled": False,
                }
            ),
        )

        def history(route: Route) -> None:
            nonlocal history_calls
            history_calls += 1
            if history_calls == 1:
                route.fulfill(status=503, json={"code": "unavailable"})
            else:
                route.fulfill(json={"items": [], "next_cursor": None})

        page.route("**/api/v1/wallet/history?*", history)
        page.goto(f"{mini_app_url}#/wallet/transfer")
        expect(page.get_by_text("Сначала — вклад в сообщество", exact=True)).to_be_visible()
        for width in (320, 390):
            page.set_viewport_size({"width": width, "height": 844})
            expect(page.locator(".wallet-unlock-view > .wallet-tile")).to_have_count(3)
            assert (
                page.locator("#screen-title").evaluate("el => getComputedStyle(el).fontSize")
                == "18px"
            )
            assert (
                page.locator(".wallet-tile-heading").first.evaluate(
                    "el => getComputedStyle(el).fontSize"
                )
                == "15px"
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        expect(page.get_by_text("Осталось 50 кредитов", exact=True)).to_be_visible()
        expect(page.get_by_label("Найти получателя")).to_have_count(0)
        page.get_by_role("button", name="Назад", exact=True).click()
        page.get_by_role("button", name="Повторить загрузку истории", exact=True).click()
        expect(page.get_by_text("Операций пока нет.")).to_be_visible()
        expect(page.get_by_role("button", name="Перевести кредиты", exact=True)).to_be_disabled()
        expect(
            page.get_by_role("button", name="Когда откроются переводы?", exact=True)
        ).to_be_visible()
        assert (
            page.locator(".wallet-balance-card").evaluate("el => el.getBoundingClientRect().height")
            < 265
        )
        expect(page.get_by_role("button", name=re.compile("В резерве"))).to_be_visible()  # noqa: RUF001
        browser.close()


def test_wallet_recipient_search_submit_empty_and_selection_reset(mini_app_url: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 320, "height": 844})
        page.route(
            "**/api/v1/**", lambda route: route.fulfill(status=403, json={"code": "forbidden"})
        )
        page.route("**/api/v1/me", lambda route: route.fulfill(json=_cache_profile()[0]))
        page.route(
            "**/api/v1/wallet",
            lambda route: route.fulfill(json={"balance": 54, "transfers_enabled": True}),
        )
        recipient = {
            "member_id": "00000000-0000-0000-0000-000000000222",
            "display_name": "Маша",
            "telegram_username": "masha",
        }
        page.route(
            "**/api/v1/wallet/recipients?*",
            lambda route: route.fulfill(
                json={
                    "items": [recipient]
                    if parse_qs(urlsplit(route.request.url).query).get("query") == ["masha"]
                    else []
                }
            ),
        )
        page.goto(f"{mini_app_url}#/wallet/transfer")
        search_form = page.get_by_role("search", name="Поиск получателя")
        expect(search_form.get_by_role("button", name="Найти", exact=True)).to_have_count(0)
        search_form.get_by_label("Найти получателя").press("Enter")
        expect(page.get_by_text("Введи имя или @ник участника.", exact=True)).to_be_visible()
        search = page.get_by_label("Найти получателя")
        search.fill("nobody")
        search.press("Enter")
        expect(page.get_by_text("Активные участники не найдены.", exact=True)).to_be_visible()
        search.fill("masha")
        page.get_by_role("button", name="Маша · @masha", exact=True).click()
        expect(page.get_by_text("Получатель: Маша · @masha", exact=True)).to_be_visible()
        search.fill("")
        page.get_by_label("Сумма", exact=True).fill("1")
        page.get_by_role("button", name="Продолжить", exact=True).click()
        expect(page.get_by_role("alert")).to_have_text(
            "Выбери получателя и укажи целую сумму в пределах баланса."
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


def test_wallet_operation_tiles_sources_and_unavailable_task(mini_app_url: str) -> None:
    identifier = "00000000-0000-0000-0000-000000000333"
    task_id = "00000000-0000-0000-0000-000000000444"
    operation = {
        "transaction_id": identifier,
        "transaction_type": "task_reward_reserved",
        "credit_delta": -2,
        "experience_delta": 0,
        "balance_after": 18,
        "balance_reconstructed": True,
        "created_at": "2026-08-28T16:23:00Z",
        "task_id": task_id,
        "task_title": "Длинное название задания " * 8,
        "task_owned": True,
        "comment": "<img src=x onerror=alert(1)>",
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(
            "**/api/v1/**", lambda route: route.fulfill(status=403, json={"code": "forbidden"})
        )
        page.route("**/api/v1/me", lambda route: route.fulfill(json=_cache_profile()[0]))
        page.route("**/api/v1/wallet", lambda route: route.fulfill(json={"balance": 18}))
        page.route("**/api/v1/wallet/operations/*", lambda route: route.fulfill(json=operation))
        page.route(
            "**/api/v1/wallet/history?*",
            lambda route: route.fulfill(json={"items": [operation], "next_cursor": None}),
        )
        for width in (320, 390):
            page.set_viewport_size({"width": width, "height": 844})
            page.goto(f"{mini_app_url}#/wallet/operations/{identifier}")
            expect(page.locator(".wallet-operation-hero")).to_be_visible()
            assert (
                page.locator("#screen-title").evaluate("el => getComputedStyle(el).fontSize")
                == "18px"
            )
            expect(page.locator(".wallet-operation-metrics .wallet-tile")).to_have_count(2)
            expect(page.get_by_text(operation["comment"], exact=True)).to_be_visible()
            assert page.locator(".wallet-operation-detail img").count() == 0
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            link = page.get_by_role("link", name=re.compile("Задание"))
            expect(link).to_have_attribute("href", f"#/wallet/operations/{identifier}/task")
            link.click()
            expect(page.get_by_text("Задание недоступно", exact=True)).to_be_visible()
            page.get_by_role("button", name="К операции", exact=True).click()  # noqa: RUF001
            expect(page.locator(".wallet-operation-hero")).to_be_visible()
        operation.update(transaction_type="manual_credit_grant", task_id=None, comment=None)
        page.reload()
        expect(page.get_by_text("Кредиты начислены администратором.", exact=False)).to_be_visible()
        expect(page.locator(".wallet-source-link")).to_have_count(0)
        operation.update(
            transaction_type="transfer_received", counterparty_id=task_id, counterparty_name="Маша"
        )
        page.reload()
        expect(page.get_by_role("link", name=re.compile("Отправитель Маша"))).to_have_attribute(
            "href", f"#/members/{task_id}"
        )
        operation.update(reversed_transaction_id=task_id)
        page.reload()
        expect(
            page.get_by_role("link", name=re.compile("Открыть исходную операцию"))
        ).to_have_attribute("href", f"#/wallet/operations/{task_id}")
        page.goto(f"{mini_app_url}#/wallet/history")
        expect(page.locator(".wallet-operation")).to_be_visible()
        assert (
            page.locator(".wallet-operation").evaluate("el => getComputedStyle(el).borderRadius")
            == "18px"
        )
        page.locator(".wallet-operation").click()
        expect(page.locator(".wallet-operation-hero")).to_be_visible()
        assert errors == []
        browser.close()


def _connected_control(page: Any, edge_id: str, trigger: str) -> Any:  # noqa: ANN401
    control = page.locator(f'[data-transition-id="{edge_id}"][data-transition-trigger="{trigger}"]')
    control.first.wait_for()
    assert control.count() >= 1
    return control


def _choose_creation_option(
    page: Any,  # noqa: ANN401
    *,
    trigger: str,
    dialog: str,
    option: str,
) -> None:
    page.get_by_role("button", name=trigger, exact=True).click()
    sheet = page.get_by_role("dialog", name=dialog, exact=True)
    sheet.get_by_role("button", name=re.compile(rf"^{re.escape(option)},")).click()


def _fill_creation_content(
    page: Any,  # noqa: ANN401
    *,
    trigger: str,
    dialog: str,
    value: str,
) -> None:
    page.get_by_role("button", name=trigger, exact=True).click()
    sheet = page.get_by_role("dialog", name=dialog, exact=True)
    sheet.get_by_label(f"{dialog}: текст", exact=True).fill(value)
    sheet.get_by_role("button", name="Готово", exact=True).click()


def _open_blank_task_creation(page: Any, *, group: bool = False) -> None:  # noqa: ANN401
    page.locator('[data-home-action="create"]').click()
    page.locator('[data-screen-id="T04B"], [data-screen-id="T05"]').wait_for()
    recovery = page.locator('[data-screen-id="T04B"]')
    if recovery.count():
        recovery.get_by_role("button", name=re.compile("Продолжить|Редактировать")).click()
    if group:
        _choose_creation_option(
            page,
            trigger="Выбрать тип задания",
            dialog="Тип задания",
            option="Групповое",
        )


@pytest.mark.browser_smoke
def test_creation_choice_sheet_scrolls_all_categories_on_compact_viewport() -> None:
    labels = (
        "Продвижение",
        "Оценка и тестирование",
        "Коммуникация",
        "Обучение и разбор",
        "Практическая помощь",
        "Другое",
        "Развитие комьюнити",
    )
    options = "".join(
        f'<button class="creation-choice-option"><span class="creation-choice-option-icon">•</span>'
        f'<span class="creation-choice-option-copy"><strong>{label}</strong>'
        "<small>Описание категории</small></span>"
        '<span class="creation-choice-option-check"></span></button>'
        for label in labels
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 420, "height": 570})
        page.set_content(
            '<section class="task-size-backdrop">'
            '<div class="task-size-sheet creation-choice-sheet">'
            '<div class="catalog-sort-heading"><h2>Категория</h2></div>'
            f'<div class="creation-choice-options">{options}</div>'
            "</div></section>"
        )
        page.add_style_tag(path=str(STATIC_DIR / "styles.css"))
        category_options = page.locator(".creation-choice-options")
        initial = category_options.evaluate(
            "node => ({ overflowY: getComputedStyle(node).overflowY, "
            "clientHeight: node.clientHeight, scrollHeight: node.scrollHeight, "
            "containerBottom: node.getBoundingClientRect().bottom, "
            "lastBottom: node.lastElementChild.getBoundingClientRect().bottom })"
        )
        assert initial["overflowY"] == "auto"
        assert initial["scrollHeight"] > initial["clientHeight"]
        assert initial["lastBottom"] > initial["containerBottom"]
        category_options.evaluate("node => { node.scrollTop = node.scrollHeight; }")
        after_scroll = category_options.evaluate(
            "node => ({ scrollTop: node.scrollTop, "
            "containerBottom: node.getBoundingClientRect().bottom, "
            "lastBottom: node.lastElementChild.getBoundingClientRect().bottom })"
        )
        assert after_scroll["scrollTop"] > 0
        assert after_scroll["lastBottom"] <= after_scroll["containerBottom"] + 1
        browser.close()


def _cache_profile(member_id: str = "member-cache") -> tuple[dict[str, Any], dict[str, Any]]:
    me = {
        "member_id": member_id,
        "display_name": "Алекс",
        "city": "Rosario",
        "timezone": "America/Argentina/Cordoba",
        "short_bio": None,
        "current_goal": None,
        "help_categories": [],
        "skill_tags": [],
        "availability": None,
        "credit_balance": 7,
        "experience_total": 12,
        "level": {"number": 2, "display_name": "Участник"},
        "statistics": {"completed_tasks": 3, "created_tasks": 4},
    }
    member = {
        "member_id": member_id,
        "display_name": "Алекс",
        "level_number": 2,
        "karma": {"score": 5, "count": 2},
        "reliability": {"rate": "0.9"},
    }
    return me, member


def _task_home_task(task_id: str = "00000000-0000-0000-0000-000000000117") -> dict[str, Any]:
    return {
        "id": task_id,
        "origin": "community",
        "author_display_name": "Сообщество",
        "category_name": "Практическая помощь",
        "category_icon": "⭐",
        "task_kind": "solo",
        "time_size": "m",
        "title": "Проверить сценарий первого запуска с очень длинным русским названием",  # noqa: RUF001
        "credit_reward_per_performer": 4,
        "performer_slots": 1,
        "minimum_level": 1,
        "format": "online",
        "city": None,
        "created_at": "2026-08-20T12:00:00Z",
        "deadline_at": "2026-08-27T20:00:00Z",
        "status": "published",
        "description": "Проверить новый сценарий и записать результат.",
        "completion_criteria": "Сценарий проверен.",
        "performer_instructions": "Пройти шаги по порядку.",
        "materials": {},
        "public_input": {},
    }


def _task_home_payload(*, empty: bool = False, partial: bool = False) -> dict[str, Any]:
    task = _task_home_task()
    second_assignment_id = "00000000-0000-0000-0000-000000000219"
    review_assignment_id = "00000000-0000-0000-0000-000000000220"
    cancellation_assignment_id = "00000000-0000-0000-0000-000000000221"
    return {
        "attention": [
            {
                "action": "submit_result",
                "count": 2 if not empty else 0,
                "target": "taken",
                "items": []
                if empty
                else [
                    {
                        "id": task["id"],
                        "title": "Подготовить результат проверки",
                        "context": "От участника",
                        "status": "accepted",
                        "started_at": "2026-08-24T11:00:00Z",
                        "deadline_at": "2026-08-27T11:00:00Z",
                    },
                    {
                        "id": second_assignment_id,
                        "title": "Сверить итоговый сценарий",
                        "context": "Сообщество",
                        "status": "accepted",
                        "started_at": "2026-08-25T11:00:00Z",
                        "deadline_at": "2026-08-29T11:00:00Z",
                    },
                ],
            },
            {
                "action": "review_work",
                "count": 1 if not empty else 0,
                "target": "created",
                "items": []
                if empty
                else [
                    {
                        "id": review_assignment_id,
                        "title": "Проверить работу тестового участника",
                        "context": "Тестовый участник",
                        "status": "submitted",
                        "started_at": "2026-08-24T11:00:00Z",
                        "deadline_at": "2026-08-27T11:00:00Z",
                    }
                ],
            },
            {
                "action": "answer_cancellation",
                "count": 1 if not empty else 0,
                "target": "cancellations",
                "items": []
                if empty
                else [
                    {
                        "id": cancellation_assignment_id,
                        "title": "Согласовать отмену",
                        "context": "Тестовый участник",
                        "status": "cancellation_pending",
                        "started_at": "2026-08-23T11:00:00Z",
                        "deadline_at": "2026-08-30T11:00:00Z",
                    }
                ],
            },
        ],
        "waiting_on_others": [
            {
                "action": "performer_work",
                "count": 0,
                "target": "created",
            },
            {
                "action": "work_review",
                "count": 1 if not empty else 0,
                "target": "taken",
            },
            {
                "action": "external_decision",
                "count": 0,
                "target": "created",
            },
        ],
        "available_count": 6 if not empty else 0,
        "available_has_more": False,
        "can_create": True,
        "has_draft": False,
        "taken_count": 4 if not empty else 0,
        "created_count": 5 if not empty else 0,
        "active_count": 2 if not empty else 0,
        "waiting_count": 2 if not empty else 0,
        "archive_count": 18 if not empty else 0,
        "new_tasks": [] if empty else [task, {**task, "id": task["id"][:-1] + "8"}],
        "errors": ["reviews"] if partial else [],
    }


@pytest.mark.parametrize("viewport", [(375, 812), (430, 932)])
@pytest.mark.browser_smoke
def test_clean_mini_app_url_only_starts_current_runtime(
    mini_app_url: str,
    viewport: tuple[int, int],
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(
                json={"member_id": "member", "display_name": "Алекс", "timezone": "UTC"}
            ),
        )
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload(empty=True)),
        )
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )

        page.goto(mini_app_url + "#/tasks")
        page.locator('[data-screen-id="UX02"][data-ui-engine="next-tasks-home"]').wait_for()
        assert page.locator('[data-screen-id="UX01"]').count() == 0
        assert page.evaluate("document.documentElement.dataset.uiThemeScope") == "next"
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        browser.close()


@pytest.mark.browser_smoke
def test_membership_gate_shows_required_chat_in_mobile_ui(mini_app_url: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 375, "height": 812})
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(
                status=403,
                json={
                    "code": "membership_required",
                    "resources": [
                        {
                            "resource_id": None,
                            "title": "Алло, Нейросеточная?",
                            "join_url": "https://t.me/allo_neural",
                            "required": True,
                            "joined": False,
                        }
                    ],
                },
            ),
        )

        page.goto(mini_app_url + "?ui=next&theme=light")
        page.get_by_role("heading", name="Вступите в сообщество").wait_for()
        page.get_by_text("Алло, Нейросеточная?", exact=True).wait_for()
        assert page.get_by_role("button", name="Открыть").count() == 1
        assert page.get_by_role("button", name="Проверить").count() == 1
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


@pytest.mark.parametrize("viewport", [(375, 812), (430, 932)])
def test_administrator_management_flow_matches_mobile_prototype(  # noqa: C901, PLR0915
    mini_app_url: str, viewport: tuple[int, int]
) -> None:
    owner_id = "00000000-0000-0000-0000-000000000201"
    manager_id = "00000000-0000-0000-0000-000000000202"
    candidate_id = "00000000-0000-0000-0000-000000000203"
    owner = {
        "member_id": owner_id,
        "telegram_username": "alexclem",
        "display_name": "Alex Clem",
        "permissions": [
            "interaction_review",
            "member_invitation",
            "member_blocking",
            "administrator_management",
            "community_task_create",
            "community_task_review",
        ],
        "is_owner": True,
        "appointed_by": None,
        "appointed_at": None,
        "can_edit": False,
        "can_demote": False,
    }
    manager = {
        "member_id": manager_id,
        "telegram_username": "schoonia",
        "display_name": "Schoonia",
        "permissions": ["interaction_review", "member_invitation"],
        "is_owner": False,
        "appointed_by": {
            "member_id": owner_id,
            "telegram_username": "alexclem",
            "display_name": "Alex Clem",
        },
        "appointed_at": "2026-05-21T07:58:00Z",
        "can_edit": True,
        "can_demote": True,
    }
    candidate = {
        "member_id": candidate_id,
        "telegram_username": "kristina_flowers",
        "display_name": "Kristina 🌼",
    }
    administrators: list[dict[str, Any]] = [owner, manager]
    mutations: list[dict[str, Any]] = []
    invitation_mutations: list[dict[str, Any]] = []
    invitations: list[dict[str, Any]] = []
    invitation_failures = [503, 403]
    optional_resource_id = "00000000-0000-0000-0000-000000000205"
    avatar_requests: list[str] = []

    def avatar_route(route: Route) -> None:
        avatar_requests.append(urlsplit(route.request.url).path)
        route.fulfill(
            body='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"/>',
            content_type="image/svg+xml",
        )

    def administration_route(route: Route) -> None:  # noqa: C901, PLR0911
        path = urlsplit(route.request.url).path
        method = route.request.method
        if path == "/api/v1/administration" and method == "GET":
            route.fulfill(
                json={
                    "items": administrators,
                    "actor_permissions": owner["permissions"],
                    "can_appoint": True,
                    "can_delegate_administrator_management": True,
                }
            )
            return
        if path == "/api/v1/administration/candidates" and method == "GET":
            route.fulfill(json={"items": [candidate]})
            return
        if path == "/api/v1/administration/membership-resources" and method == "GET":
            route.fulfill(
                json={
                    "items": [
                        {
                            "resource_id": None,
                            "title": "Алло, Нейросеточная?",
                            "join_url": "https://t.me/allo_neural",
                            "required": True,
                            "joined": None,
                        },
                        {
                            "resource_id": optional_resource_id,
                            "title": "Партнёрский канал",
                            "join_url": "https://t.me/partner_channel",
                            "required": False,
                            "joined": None,
                        },
                    ],
                    "can_add": True,
                }
            )
            return
        if path == "/api/v1/administration/invitations" and method == "GET":
            route.fulfill(
                json={
                    "items": invitations,
                    "pending_count": sum(item["status"] == "waiting" for item in invitations),
                }
            )
            return
        if path == "/api/v1/administration/invitations" and method == "POST":
            if invitation_failures:
                route.fulfill(
                    status=invitation_failures.pop(0),
                    json={"code": "invitation_unavailable"},
                )
                return
            body = route.request.post_data_json
            assert body is not None
            invitation_mutations.append({"method": method, "path": path, "body": body})
            invitation = {
                "invitation_id": "00000000-0000-0000-0000-000000000204",
                "telegram_username": body["telegram_username"].removeprefix("@").lower(),
                "created_by_display_name": "Alex Clem",
                "status": "waiting",
                "created_at": "2026-08-28T12:00:00Z",
                "expires_at": "2026-09-04T12:00:00Z",
                "redeemed_at": None,
                "redeemed_member_id": None,
                "redeemed_display_name": None,
            }
            invitations.insert(0, invitation)
            route.fulfill(
                status=201,
                json={
                    "invitation_id": invitation["invitation_id"],
                    "telegram_username": invitation["telegram_username"],
                    "expires_at": invitation["expires_at"],
                    "invitation_url": "https://t.me/community_test_bot?startapp=secret",
                },
            )
            return
        if path.endswith("/revoke") and "/administration/invitations/" in path:
            invitations[0]["status"] = "revoked"
            route.fulfill(status=204)
            return
        member_id = path.removeprefix("/api/v1/administration/").removesuffix("/demote")
        person = next((item for item in administrators if item["member_id"] == member_id), None)
        if method == "GET" and person is not None:
            route.fulfill(json=person)
            return
        body = route.request.post_data_json
        assert body is not None
        mutations.append({"method": method, "path": path, "body": body})
        if path.endswith("/demote"):
            administrators[:] = [item for item in administrators if item["member_id"] != member_id]
            route.fulfill(
                json={
                    key: manager[key] for key in ("member_id", "telegram_username", "display_name")
                }
            )
            return
        if method == "POST":
            created = {
                **candidate,
                "permissions": body["permissions"],
                "is_owner": False,
                "appointed_by": {
                    key: owner[key] for key in ("member_id", "telegram_username", "display_name")
                },
                "appointed_at": "2026-08-27T12:00:00Z",
                "can_edit": True,
                "can_demote": True,
            }
            administrators.append(created)
            route.fulfill(status=201, json=created)
            return
        if method == "PUT" and person is not None:
            person["permissions"] = body["permissions"]
            route.fulfill(json=person)
            return
        route.fulfill(status=404, json={"code": "not_found"})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]})
        page = _new_page(context)
        me, _member = _cache_profile(owner_id)
        page.route("**/api/v1/me", lambda route: route.fulfill(json=me))
        page.route("**/api/v1/administration**", administration_route)
        page.route("**/api/v1/members/*/avatar", avatar_route)
        page.goto(mini_app_url + "?ui=next&theme=light#/moderation/team")

        page.get_by_role("heading", name="Команда").wait_for()
        page.locator(".admin-list .person-avatar-photo").nth(1).wait_for()
        assert page.get_by_text("Alex Clem").count() >= 1
        assert page.get_by_text("Владелец", exact=True).count() == 1
        assert sorted(avatar_requests) == sorted(
            [
                f"/api/v1/members/{owner_id}/avatar",
                f"/api/v1/members/{manager_id}/avatar",
            ]
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

        page.get_by_role("button", name="+ Пригласить участника").click()
        page.get_by_text("Алло, Нейросеточная?", exact=True).wait_for()
        assert page.get_by_role("button", name="+ Добавить ресурс").count() == 1  # noqa: RUF001
        resource_row = page.locator(".admin-invitation-condition").filter(
            has_text="Партнёрский канал"
        )
        resource_row.get_by_role("checkbox").check()
        page.get_by_placeholder("username или @username").fill("Marina_Orlova")
        page.get_by_role("button", name="Создать ссылку").click()
        page.get_by_text("Приглашения временно недоступны. Попробуйте позже.").wait_for()
        page.get_by_role("button", name="Создать ссылку").click()
        page.get_by_text("У вас нет права приглашать участников.").wait_for()  # noqa: RUF001
        page.get_by_role("button", name="Создать ссылку").click()
        page.get_by_role("heading", name="Приглашение готово").wait_for()
        page.get_by_text("@marina_orlova", exact=True).wait_for()
        assert invitation_mutations[0]["body"] == {
            "telegram_username": "Marina_Orlova",
            "required_resource_ids": [optional_resource_id],
        }
        page.evaluate(
            "globalThis.sentInvitationLinks=[];"
            "globalThis.Telegram={WebApp:{"
            "openTelegramLink:(url)=>sentInvitationLinks.push(url)}}"
        )
        page.get_by_role("button", name="Написать @marina_orlova").click()
        assert page.evaluate("sentInvitationLinks.at(-1)").startswith(
            "https://t.me/marina_orlova?text="
        )
        page.get_by_role("button", name="Все приглашения").click()  # noqa: RUF001
        page.get_by_role("heading", name="Приглашения", exact=True).wait_for()
        assert page.get_by_role("button", name="+ Пригласить", exact=True).count() == 0
        assert page.get_by_text("Кто получил ссылку и что произошло", exact=True).count() == 0
        page.get_by_text("Ожидает", exact=True).wait_for()
        page.get_by_role("button", name="Отозвать", exact=True).click()
        revoke_dialog = page.get_by_role("dialog")
        revoke_dialog.get_by_role("button", name="Отозвать", exact=True).click()
        page.get_by_text("Приглашение отозвано").wait_for()
        page.get_by_text("Отозвано", exact=True).wait_for()
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Приглашение готово").wait_for()
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Команда").wait_for()

        page.get_by_role("button", name="+ Назначить администратора").click()
        page.get_by_placeholder("Имя или @username").fill("Kristina")
        page.get_by_role("button", name=re.compile("Kristina")).click()
        page.locator('[data-permission="member_invitation"]').check(force=True)
        page.locator('[data-permission="administrator_management"]').check(force=True)
        page.get_by_role("button", name="Назначить администратором").click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_text("повышенным").wait_for()
        dialog.get_by_role("button", name="Назначить", exact=True).click()
        page.get_by_text("Kristina 🌼 назначен администратором").wait_for()
        assert mutations[0]["body"]["permissions"] == [
            "member_invitation",
            "administrator_management",
        ]
        assert page.url.endswith("#/moderation/team")

        page.get_by_role("button", name=re.compile("Kristina")).click()
        page.get_by_role("heading", name="Права", exact=True).wait_for()
        assert page.locator('[data-permission="community_task_create"]').count() == 1
        assert page.locator('[data-permission="community_task_review"]').count() == 1
        page.locator(".admin-profile-card .person-avatar-photo").wait_for()
        assert avatar_requests.count(f"/api/v1/members/{candidate_id}/avatar") == 1
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Команда").wait_for()
        assert page.url.endswith("#/moderation/team")

        page.get_by_role("button", name=re.compile("Schoonia")).click()
        page.get_by_text("Назначил Alex Clem").wait_for()
        page.get_by_role("button", name="Снять права администратора").click()
        demotion = page.get_by_role("dialog")
        demotion.get_by_label("Причина").fill("Изменение зоны ответственности")
        demotion.get_by_role("button", name="Снять права", exact=True).click()
        page.get_by_text("Права администратора сняты").wait_for()
        assert mutations[-1]["body"] == {"reason": "Изменение зоны ответственности"}

        page.get_by_role("button", name=re.compile("Alex Clem")).click()
        page.get_by_role("heading", name="Права", exact=True).wait_for()
        page.locator(".admin-profile-card .person-avatar-photo").wait_for()
        assert avatar_requests.count(f"/api/v1/members/{owner_id}/avatar") == 1
        page.get_by_text("изменить или снять их нельзя").wait_for()
        assert page.locator("[data-permission]:disabled").count() == 6
        assert page.get_by_role("button", name="Снять права администратора").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        context.close()
        browser.close()


def test_community_task_review_queue_supports_authorized_decision(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    owner_id = "00000000-0000-0000-0000-000000000206"
    assignment_id = "00000000-0000-0000-0000-000000000207"
    performer_id = "00000000-0000-0000-0000-000000000209"
    review = {
        "id": assignment_id,
        "task_id": "00000000-0000-0000-0000-000000000208",
        "task_title": "Подготовить программу встречи",
        "performer_id": performer_id,
        "performer_display_name": "Марина",
        "submitted_at": "2026-08-29T12:00:00Z",
        "review_deadline_at": "2026-09-01T12:00:00Z",
        "result": "Программа встречи, темы и ответственные готовы.",
        "available_decisions": ["full", "partial", "reject"],
    }
    pending = {"value": True}
    decisions: list[dict[str, object]] = []

    def community_reviews(route: Route) -> None:
        path = urlsplit(route.request.url).path
        if path == "/api/v1/moderation/community-reviews":
            route.fulfill(json={"items": [review] if pending["value"] else []})
            return
        if path == f"/api/v1/moderation/community-reviews/{assignment_id}":
            route.fulfill(json=review)
            return
        route.fulfill(status=404, json={"code": "not_found"})

    def decide(route: Route) -> None:
        body = route.request.post_data_json
        assert body is not None
        decisions.append(body)
        pending["value"] = False
        route.fulfill(status=204)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = _new_page(context)
        me, _member = _cache_profile(owner_id)
        _, performer = _cache_profile(performer_id)
        performer["display_name"] = "Марина"
        page.route("**/api/v1/me", lambda route: route.fulfill(json=me))
        page.route(
            f"**/api/v1/members/{performer_id}",
            lambda route: route.fulfill(json=performer),
        )
        page.route(
            "**/api/v1/community-stats/pulse?*",
            lambda route: route.fulfill(status=503, json={"code": "unavailable"}),
        )
        page.route(
            "**/api/v1/administration",
            lambda route: route.fulfill(
                json={
                    "items": [],
                    "actor_permissions": ["community_task_review"],
                    "can_appoint": False,
                    "can_delegate_administrator_management": False,
                    "can_grant_credits": False,
                }
            ),
        )
        page.route("**/api/v1/moderation/community-reviews**", community_reviews)
        page.route(
            f"**/api/v1/assignment-reviews/{assignment_id}/decision",
            decide,
        )
        page.goto(mini_app_url + "#/moderation/community-reviews")

        page.get_by_role("heading", name="Задания сообщества").wait_for()
        page.get_by_role("button", name="Проверка", exact=True).wait_for()
        page.get_by_role("button", name=re.compile("Подготовить программу встречи")).click()
        page.get_by_text("Программа встречи, темы и ответственные готовы.", exact=True).wait_for()
        performer_link = page.get_by_role(
            "button", name="Открыть профиль исполнителя Марина", exact=True
        )
        assert performer_link.is_visible()
        performer_link.click()
        page.locator(".foreign-profile").wait_for()
        assert page.url.endswith(f"#/members/{performer_id}")
        page.go_back()
        page.get_by_role("heading", name="Подготовить программу встречи", exact=True).wait_for()
        page.get_by_role("button", name="Принять полностью", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_role("button", name="Принять полностью", exact=True).click()

        page.get_by_text("Заданий на проверку нет", exact=True).wait_for()
        assert decisions == [{"decision": "full"}]
        assert page.url.endswith("#/moderation/community-reviews")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        context.close()
        browser.close()


@pytest.mark.browser_smoke
def test_superadministrator_credit_grant_searches_inline_before_confirmation(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    owner_id = "00000000-0000-0000-0000-000000000301"
    recipient_id = "00000000-0000-0000-0000-000000000302"
    owner = {
        "member_id": owner_id,
        "telegram_username": "alex_owner",
        "display_name": "Алексей Окситоцин",
        "status": "active",
        "credit_balance": 240,
    }
    recipient = {
        "member_id": recipient_id,
        "telegram_username": "annapetrova",
        "display_name": "Анна Петрова",
        "status": "active",
        "credit_balance": 8,
    }
    mutations: list[dict[str, Any]] = []

    def administration_route(route: Route) -> None:
        url = urlsplit(route.request.url)
        path = url.path
        if path == "/api/v1/administration":
            route.fulfill(
                json={
                    "items": [],
                    "actor_permissions": [],
                    "can_appoint": True,
                    "can_delegate_administrator_management": True,
                    "can_grant_credits": True,
                }
            )
        elif path == "/api/v1/administration/credits/self":
            route.fulfill(json=owner)
        elif path == "/api/v1/administration/credits/recipients":
            assert parse_qs(url.query)["query"] == ["Анна"]
            route.fulfill(json={"items": [recipient]})
        elif path == f"/api/v1/administration/credits/recipients/{recipient_id}":
            route.fulfill(json=recipient)
        elif path == "/api/v1/administration/credits/grants":
            body = route.request.post_data_json
            assert body is not None
            mutations.append(body)
            route.fulfill(
                status=201,
                json={
                    "transaction_id": "00000000-0000-0000-0000-000000000303",
                    "recipient": {**recipient, "credit_balance": 33},
                    "amount": body["amount"],
                    "reason": body["reason"],
                    "replayed": False,
                },
            )
        elif path == "/api/v1/administration/credits/history":
            route.fulfill(json={"items": [], "next_cursor": None})
        else:
            route.fulfill(status=404, json={"code": "not_found"})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = _new_page(context)
        me, _member = _cache_profile(owner_id)
        page.route("**/api/v1/me", lambda route: route.fulfill(json=me))
        page.route("**/api/v1/administration**", administration_route)
        page.goto(mini_app_url + "?ui=next&theme=light#/moderation/credits")

        page.get_by_role("heading", name="Кому начислить").wait_for()
        assert page.get_by_text("Алексей Окситоцин", exact=True).count() == 1
        assert page.get_by_text("Анна Петрова", exact=True).count() == 0
        page.get_by_role("button", name="История", exact=True).click()
        page.get_by_role("heading", name="История начислений").wait_for()
        page.get_by_text("Начислений пока нет.").wait_for()
        assert (
            float(
                page.locator("#screen-title").evaluate("node => getComputedStyle(node).fontSize")[
                    :-2
                ]
            )
            == 22
        )
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Кому начислить").wait_for()
        page.get_by_placeholder("Имя или @username").fill("Анна")
        assert page.url.endswith("#/moderation/credits")
        page.get_by_role("button", name=re.compile("Анна Петрова")).wait_for()
        page.get_by_role("button", name=re.compile("Анна Петрова")).click()

        assert (
            float(
                page.locator("#screen-title").evaluate("node => getComputedStyle(node).fontSize")[
                    :-2
                ]
            )
            == 22
        )
        page.get_by_label("Сколько кредитов").fill("25")
        page.get_by_label("Причина начисления").fill("Компенсация за техническую ошибку")
        page.get_by_role("button", name="Продолжить").click()
        page.get_by_role("heading", name="Подтверждение").wait_for()
        assert (
            float(
                page.locator("#screen-title").evaluate("node => getComputedStyle(node).fontSize")[
                    :-2
                ]
            )
            == 22
        )
        page.get_by_text("+25 кредитов", exact=True).wait_for()
        page.get_by_role("button", name="Начислить кредиты").click()
        page.get_by_role("heading", name="Начислено 25 кредитов").wait_for()
        page.get_by_text("33 кредитов на балансе", exact=True).wait_for()
        assert mutations == [
            {
                "target_member_id": recipient_id,
                "amount": 25,
                "reason": "Компенсация за техническую ошибку",
            }
        ]
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        context.close()
        browser.close()


@pytest.mark.browser_smoke
def test_bootstrap_waits_for_late_telegram_desktop_init_data(
    mini_app_url: str,
) -> None:
    """The single Mini App runtime tolerates late Telegram Desktop initData."""
    init_data = "query_id=desktop&user=%7B%22id%22%3A1%7D&hash=proof"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(
            browser,
            bridge=(
                "globalThis.Telegram = {WebApp: {}};"
                "setTimeout(() => { globalThis.Telegram.WebApp.initData = "
                f'"{init_data}"; }}, 150);'
            ),
        )
        calls = 0

        def me(route: Route) -> None:
            nonlocal calls
            calls += 1
            route.fulfill(
                status=401 if calls == 1 else 200,
                json={"member_id": "desktop", "display_name": "Алекс"},
            )

        page.route("**/api/v1/me", me)
        page.route("**/api/v1/auth/telegram", lambda route: route.fulfill(status=204))
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload(empty=True)),
        )
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload(empty=True)),
        )
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )

        page.goto(mini_app_url)
        page.locator('[data-screen-id="UX02"][data-ui-engine="next-tasks-home"]').wait_for()
        assert page.locator('[data-screen-id="UX01"]').count() == 0
        assert calls == 2
        browser.close()


def test_ui_next_system_theme_tracks_telegram_and_syncs_chrome(mini_app_url: str) -> None:
    bridge = """
    globalThis.themeHandlers = {};
    globalThis.telegramChrome = [];
    globalThis.Telegram = {WebApp: {
      colorScheme: 'dark', ready() {}, expand() {},
      onEvent(name, callback) { globalThis.themeHandlers[name] = callback; },
      offEvent(name) { delete globalThis.themeHandlers[name]; },
      setHeaderColor(color) { globalThis.telegramChrome.push(['header', color]); },
      setBackgroundColor(color) { globalThis.telegramChrome.push(['background', color]); },
      setBottomBarColor(color) { globalThis.telegramChrome.push(['bottom', color]); },
    }};
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser, bridge=bridge)
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(
                json={"member_id": "member", "display_name": "Алекс", "timezone": "UTC"}
            ),
        )
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload(empty=True)),
        )
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )
        page.goto(mini_app_url + "?theme=system#/tasks")
        page.locator('[data-screen-id="UX02"][data-ui-engine="next-tasks-home"]').wait_for()
        assert page.evaluate("document.documentElement.dataset.themePreference") == "system"
        assert page.evaluate("document.documentElement.dataset.themePreset") == "acid"
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        assert page.evaluate("typeof globalThis.themeHandlers.themeChanged") == "function"

        page.evaluate(
            """() => {
              Telegram.WebApp.colorScheme = 'light';
              globalThis.themeHandlers.themeChanged();
            }"""
        )
        assert page.evaluate("document.documentElement.dataset.theme") == "light"
        assert page.evaluate("globalThis.telegramChrome.slice(-3)") == [
            ["header", "#f4f7ed"],
            ["background", "#f4f7ed"],
            ["bottom", "#ffffff"],
        ]
        browser.close()


@pytest.mark.browser_smoke
def test_ui_next_onboarding_starts_light_and_confirms_catalog_city(mini_app_url: str) -> None:
    view: dict[str, Any] = {
        "outcome": "registration_step:city",
        "application_status": "draft",
        "step": "city",
        "payload": {"consent": True, "display_name": "Новый участник"},
        "review_comment": None,
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 390, "height": 844})
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(status=403, json={"code": "profile_unavailable"}),
        )
        page.route("**/api/v1/onboarding", lambda route: route.fulfill(json=view))
        page.route(
            "**/api/v1/onboarding/answer",
            lambda route: route.fulfill(
                json={
                    **view,
                    "outcome": "registration_step:short_bio",
                    "step": "short_bio",
                    "payload": {
                        **view["payload"],
                        "city": "Buenos Aires — Argentina",
                        "timezone": "America/Argentina/Buenos_Aires",
                    },
                }
            ),
        )
        page.route(
            "**/api/v1/onboarding/back",
            lambda route: route.fulfill(
                json={
                    **view,
                    "payload": {
                        **view["payload"],
                        "city": "Buenos Aires — Argentina",
                        "timezone": "America/Argentina/Buenos_Aires",
                    },
                }
            ),
        )
        page.route(
            "**/api/v1/task-cities?*",
            lambda route: route.fulfill(
                json={
                    "items": [
                        {
                            "value": "Buenos Aires — Argentina",
                            "label": "Buenos Aires — Argentina",
                            "timezone": "America/Argentina/Buenos_Aires",
                        }
                    ]
                }
            ),
        )

        page.goto(mini_app_url + "?theme=dark#/tasks")
        page.get_by_role(
            "heading",
            name="В каком городе вы живёте?",  # noqa: RUF001
            exact=True,
        ).wait_for()
        assert page.url.endswith("#/onboarding")
        assert "preset=neon" in page.url
        assert "theme=light" in page.url
        assert page.evaluate("document.documentElement.dataset.themePreset") == "neon"
        assert page.evaluate("document.documentElement.dataset.theme") == "light"
        assert page.get_by_role("button", name="Предыдущий шаг", exact=True).is_visible()
        assert page.locator(".bottom-nav").is_hidden()
        assert page.get_by_role("dialog").count() == 0
        city_search = page.get_by_label("Город *", exact=True)
        city_search.fill("Buenos Aires")
        city = page.locator(".city-sheet-option")
        city.wait_for()
        assert city.get_by_text("Buenos Aires — Argentina", exact=True).is_visible()
        assert city.get_by_text(re.compile(r"^UTC.03:00$"), exact=True).is_visible()
        proceed = page.get_by_role("button", name="Продолжить", exact=True)
        assert proceed.is_disabled()
        city.click()
        assert page.get_by_role("dialog").count() == 0
        assert page.locator(".onboarding-city-results").is_hidden()
        assert not proceed.is_disabled()
        assert page.get_by_text(re.compile(r"^Выбран: Buenos Aires"), exact=False).is_visible()
        proceed.click()
        page.get_by_role(
            "heading",
            name="Расскажите о себе",  # noqa: RUF001
            exact=True,
        ).wait_for()
        short_bio = page.locator('textarea[name="short_bio"]')
        assert not short_bio.evaluate("node => node.required")
        placeholder_style = short_bio.evaluate(
            """node => {
              const field = getComputedStyle(node);
              const placeholder = getComputedStyle(node, '::placeholder');
              return {
                background: field.backgroundColor,
                text: field.color,
                placeholder: placeholder.color,
                placeholderFill: placeholder.webkitTextFillColor,
              };
            }"""
        )
        assert placeholder_style["placeholderFill"] == placeholder_style["placeholder"]
        assert placeholder_style["placeholder"] != placeholder_style["text"]
        assert page.get_by_role("button", name="Заполнить позже", exact=True).is_visible()
        page.get_by_role("button", name="Предыдущий шаг", exact=True).click()
        page.get_by_role(
            "heading",
            name="В каком городе вы живёте?",  # noqa: RUF001
            exact=True,
        ).wait_for()
        assert page.get_by_label("Город *", exact=True).input_value() == (
            "Buenos Aires — Argentina"
        )
        assert not page.get_by_role("button", name="Продолжить", exact=True).is_disabled()
        browser.close()


@pytest.mark.browser_smoke
def test_personal_invitation_finishes_without_moderation_wait(mini_app_url: str) -> None:
    preview = {
        "outcome": "registration_step:preview",
        "application_status": "draft",
        "step": "preview",
        "payload": {
            "consent": True,
            "display_name": "Новый участник",
            "city": "Buenos Aires — Argentina",
            "timezone": "America/Argentina/Buenos_Aires",
            "short_bio": "",
            "skill_tags": [],
        },
        "review_comment": None,
        "personal_invitation": True,
    }
    approved = {
        **preview,
        "outcome": "registration_approved",
        "application_status": "approved",
        "step": "submitted",
        "payload": {},
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 390, "height": 844})
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(status=403, json={"code": "profile_unavailable"}),
        )
        page.route("**/api/v1/onboarding", lambda route: route.fulfill(json=preview))
        page.route("**/api/v1/onboarding/submit", lambda route: route.fulfill(json=approved))

        page.goto(mini_app_url + "?theme=light#/onboarding")
        page.get_by_text("После подтверждения вы сразу станете участником Комьюнити.").wait_for()
        page.get_by_role("button", name="Вступить в Комьюнити", exact=True).click()
        page.get_by_role("heading", name="Вы в Комьюнити", exact=True).wait_for()
        assert page.get_by_text("Ждём решение модератора").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


@pytest.mark.parametrize("viewport", [(375, 812), (430, 932)])
def test_ui_next_settings_opens_profile_and_selects_theme(  # noqa: PLR0915
    mini_app_url: str,
    viewport: tuple[int, int],
) -> None:
    me, member = _cache_profile()
    me["skill_tags"] = ["Python"]
    timezone_label = f"UTC{chr(0x2212)}03:00"
    task = _task_home_task()
    selectors = [
        ".settings-list",
        ".settings-link-row",
        ".settings-theme-row",
        ".settings-fullscreen-row",
    ]
    profile_mutations: list[dict[str, Any]] = []

    def update_profile(route: Route) -> None:
        body = route.request.post_data_json
        assert isinstance(body, dict)
        profile_mutations.append(body)
        me[body["field"]] = body["value"]
        if body["field"] == "city":
            me["timezone"] = "America/Argentina/Cordoba" if body["value"] else "UTC"
        route.fulfill(json=me)

    def boxes(page: Page) -> dict[str, dict[str, float]]:
        return page.evaluate(
            """selectors => Object.fromEntries(selectors.map(selector => {
              const rect = document.querySelector(selector).getBoundingClientRect();
              return [selector, Object.fromEntries(
                ['x', 'y', 'width', 'height'].map(key => [key, Math.round(rect[key] * 100) / 100])
              )];
            }))""",
            selectors,
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(
            browser,
            bridge="""
            globalThis.fullscreenCalls = [];
            globalThis.Telegram = {WebApp: {
              isFullscreen: false,
              ready() {}, expand() {},
              requestFullscreen() {
                this.isFullscreen = true;
                globalThis.fullscreenCalls.push('enter');
              },
              exitFullscreen() {
                this.isFullscreen = false;
                globalThis.fullscreenCalls.push('exit');
              }
            }};
            """,
        )
        page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
        page.route("**/api/v1/me", lambda route: route.fulfill(json=me))
        page.route("**/api/v1/me/profile", update_profile)
        page.route(
            "**/api/v1/task-cities?*",
            lambda route: route.fulfill(
                json={
                    "items": [
                        {
                            "value": "Rosario — Argentina",
                            "label": "Rosario — Argentina",
                            "timezone": "America/Argentina/Cordoba",
                        }
                    ]
                }
            ),
        )
        page.route(
            f"**/api/v1/members/{me['member_id']}",
            lambda route: route.fulfill(json=member),
        )
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [task], "next_cursor": None}),
        )
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload()),
        )

        page.goto(mini_app_url + "?theme=light&preset=neon#/settings")
        page.locator(".settings-list").wait_for()
        assert page.locator("#screen-title").is_hidden()
        assert page.locator(".screen").get_attribute("aria-label") == "Параметры"
        settings_nav = page.get_by_role("button", name="Параметры", exact=True)
        assert settings_nav.get_attribute("aria-pressed") == "true"
        assert page.evaluate("location.hash") == "#/settings"
        assert page.get_by_role("button", name="Профиль", exact=False).is_visible()
        theme_trigger = page.get_by_role("button", name=re.compile(r"^Оформление"))
        assert "Неон · Светлый" in theme_trigger.inner_text()
        fullscreen_toggle = page.get_by_role("switch", name="Полноэкранный режим", exact=True)
        assert fullscreen_toggle.get_attribute("aria-checked") == "true"
        assert page.evaluate("globalThis.fullscreenCalls") == ["enter"]
        light_boxes = boxes(page)

        fullscreen_toggle.click()
        assert fullscreen_toggle.get_attribute("aria-checked") == "false"
        assert page.evaluate("localStorage.getItem('community_bot_fullscreen_enabled')") == "false"
        assert page.evaluate("globalThis.fullscreenCalls") == ["enter", "exit"]

        theme_trigger.click()
        theme_dialog = page.get_by_role("dialog", name="Оформление", exact=True)
        theme_dialog.wait_for()
        acid = theme_dialog.get_by_role("radio", name="Яблоко", exact=True)
        neon = theme_dialog.get_by_role("radio", name="Неон", exact=True)
        system_mode = theme_dialog.get_by_role("radio", name="Как в Telegram", exact=True)
        light_mode = theme_dialog.get_by_role("radio", name="Светлый", exact=True)
        dark_mode = theme_dialog.get_by_role("radio", name="Тёмный", exact=True)
        assert neon.get_attribute("aria-checked") == "true"
        assert light_mode.get_attribute("aria-checked") == "true"
        assert system_mode.get_attribute("aria-checked") == "false"

        acid.click()
        assert page.evaluate("document.documentElement.dataset.themePreset") == "acid"
        assert page.evaluate("document.documentElement.dataset.theme") == "light"
        assert page.evaluate("localStorage.getItem('community_bot_ui_theme_preset')") == "acid"
        assert "preset=acid" in page.url
        assert acid.get_attribute("aria-checked") == "true"

        dark_mode.click()
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        assert page.evaluate("document.documentElement.dataset.themePreference") == "dark"
        assert page.evaluate("localStorage.getItem('community_bot_ui_theme')") == "dark"
        assert dark_mode.get_attribute("aria-checked") == "true"

        neon.click()
        assert page.evaluate("document.documentElement.dataset.themePreset") == "neon"
        assert page.evaluate("localStorage.getItem('community_bot_ui_theme_preset')") == "neon"
        assert page.evaluate("location.hash") == "#/settings"
        assert "theme=dark" in page.url
        assert "preset=neon" in page.url
        theme_dialog.get_by_role("button", name="Закрыть выбор оформления", exact=True).click()
        assert theme_trigger.evaluate("node => node === document.activeElement")
        assert "Неон · Тёмный" in theme_trigger.inner_text()
        assert boxes(page) == light_boxes

        page.reload()
        page.locator(".settings-list").wait_for()
        assert page.locator("#screen-title").is_hidden()
        assert page.locator(".screen").get_attribute("aria-label") == "Параметры"
        assert page.evaluate("document.documentElement.dataset.themePreset") == "neon"
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        assert (
            "Неон · Тёмный"
            in page.get_by_role("button", name=re.compile(r"^Оформление")).inner_text()
        )
        assert (
            page.get_by_role("switch", name="Полноэкранный режим", exact=True).get_attribute(
                "aria-checked"
            )
            == "false"
        )
        assert page.evaluate("globalThis.fullscreenCalls") == []
        page.get_by_role("button", name="Профиль", exact=False).click()
        page.locator(".profile-overview").wait_for()
        assert page.url.endswith("#/profile")
        assert page.locator(".profile-timezone").inner_text() == timezone_label
        assert settings_nav.get_attribute("aria-pressed") == "true"
        profile_back = page.get_by_role("button", name="Назад в параметры", exact=True)
        assert profile_back.inner_text() == "\u2039"
        assert profile_back.get_attribute("data-navigation-kind") == "back"
        assert page.locator("#screen-title").is_hidden()
        profile_back_box = profile_back.bounding_box()
        assert profile_back_box is not None
        assert (profile_back_box["width"], profile_back_box["height"]) == (36, 36)
        profile_back.click()
        page.locator(".settings-list").wait_for()
        assert page.locator("#screen-title").is_hidden()
        assert page.locator(".screen").get_attribute("aria-label") == "Параметры"
        assert page.url.endswith("#/settings")

        page.get_by_role("button", name="Профиль", exact=False).click()
        page.locator(".profile-overview").wait_for()
        assert page.locator(".profile-pencil").count() == 0
        editors = (
            ("Изменить имя", "Имя"),
            ("Изменить город", "Город"),
            ("Изменить о себе", "О себе"),  # noqa: RUF001
            ("Изменить навыки", "Навыки"),
            ("Изменить ссылки", "Ссылки"),
        )
        for trigger_label, dialog_label in editors:
            page.get_by_role("button", name=trigger_label, exact=True).click()
            editor_dialog = page.get_by_role("dialog", name=dialog_label, exact=True)
            editor_dialog.wait_for()
            assert page.url.endswith("#/profile")
            assert page.locator(".profile-editor-backdrop").is_visible()
            assert (
                page.locator('[data-navigation-kind="back"]').get_attribute("aria-label")
                == "Назад в параметры"
            )
            editor_dialog.get_by_role("button", name="Закрыть редактор", exact=True).click()
            page.locator(".profile-overview").wait_for()
        page.get_by_role("button", name="Изменить навыки", exact=True).click()
        skills_dialog = page.get_by_role("dialog", name="Навыки", exact=True)
        assert skills_dialog.get_by_role("button", name="Добавить навык").inner_text() == (
            "Добавить"
        )
        remove_skill = skills_dialog.get_by_role("button", name=re.compile("Удалить навык")).first
        remove_box = remove_skill.bounding_box()
        assert remove_box is not None
        assert (remove_box["width"], remove_box["height"]) == (24, 24)
        skills_dialog.get_by_role("button", name="Закрыть редактор", exact=True).click()

        page.get_by_role("button", name="Изменить город", exact=True).click()
        city_dialog = page.get_by_role("dialog", name="Город", exact=True)
        assert city_dialog.locator(".profile-timezone-note").inner_text() == (
            f"Часовой пояс · {timezone_label}"
        )
        city_search = city_dialog.get_by_role("searchbox", name="Поиск города")
        city_search.fill("Rosario")
        city_option = city_dialog.get_by_role("option", name="Rosario — Argentina")
        assert city_option.locator("small").inner_text() == timezone_label
        city_option.click()
        page.get_by_text("Rosario — Argentina", exact=True).wait_for()

        page.get_by_role("button", name="Изменить имя", exact=True).click()
        name_dialog = page.get_by_role("dialog", name="Имя", exact=True)
        name_input = name_dialog.get_by_role("textbox", name="Имя", exact=True)
        name_input.fill("Новое имя")
        assert name_input.evaluate("node => getComputedStyle(node).outlineWidth") == "0px"
        assert name_input.evaluate("node => getComputedStyle(node).boxShadow") != "none"
        name_dialog.get_by_role("button", name="Сохранить", exact=True).click()
        page.get_by_role("heading", name="Новое имя", exact=True).wait_for()
        assert page.get_by_role("dialog").count() == 0
        assert profile_mutations == [
            {"field": "city", "value": "Rosario — Argentina"},
            {"field": "display_name", "value": "Новое имя"},
        ]
        page.get_by_role("button", name="Задания", exact=True).click()
        page.locator('[data-screen-id="UX02"]').wait_for()
        page.get_by_role("button", name=re.compile("Найти задание")).click()
        page.locator('[data-screen-id="T01"]').wait_for()
        page.get_by_role("button", name=re.compile(re.escape(task["title"]))).click()
        page.locator('[data-screen-id="T03"]').wait_for()
        page.get_by_role("button", name="Назад к заданиям", exact=True).click()
        page.locator('[data-screen-id="T01"]').wait_for()
        assert page.url.endswith("#/catalog?view_state=t01")
        assert page.locator(".settings-list").count() == 0
        page.get_by_role("button", name="Параметры", exact=True).click()
        page.locator(".settings-list").wait_for()

        page.goto(mini_app_url)
        page.get_by_role("heading", name="Задания", exact=True).wait_for()
        assert page.get_by_role("button", name="Параметры", exact=True).is_visible()
        assert page.get_by_role("button", name="Профиль", exact=True).count() == 0
        browser.close()


@pytest.mark.parametrize("viewport", [(375, 812), (430, 932)])
def test_ui_next_profile_secondary_titles_are_visually_hidden(
    mini_app_url: str,
    viewport: tuple[int, int],
) -> None:
    me, member = _cache_profile()
    me["profile_links"] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for route, screen_label, content_selector in (
            ("/profile/edit/city", "Город", ".profile-editor"),
            ("/profile/edit/bio", "О себе", ".profile-editor"),  # noqa: RUF001
            ("/profile/edit/skills", "Навыки", ".profile-editor"),
            ("/profile/links", "Мои ссылки", ".profile-links-manager"),
        ):
            page = _new_page(browser)
            page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
            page.route("**/api/v1/me", lambda request: request.fulfill(json=me))
            page.route(
                f"**/api/v1/members/{me['member_id']}",
                lambda request: request.fulfill(json=member),
            )
            page.route(
                "**/api/v1/moderation/cases?*",
                lambda request: request.fulfill(status=403, json={"code": "forbidden"}),
            )

            page.goto(mini_app_url + f"?theme=light#{route}")
            page.locator(content_selector).wait_for()
            assert page.locator("#screen-title").text_content() == screen_label
            assert page.locator("#screen-title").is_hidden()
            assert page.locator(".screen").get_attribute("aria-label") == screen_label
            route_back = page.get_by_role("button", name="Назад", exact=True)
            assert route_back.inner_text() == "\u2039"
            assert route_back.get_attribute("data-navigation-kind") == "back"
            page.close()
        browser.close()


def test_ui_next_member_profile_returns_to_participants(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    me, member = _cache_profile()
    me["member_id"] = "viewer"
    member["can_rate_karma"] = True
    member["short_bio"] = "Помогаю участникам сообщества решать сложные задачи."

    def karma_vote(route: Route) -> None:
        body = route.request.post_data_json
        assert isinstance(body, dict)
        action = body["action"]
        assert isinstance(action, str)
        revision = {"begin": 0, "save_value": 1, "save_comment": 2, "confirm": 3}[action]
        route.fulfill(
            json={
                "action": action,
                "target_id": member["member_id"],
                "step": "confirmed" if action == "confirm" else action,
                "revision": revision,
                "aggregate": member["karma"] if action == "confirm" else None,
            }
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 375, "height": 812})
        page.route("**/api/v1/me", lambda route: route.fulfill(json=me))
        page.route("**/api/v1/task-home", lambda route: route.fulfill(json=_task_home_payload()))
        page.route(
            "**/api/v1/members?*",
            lambda route: route.fulfill(json={"items": [member], "next_cursor": None}),
        )
        page.route(
            f"**/api/v1/members/{member['member_id']}",
            lambda route: route.fulfill(json=member),
        )
        page.route("**/api/v1/members/*/karma-vote", karma_vote)
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )

        page.goto(mini_app_url + "?theme=light#/tasks")
        page.get_by_role("button", name="Комьюнити", exact=True).click()
        page.get_by_role("button", name="Люди", exact=True).click()
        page.locator(".member-row").click()
        page.locator(".foreign-profile").wait_for()
        member_back = page.get_by_role("button", name="Назад к участникам", exact=True)
        assert member_back.inner_text() == "\u2039"
        assert member_back.get_attribute("data-navigation-kind") == "back"
        assert page.locator("#screen-title").is_hidden()
        assert page.locator(".screen").get_attribute("aria-label") == "Профиль участника"
        bio_card = page.locator(".foreign-bio-card")
        assert bio_card.get_by_role(
            "heading",
            name="О себе",  # noqa: RUF001
            exact=True,
        ).is_visible()
        assert bio_card.get_by_text(member["short_bio"], exact=True).is_visible()
        assert bio_card.locator("h3, p").evaluate_all(
            "nodes => nodes.every(node => node.getBoundingClientRect().left === "
            "nodes[0].getBoundingClientRect().left)"
        )
        rate_karma = page.get_by_role("button", name="Оценить карму", exact=True)
        assert rate_karma.evaluate(
            "node => node.previousElementSibling?.classList.contains('foreign-metrics') "
            "&& node.nextElementSibling?.classList.contains('foreign-bio-card')"
        )
        rate_karma.click()
        page.get_by_role("heading", name="Оценить взаимодействие", exact=True).wait_for()
        assert page.locator("#screen-title").text_content() == "Оценка кармы"
        assert page.locator("#screen-title").is_hidden()
        assert page.locator(".screen").get_attribute("aria-label") == "Оценка кармы"
        comment = page.get_by_label(re.compile("^Комментарий"))
        comment.fill("Полезное и внимательное взаимодействие")
        page.get_by_role("button", name="Подтвердить оценку", exact=True).click()
        assert page.locator("#screen-title").text_content() == "Подтвердить оценку"
        assert page.locator("#screen-title").is_hidden()
        assert page.locator(".screen").get_attribute("aria-label") == "Подтвердить оценку"
        assert page.get_by_role("button", name="Изменить", exact=True).count() == 0
        assert page.locator(".confirm-actions button").count() == 1
        assert page.locator(".confirm-actions").evaluate(
            "node => Math.abs(node.clientWidth - node.firstElementChild.offsetWidth) < 1"
        )
        page.get_by_role("button", name="Назад", exact=True).click()
        page.get_by_role("heading", name="Оценить взаимодействие", exact=True).wait_for()
        assert comment.input_value() == "Полезное и внимательное взаимодействие"
        page.get_by_role("button", name="Подтвердить оценку", exact=True).click()
        page.get_by_role("button", name="Сохранить оценку", exact=True).click()
        page.locator('[data-screen-id="P04"]').wait_for()
        assert page.locator("#screen-title").text_content() == "Карма сохранена"
        assert page.locator("#screen-title").is_hidden()
        assert page.locator(".screen").get_attribute("aria-label") == "Карма сохранена"
        page.get_by_role("button", name="К профилю", exact=True).click()  # noqa: RUF001
        page.locator(".foreign-profile").wait_for()
        page.get_by_role("button", name="Назад к участникам", exact=True).click()
        page.locator(".participants-view").wait_for()
        assert page.url.endswith("#/members?view_state=p01")
        browser.close()


def test_ui_next_task_creation_uses_medium_navigation_title(mini_app_url: str) -> None:
    category_id = "00000000-0000-0000-0000-000000000119"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 375, "height": 812})
        page.route("**/api/v1/me", lambda route: route.fulfill(json={"member_id": "member"}))
        page.route("**/api/v1/task-home", lambda route: route.fulfill(json=_task_home_payload()))
        page.route(
            "**/api/v1/task-creation",
            lambda route: route.fulfill(
                json={
                    "categories": [
                        {"id": category_id, "name": "Практическая помощь", "icon": "⭐"}
                    ],
                    "time_sizes": [
                        {
                            "value": "s",
                            "label": "15-40 минут",
                            "reward_options": [2, 3, 4],
                            "minimum_reward": 2,
                        },
                    ],
                    "draft": None,
                    "preview": None,
                    "needs_edit": False,
                }
            ),
        )
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )

        page.goto(mini_app_url + "?theme=dark#/tasks")
        page.locator('[data-home-action="create"]').click()
        page.locator('[data-screen-id="T05"]').wait_for()
        assert page.locator("#screen-title").text_content() == "Новое задание"
        assert page.locator("#screen-title").is_visible()
        assert (
            page.locator("#screen-title").evaluate("node => getComputedStyle(node).fontSize")
            == "18px"
        )
        assert page.locator(".screen").get_attribute("aria-labelledby") == "screen-title"
        creation_back = page.get_by_role("button", name="Назад", exact=True)
        assert creation_back.inner_text() == "\u2039"
        assert creation_back.get_attribute("data-navigation-kind") == "back"
        assert page.get_by_role("button", name="Выбрать тип задания", exact=True).is_visible()
        _choose_creation_option(
            page,
            trigger="Выбрать тип задания",
            dialog="Тип задания",
            option="Групповое",
        )
        assert page.get_by_label("Число исполнителей *", exact=True).is_enabled()
        browser.close()


@pytest.mark.parametrize("viewport", [(375, 650), (375, 812), (430, 932)])
@pytest.mark.browser_smoke
def test_ui_next_task_home_uses_server_projection_and_stable_theme_geometry(  # noqa: PLR0915
    mini_app_url: str,
    viewport: tuple[int, int],
) -> None:
    home = _task_home_payload()
    selectors = [
        ".task-home-attention",
        ".task-home-primary-actions",
        ".task-home-work-grid",
        ".task-home-archive",
    ]

    def boxes(page: Page) -> dict[str, dict[str, float]]:
        return page.evaluate(
            """selectors => Object.fromEntries(selectors.map(selector => {
              const rect = document.querySelector(selector).getBoundingClientRect();
              return [selector, Object.fromEntries(
                ['x', 'y', 'width', 'height'].map(key => [key, Math.round(rect[key] * 100) / 100])
              )];
            }))""",
            selectors,
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
        requests: list[str] = []
        page.on(
            "request",
            lambda request: (
                requests.append(urlsplit(request.url).path) if "/api/v1/" in request.url else None
            ),
        )
        page.route("**/api/v1/me", lambda route: route.fulfill(json={"member_id": "member"}))
        page.route("**/api/v1/task-home", lambda route: route.fulfill(json=home))
        page.route("**/api/v1/owned-tasks", lambda route: route.fulfill(json={"items": []}))
        page.route(
            "**/api/v1/assignment-reviews",
            lambda route: route.fulfill(json={"items": []}),
        )
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )

        page.goto(mini_app_url + "?theme=dark#/tasks")
        boundary = page.locator('[data-screen-id="UX02"][data-ui-engine="next-tasks-home"]')
        boundary.wait_for()
        assert boundary.get_by_text("Требуются ваши действия", exact=True).is_visible()
        assert boundary.get_by_text("ВЗЯТЫЕ МНОЙ", exact=True).is_visible()
        assert boundary.get_by_text("СОЗДАННЫЕ МНОЙ", exact=True).is_visible()
        assert boundary.get_by_text("Проверить сценарий первого запуска", exact=False).count() == 0
        assert boundary.get_by_text("18", exact=True).is_visible()
        expect(page.locator("#primary-navigation button:visible")).to_have_count(4)
        expect(page.get_by_role("button", name="Кошелёк", exact=True)).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert page.locator(
            ".task-home-primary, .task-home-work-tile, .task-home-archive"
        ).evaluate_all(
            "nodes => nodes.every(node => node.getBoundingClientRect().width >= 44 "
            "&& node.getBoundingClientRect().height >= 44)"
        )
        assert page.locator(
            ".task-home-attention-action, .task-home-attention-switch"
        ).evaluate_all("nodes => nodes.every(node => node.getBoundingClientRect().height >= 38)")
        if viewport[1] <= 760:
            assert page.locator(".task-home-screen .screen").evaluate(
                "node => node.scrollHeight <= node.clientHeight"
            )
        attention_height = page.locator(".task-home-attention").bounding_box()["height"]
        page.locator('[data-home-hero-switch="waiting"]').click()
        assert boundary.get_by_text("Ждём действия других", exact=True).is_visible()
        assert boundary.get_by_text("Выполняют ваши задания", exact=True).count() == 0
        assert boundary.get_by_text("Проверяют вашу работу", exact=True).is_visible()
        assert boundary.get_by_text("Решают отмену или спор", exact=True).count() == 0
        waiting_height = page.locator(".task-home-attention").bounding_box()["height"]
        assert waiting_height < attention_height
        assert waiting_height <= 180
        page.locator('[data-home-hero-switch="attention"]').click()
        assert boundary.get_by_text("Требуются ваши действия", exact=True).is_visible()
        assert page.locator(".task-home-attention").bounding_box()["height"] == attention_height
        dark_boxes = boxes(page)

        page.goto(mini_app_url + "?theme=light#/tasks")
        boundary.wait_for()
        assert page.evaluate("document.documentElement.dataset.theme") == "light"
        assert boxes(page) == dark_boxes
        assert requests.count("/api/v1/task-home") == 2
        page.locator('[data-home-action="created"]').click()
        page.locator('[data-screen-id="M09"]').wait_for()
        assert page.url.endswith("#/work?view_state=m09")
        page.reload()
        page.locator('[data-screen-id="M09"]').wait_for()
        assert page.url.endswith("#/work?view_state=m09")
        browser.close()


def test_ui_next_task_home_empty_partial_error_and_existing_flow_transition(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    mode = {"value": "empty"}
    attempts = 0

    def task_home(route: Route) -> None:
        nonlocal attempts
        attempts += 1
        if mode["value"] == "error":
            route.fulfill(status=503, json={"code": "request_failed"})
        else:
            route.fulfill(
                json=_task_home_payload(
                    empty=mode["value"] == "empty",
                    partial=mode["value"] == "partial",
                )
            )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.route("**/api/v1/me", lambda route: route.fulfill(json={"member_id": "member"}))
        page.route("**/api/v1/task-home", task_home)
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [_task_home_task()], "next_cursor": None}),
        )

        page.goto(mini_app_url + "?theme=dark#/tasks")
        page.locator('[data-screen-id="UX02"][data-state="content"]').wait_for()
        assert page.get_by_text("Всё под контролем", exact=True).is_visible()
        assert page.locator(".task-home-new").count() == 0

        mode["value"] = "partial"
        page.evaluate("localStorage.clear()")
        page.reload()
        page.locator('[data-screen-id="UX02"][data-state="partial"]').wait_for()
        assert page.get_by_text("Часть данных временно недоступна.", exact=True).is_visible()
        page.locator('[data-home-action="find"]').click()
        page.locator('[data-screen-id="T01"]').wait_for()
        assert page.url.endswith("#/catalog?view_state=t01")
        catalog_back = page.get_by_role("button", name="Назад к заданиям", exact=True)
        assert catalog_back.inner_text() == "\u2039"
        assert (
            page.locator(".screen").evaluate("node => getComputedStyle(node).paddingTop") == "12px"
        )
        page.evaluate(
            "document.documentElement.dataset.telegramFullscreen = 'true'; "
            "document.documentElement.style.setProperty("
            "'--tg-content-safe-area-inset-top', '74px')"
        )
        assert (
            page.locator(".screen").evaluate("node => getComputedStyle(node).paddingTop") == "80px"
        )
        assert page.locator(".catalog-actions").evaluate(
            "node => node.getBoundingClientRect().top "
            "- document.querySelector('.screen').getBoundingClientRect().top"
        ) == pytest.approx(80, abs=0.5)
        action_geometry = page.evaluate(
            """() => {
              const back = document.querySelector('.catalog-back-button').getBoundingClientRect();
              const filterButton = document.querySelector('.catalog-filter-button');
              const filters = filterButton.getBoundingClientRect();
              const sort = document.querySelector('.catalog-sort-button').getBoundingClientRect();
              const search = document.querySelector('.catalog-search').getBoundingClientRect();
              const actions = document.querySelector('.catalog-actions').getBoundingClientRect();
              const backCenter = (back.top + back.bottom) / 2;
              const filtersCenter = (filters.top + filters.bottom) / 2;
              const sortCenter = (sort.top + sort.bottom) / 2;
              return {
                aligned: Math.abs(backCenter - filtersCenter) < 1
                  && Math.abs(backCenter - sortCenter) < 1,
                rightAligned: Math.abs(actions.right - sort.right) < 1,
                paired: Math.abs(sort.left - filters.right - 8) < 1,
                searchBetween: search.left > back.right && search.right < filters.left,
                backWidth: back.width,
                backHeight: back.height,
                filtersWidth: filters.width,
                filtersHeight: filters.height,
                sortWidth: sort.width,
                sortHeight: sort.height,
                filtersText: filterButton.textContent,
              };
            }"""
        )
        assert action_geometry == {
            "aligned": True,
            "rightAligned": True,
            "paired": True,
            "searchBetween": True,
            "backWidth": 36,
            "backHeight": 36,
            "filtersWidth": 36,
            "filtersHeight": 36,
            "sortWidth": 36,
            "sortHeight": 36,
            "filtersText": "",
        }
        catalog_back.click()
        page.locator('[data-screen-id="UX02"]').wait_for()
        assert page.url.endswith("#/tasks")
        page.locator('[data-home-action="find"]').click()
        page.locator('[data-screen-id="T01"]').wait_for()
        catalog_url = page.url
        assert (
            page.get_by_label("Поиск по названию и описанию", exact=True).get_attribute(
                "placeholder"
            )
            == "Название или описание"
        )
        page.get_by_role("button", name="Фильтры", exact=True).click()
        filter_dialog = page.get_by_role("dialog", name="Активные фильтры", exact=True)
        filter_dialog.wait_for()
        assert page.url == catalog_url
        assert page.locator('[data-screen-id="T02"]').count() == 0
        assert (
            filter_dialog.get_by_role("heading", name="Активные фильтры", exact=True).evaluate(
                "node => getComputedStyle(node).fontSize"
            )
            == "18px"
        )
        filter_dialog.get_by_role("button", name="Закрыть фильтры", exact=True).click()
        page.locator('[data-screen-id="T01"]').wait_for()
        page.locator(".task-card").click()
        page.locator('[data-screen-id="T03"]').wait_for()
        task_back = page.get_by_role("button", name="Назад к заданиям", exact=True)
        assert task_back.inner_text() == "\u2039"
        assert task_back.get_attribute("data-navigation-kind") == "back"
        assert page.locator("#screen-title").is_hidden()
        task_back.click()
        page.locator('[data-screen-id="T01"]').wait_for()
        page.locator("#catalog-nav").click()
        page.locator('[data-screen-id="UX02"]').wait_for()
        assert page.url.endswith("#/tasks")

        mode["value"] = "error"
        page.evaluate("localStorage.clear()")
        page.reload()
        page.locator('[data-screen-id="UX02"][data-state="error"]').wait_for()
        mode["value"] = "empty"
        page.get_by_role("button", name="Повторить", exact=True).click()
        page.locator('[data-screen-id="UX02"][data-state="content"]').wait_for()
        assert attempts >= 4
        browser.close()


def test_task_home_action_count_opens_one_card_or_a_choice_sheet(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    home = _task_home_payload()
    first_assignment_id = home["attention"][0]["items"][0]["id"]
    review_assignment_id = home["attention"][1]["items"][0]["id"]
    home["attention"][1]["count"] = 2
    home["attention"][1]["items"].append(
        {
            "id": "00000000-0000-0000-0000-000000000223",
            "title": "Проверить вторую работу участника",
            "context": "Второй участник",
            "status": "submitted",
            "started_at": "2026-08-25T11:00:00Z",
            "deadline_at": "2026-08-28T11:00:00Z",
        }
    )
    _base_id, _draft_id, _assignment, detail = _freeform_submission_rows()
    detail = {
        **detail,
        "id": first_assignment_id,
        "task_title": "Подготовить результат проверки",
        "assignment_status": "accepted",
        "submitted_at": None,
        "result_summary": None,
        "can_submit": True,
        "can_cancel": True,
    }
    review = {
        "id": review_assignment_id,
        "task_id": "00000000-0000-0000-0000-000000000222",
        "task_title": "Проверить работу тестового участника",
        "performer_display_name": "Тестовый участник",
        "submitted_at": "2026-08-26T11:00:00Z",
        "review_deadline_at": "2026-08-28T11:00:00Z",
        "result": "Готовый результат",
        "available_decisions": ["full", "partial", "reject"],
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 375, "height": 812})
        page.route("**/api/v1/me", lambda route: route.fulfill(json={"member_id": "member"}))
        page.route("**/api/v1/task-home", lambda route: route.fulfill(json=home))
        page.route("**/api/v1/assignments/*", lambda route: route.fulfill(json=detail))
        page.route(
            f"**/api/v1/assignment-reviews/{review_assignment_id}",
            lambda route: route.fulfill(json=review),
        )
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )

        page.goto(mini_app_url + "?theme=dark#/tasks")
        page.get_by_role("button", name="Сдать результат 2", exact=True).click()
        chooser = page.get_by_role("dialog", name="Сдать результат", exact=True)
        chooser.wait_for()
        assert chooser.locator(".task-home-action-card").count() == 2
        first_choice = chooser.get_by_role(
            "button", name=re.compile("Подготовить результат проверки")
        )
        assert first_choice.get_by_text("Принято", exact=True).is_visible()
        assert first_choice.get_by_text("От участника", exact=True).is_visible()
        assert first_choice.get_by_text(
            "Задание выполняется — результат ещё не отправлен.", exact=True
        ).is_visible()
        assert first_choice.get_by_text("Взято 24 авг.", exact=True).is_visible()
        assert first_choice.get_by_text("до 27 авг.", exact=True).is_visible()
        assert chooser.get_by_role("button", name="Подготовить результат проверки").is_visible()
        assert chooser.get_by_role("button", name="Сверить итоговый сценарий").is_visible()
        chooser.get_by_role("button", name="Подготовить результат проверки").click()
        page.locator('[data-screen-id="M03"]').wait_for()
        assert (
            page.get_by_role("button", name="Назад к заданиям", exact=True).get_attribute(
                "data-navigation-kind"
            )
            == "back"
        )
        assert page.get_by_role(
            "heading", name="Подготовить результат проверки", exact=True
        ).is_visible()
        assert (
            page.locator(".assignment-detail-meta").get_by_text("Принято", exact=True).is_visible()
        )
        action_geometry = page.locator(".assignment-detail .detail-actions button").evaluate_all(
            "nodes => nodes.map(node => { const box = node.getBoundingClientRect(); "
            "return { top: Math.round(box.top), width: Math.round(box.width), "
            "height: box.height }; })"
        )
        assert len(action_geometry) == 2
        assert action_geometry[0]["top"] == action_geometry[1]["top"]
        assert all(item["width"] >= 135 and item["height"] >= 44 for item in action_geometry)
        page.get_by_role("button", name="Назад к заданиям", exact=True).click()
        page.locator('[data-screen-id="UX02"]').wait_for()
        assert page.url.endswith("#/tasks")

        page.goto(mini_app_url + "?theme=dark&review=single-action#/tasks")
        page.get_by_role("button", name="Проверить работу 2", exact=True).click()
        review_chooser = page.get_by_role("dialog", name="Проверить работу", exact=True)
        review_chooser.wait_for()
        assert review_chooser.locator(".task-home-action-card").count() == 2
        review_choice = review_chooser.get_by_role(
            "button", name=re.compile("Проверить работу тестового участника")
        )
        assert review_choice.get_by_text("Требуется проверка", exact=True).is_visible()
        assert review_choice.get_by_text("Тестовый участник", exact=True).is_visible()
        assert review_choice.get_by_text(
            "Исполнитель Тестовый участник отправил результат.", exact=True
        ).is_visible()
        assert review_choice.get_by_text("Отправлено 24 авг.", exact=True).is_visible()
        assert review_choice.get_by_text("решить до 27 авг.", exact=True).is_visible()
        review_choice.click()
        page.locator('[data-screen-id="M11"]').wait_for()
        assert page.get_by_role(
            "heading", name="Проверить работу тестового участника", exact=True
        ).is_visible()
        assert page.get_by_role("dialog").count() == 0
        page.get_by_role("button", name="Назад к заданиям", exact=True).click()
        page.locator('[data-screen-id="UX02"]').wait_for()
        assert page.url.endswith("#/tasks")
        browser.close()


def test_ui_next_assignment_actions_use_compact_sheets_and_review_is_compact(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    home = _task_home_payload()
    assignment_id = home["attention"][0]["items"][0]["id"]
    creator_id = "00000000-0000-0000-0000-000000000198"
    review_assignment_id = home["attention"][1]["items"][0]["id"]
    _base_id, draft_id, _assignment, base_detail = _freeform_submission_rows()
    accepted_detail = {
        **base_detail,
        "id": assignment_id,
        "task_title": "Подготовить результат проверки",
        "task_creator_id": creator_id,
        "task_author_display_name": "Алексей Окситоцин",
        "assignment_status": "accepted",
        "submitted_at": None,
        "result_summary": None,
        "can_submit": True,
        "can_cancel": True,
    }
    submitted_detail = {
        **accepted_detail,
        "assignment_status": "submitted",
        "result_summary": "Готовый результат для проверки",
        "can_submit": False,
        "can_cancel": False,
    }
    rejected_detail = {
        **accepted_detail,
        "assignment_status": "rejected_pending_dispute",
        "reject_dispute_deadline_at": "2026-08-28T11:00:00Z",
        "can_submit": False,
        "can_cancel": False,
        "can_dispute": True,
    }
    disputed_detail = {
        **rejected_detail,
        "assignment_status": "disputed",
        "case_status": "open",
        "can_dispute": False,
    }
    current_detail: dict[str, Any] = {"value": accepted_detail}
    review = {
        "id": review_assignment_id,
        "task_id": "00000000-0000-0000-0000-000000000222",
        "task_title": "Проверить работу тестового участника",
        "performer_display_name": "Тестовый участник",
        "submitted_at": "2026-08-26T11:00:00Z",
        "review_deadline_at": "2026-08-28T11:00:00Z",
        "result": "Макет проверен на мобильном устройстве.",
        "available_decisions": ["full", "partial", "reject"],
    }
    saved_results: list[dict[str, Any]] = []
    cancellations: list[dict[str, Any]] = []
    disputes: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []

    def assignment_detail(route: Route) -> None:
        route.fulfill(json=current_detail["value"])

    def begin_submission(route: Route) -> None:
        assert route.request.method == "POST"
        route.fulfill(json={"id": draft_id, "revision": 0, "result": None})

    def save_submission(route: Route) -> None:
        body = route.request.post_data_json
        assert route.request.method == "PUT"
        assert isinstance(body, dict)
        saved_results.append(body)
        route.fulfill(json={"id": draft_id, "revision": 1, "result": body["payload"]["result"]})

    def confirm_submission(route: Route) -> None:
        assert route.request.post_data_json == {"expected_revision": 1}
        current_detail["value"] = submitted_detail
        route.fulfill(status=204)

    def cancel_assignment(route: Route) -> None:
        body = route.request.post_data_json
        assert isinstance(body, dict)
        cancellations.append(body)
        route.fulfill(status=204)

    def open_dispute(route: Route) -> None:
        body = route.request.post_data_json
        assert isinstance(body, dict)
        disputes.append(body)
        current_detail["value"] = disputed_detail
        route.fulfill(status=204)

    def decide(route: Route) -> None:
        body = route.request.post_data_json
        assert isinstance(body, dict)
        decisions.append(body)
        route.fulfill(status=204)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 375, "height": 812})
        page.route("**/api/v1/me", lambda route: route.fulfill(json={"member_id": "member"}))
        _, creator = _cache_profile(creator_id)
        creator["display_name"] = "Алексей Окситоцин"
        page.route(
            f"**/api/v1/members/{creator_id}",
            lambda route: route.fulfill(json=creator),
        )
        page.route(
            "**/api/v1/community-stats/pulse?*",
            lambda route: route.fulfill(status=503, json={"code": "unavailable"}),
        )
        page.route("**/api/v1/task-home", lambda route: route.fulfill(json=home))
        page.route(
            "**/api/v1/assignments?*",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route(f"**/api/v1/assignments/{assignment_id}", assignment_detail)
        page.route(
            f"**/api/v1/assignments/{assignment_id}/submission-drafts",
            begin_submission,
        )
        page.route(f"**/api/v1/submission-drafts/{draft_id}", save_submission)
        page.route(f"**/api/v1/submission-drafts/{draft_id}/confirm", confirm_submission)
        page.route(
            f"**/api/v1/assignments/{assignment_id}/cancellation",
            cancel_assignment,
        )
        page.route(
            f"**/api/v1/assignments/{assignment_id}/disputes",
            open_dispute,
        )
        page.route(
            f"**/api/v1/assignment-reviews/{review_assignment_id}",
            lambda route: route.fulfill(json=review),
        )
        page.route(
            f"**/api/v1/assignment-reviews/{review_assignment_id}/decision",
            decide,
        )
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )

        page.goto(mini_app_url + "?theme=dark&review=compact-actions#/tasks")
        page.get_by_role("button", name="Сдать результат 2", exact=True).click()
        page.get_by_role("dialog", name="Сдать результат", exact=True).get_by_role(
            "button", name="Подготовить результат проверки"
        ).click()
        page.locator('[data-screen-id="M03"]').wait_for()
        customer = page.get_by_role(
            "button", name="Открыть профиль заказчика Алексей Окситоцин", exact=True
        )
        assert customer.is_visible()
        assert customer.evaluate(
            "node => node.closest('.assignment-detail-header').querySelector('h2')"
            ".compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING"
        )
        customer.click()
        page.locator(".foreign-profile").wait_for()
        assert page.url.endswith(f"#/members/{creator_id}")
        page.go_back()
        page.locator('[data-screen-id="M03"]').wait_for()
        opened_url = page.url
        page.get_by_role("button", name="Отправить результат", exact=True).click()
        submission_sheet = page.get_by_role("dialog", name="Отправить результат", exact=True)
        submission_sheet.wait_for()
        assert page.url == opened_url
        assert submission_sheet.get_by_role("button", name="Отмена", exact=True).count() == 0
        assert submission_sheet.get_by_text(
            "Минимум 10 символов · 0 / 2000", exact=True
        ).is_visible()
        assert submission_sheet.get_by_role(
            "button", name="Отправить результат", exact=True
        ).is_disabled()
        assert page.locator(".assignment-action-sheet").bounding_box()["y"] < 100
        assert page.locator(".assignment-action-buttons > :only-child").is_visible()
        legacy_submission_screens = page.locator(
            '[data-screen-id="M04"], [data-screen-id="M05"], [data-screen-id="M06"]'
        )
        assert legacy_submission_screens.count() == 0
        submission_sheet.get_by_label("Результат", exact=True).fill(
            "Готовый результат для проверки"
        )
        submission_sheet.get_by_role("button", name="Отправить результат", exact=True).click()
        page.locator('[data-screen-id="UX02"]').wait_for()
        assert page.url.endswith("#/tasks")
        assert saved_results[0]["payload"] == {"result": "Готовый результат для проверки"}

        current_detail["value"] = accepted_detail
        page.goto(mini_app_url + "?theme=dark&review=compact-cancel#/tasks")
        page.get_by_role("button", name="Сдать результат 2", exact=True).click()
        page.get_by_role("dialog", name="Сдать результат", exact=True).get_by_role(
            "button", name="Подготовить результат проверки"
        ).click()
        page.locator('[data-screen-id="M03"]').wait_for()
        cancel_url = page.url
        page.get_by_role("button", name="Отказаться от задания", exact=True).click()
        cancel_sheet = page.get_by_role("dialog", name="Отказаться от задания", exact=True)
        cancel_sheet.wait_for()
        assert page.url == cancel_url
        keep_label = "Не отказываться"  # noqa: RUF001
        assert cancel_sheet.get_by_role("button", name=keep_label, exact=True).count() == 0
        assert cancel_sheet.get_by_text(
            "Укажите причину отказа · 0 / 1000", exact=True
        ).is_visible()
        assert page.locator(".assignment-action-sheet").bounding_box()["y"] < 100
        assert page.locator(".assignment-action-buttons > :only-child").is_visible()
        assert page.locator('[data-screen-id="M08"]').count() == 0
        cancel_reason = "Не успеваю к сроку"  # noqa: RUF001
        cancel_sheet.get_by_label("Причина отказа", exact=True).fill(cancel_reason)
        cancel_sheet.get_by_role("button", name="Подтвердить отказ", exact=True).click()
        page.locator('[data-screen-id="UX02"]').wait_for()
        assert page.url.endswith("#/tasks")
        assert cancellations == [{"reason": cancel_reason}]

        current_detail["value"] = rejected_detail
        page.goto(mini_app_url + "?theme=dark&review=compact-dispute#/tasks")
        page.get_by_role("button", name="Сдать результат 2", exact=True).click()
        page.get_by_role("dialog", name="Сдать результат", exact=True).get_by_role(
            "button", name="Подготовить результат проверки"
        ).click()
        page.locator('[data-screen-id="M03"]').wait_for()
        dispute_url = page.url
        page.get_by_role("button", name="Подать спор", exact=True).click()
        dispute_sheet = page.get_by_role("dialog", name="Открыть спор", exact=True)
        dispute_sheet.wait_for()
        assert page.url == dispute_url
        assert page.locator('[data-screen-id="M14"]').count() == 0
        assert dispute_sheet.get_by_text("Минимум 10 символов · 0 / 1000", exact=True).is_visible()
        assert dispute_sheet.get_by_role("button", name="Подать спор", exact=True).is_disabled()
        assert page.locator(".assignment-action-sheet").bounding_box()["y"] < 100
        assert page.locator(".assignment-action-buttons > :only-child").is_visible()
        dispute_comment = dispute_sheet.get_by_label("Причина пересмотра", exact=True)
        dispute_comment.fill("коротко")
        assert dispute_sheet.get_by_text("Нужно ещё 3 · 7 / 1000", exact=True).is_visible()
        assert dispute_sheet.get_by_role("button", name="Подать спор", exact=True).is_disabled()
        reason = "Прошу пересмотреть результат."
        dispute_comment.fill(reason)
        dispute_sheet.get_by_role("button", name="Подать спор", exact=True).click()
        page.locator('[data-screen-id="UX02"]').wait_for()
        assert page.url.endswith("#/tasks")
        assert disputes == [{"comment": reason}]

        page.goto(mini_app_url + "?theme=dark&review=compact-review#/tasks")
        page.get_by_role("button", name="Проверить работу 1", exact=True).click()
        page.locator('[data-screen-id="M11"]').wait_for()
        assert page.locator(".assignment-review-detail").is_visible()
        assert page.locator("#screen-title").is_hidden()
        decision_geometry = page.locator(".assignment-review-actions button").evaluate_all(
            "nodes => nodes.map(node => { const box = node.getBoundingClientRect(); "
            "return { top: Math.round(box.top), width: Math.round(box.width), "
            "height: Math.round(box.height) }; })"
        )
        assert len(decision_geometry) == 3
        assert decision_geometry[0]["width"] > decision_geometry[1]["width"]
        assert decision_geometry[1]["top"] == decision_geometry[2]["top"]
        assert all(item["height"] >= 44 for item in decision_geometry)
        review_opened_url = page.url
        page.get_by_role("button", name="Отклонить", exact=True).click()
        decision_sheet = page.get_by_role("dialog", name="Отклонить", exact=True)
        decision_sheet.wait_for()
        assert page.url == review_opened_url
        assert page.locator('[data-screen-id="M12"]').count() == 0
        assert decision_sheet.get_by_role("button", name="Вернуться", exact=True).count() == 0
        assert decision_sheet.locator(".assignment-action-buttons > :only-child").is_visible()
        reject_confirm = decision_sheet.get_by_role("button", name="Отклонить", exact=True)
        assert reject_confirm.is_disabled()
        decision_sheet.get_by_label("Недостаточно подтверждений", exact=True).check()
        comment = decision_sheet.get_by_label("Комментарий к отклонению", exact=True)
        comment.fill("Нужна ссылка на готовый результат.")
        assert reject_confirm.is_enabled()
        reject_confirm.click()
        page.locator('[data-screen-id="UX02"]').wait_for()
        assert page.url.endswith("#/tasks")
        assert decisions == [
            {
                "decision": "reject",
                "rejection_reason": "insufficient_evidence",
                "rejection_comment": "Нужна ссылка на готовый результат.",
            }
        ]
        browser.close()


def test_ui_next_accepted_task_returns_to_taken_assignments(mini_app_url: str) -> None:
    task = _task_home_task("00000000-0000-0000-0000-000000000231")
    assignment_id = "00000000-0000-0000-0000-000000000232"
    assignment = {
        "id": assignment_id,
        "task_id": task["id"],
        "task_title": task["title"],
        "task_origin": task["origin"],
        "created_at": task["created_at"],
        "category_name": task["category_name"],
        "task_kind": task["task_kind"],
        "time_size": task["time_size"],
        "format": task["format"],
        "city": task["city"],
        "credit_reward_per_performer": task["credit_reward_per_performer"],
        "performer_slots": task["performer_slots"],
        "minimum_level": task["minimum_level"],
        "deadline_at": task["deadline_at"],
        "assignment_status": "accepted",
        "accepted_at": "2026-08-26T12:00:00Z",
        "submitted_at": None,
        "review_deadline_at": None,
        "reject_dispute_deadline_at": None,
        "reviewed_at": None,
        "task_deadline_at": task["deadline_at"],
        "result_summary": None,
        "case_status": None,
    }
    detail = assignment | {
        "category_icon": task["category_icon"],
        "description": task["description"],
        "performer_instructions": task["performer_instructions"],
        "completion_criteria": task["completion_criteria"],
        "reward_per_performer": task["credit_reward_per_performer"],
        "submission_contract": None,
        "can_submit": True,
        "can_cancel": True,
        "can_dispute": False,
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 375, "height": 812})
        page.route("**/api/v1/me", lambda route: route.fulfill(json={"member_id": "member"}))
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload()),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [task], "next_cursor": None}),
        )
        page.route(
            f"**/api/v1/tasks/{task['id']}/assignments",
            lambda route: route.fulfill(
                status=201,
                json={
                    "id": assignment_id,
                    "task_id": task["id"],
                    "slot_number": 1,
                    "status": "accepted",
                    "accepted_at": assignment["accepted_at"],
                },
            ),
        )
        page.route(
            "**/api/v1/assignments?*",
            lambda route: route.fulfill(json={"items": [assignment], "next_cursor": None}),
        )
        page.route(
            f"**/api/v1/assignments/{assignment_id}",
            lambda route: route.fulfill(json=detail),
        )
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )

        page.goto(mini_app_url + "?theme=dark&review=accept-return#/tasks")
        page.get_by_role("button", name=re.compile("Найти задание")).click()
        page.get_by_role("button", name=re.compile(task["title"])).click()
        page.get_by_role("button", name="Принять задание", exact=True).click()
        assert page.get_by_role("button", name="Изменить", exact=True).count() == 0
        page.get_by_role("button", name="Принять слот", exact=True).click()
        page.locator('[data-screen-id="M03"]').wait_for()
        page.get_by_role("button", name="Назад к выполняемым заданиям", exact=True).click()
        taken = page.locator('[data-screen-id="M01"]')
        taken.wait_for()
        assert page.url.endswith("#/work?view_state=m01")
        assert taken.get_by_role("heading", name="Что я выполняю", exact=True).is_visible()
        assert taken.get_by_role("button", name=re.compile(task["title"])).is_visible()
        assert page.locator('[data-screen-id="T01"]').count() == 0
        browser.close()


@pytest.mark.browser_smoke
def test_ui_next_catalog_supports_full_filters_sorting_and_reset(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    catalog_tasks = [
        {
            **_task_home_task("00000000-0000-0000-0000-000000000201"),
            "title": "Настроить онлайн-встречу",
            "description": "Подготовить общую встречу сообщества.",
            "category_name": "Организация",
            "task_kind": "solo",
            "time_size": "s",
            "format": "online",
            "credit_reward_per_performer": 2,
            "performer_slots": 1,
            "created_at": "2026-08-20T12:00:00Z",
            "deadline_at": "2026-09-03T20:00:00Z",
        },
        {
            **_task_home_task("00000000-0000-0000-0000-000000000202"),
            "title": "Помочь району с офлайн-встречей",  # noqa: RUF001
            "description": "Организовать встречу в Буэнос-Айресе.",
            "category_name": "Практическая помощь",
            "task_kind": "group",
            "time_size": "m",
            "format": "offline",
            "city": "Буэнос-Айрес",
            "credit_reward_per_performer": 8,
            "performer_slots": 4,
            "created_at": "2026-08-22T12:00:00Z",
            "deadline_at": "2026-08-30T20:00:00Z",
        },
        {
            **_task_home_task("00000000-0000-0000-0000-000000000203"),
            "title": "Проверить текст публикации",
            "description": "Отредактировать описание нового проекта.",
            "category_name": "Продвижение",
            "task_kind": "group",
            "time_size": "l",
            "format": "online",
            "credit_reward_per_performer": 5,
            "performer_slots": 2,
            "created_at": "2026-08-21T12:00:00Z",
            "deadline_at": "2026-09-01T20:00:00Z",
        },
    ]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 375, "height": 812})
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(json={"member_id": "member"}),
        )
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload()),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": catalog_tasks, "next_cursor": None}),
        )

        page.goto(mini_app_url + "?theme=light#/tasks")
        page.locator('[data-screen-id="UX02"]').wait_for()
        page.locator('[data-home-action="find"]').click()
        catalog = page.locator('[data-screen-id="T01"][data-state="content"]')
        catalog.wait_for()
        assert page.get_by_role("button", name="+ Создать", exact=True).count() == 0

        sorting = page.get_by_role("button", name="Сортировка: Создано позже", exact=True)
        assert "is-active" not in (sorting.get_attribute("class") or "")
        assert page.locator(".catalog-sort-select").count() == 0
        sorting.click()
        sort_dialog = page.get_by_role("dialog", name="Сортировка", exact=True)
        sort_dialog.wait_for()
        assert sort_dialog.evaluate(
            "node => { const shell = document.querySelector('.shell').getBoundingClientRect(); "
            "const box = node.getBoundingClientRect(); "
            "return box.top - shell.top >= 55 && box.top - shell.top <= 70; }"
        )
        assert (
            sort_dialog.locator('[role="radio"][aria-checked="true"]')
            .inner_text()
            .startswith("Создано позже")
        )
        assert sort_dialog.get_by_role("radio", name="Создано раньше", exact=True).is_visible()
        assert sort_dialog.get_by_role("radio", name="Мест больше", exact=True).count() == 0
        sort_dialog.get_by_role("radio", name="Создано раньше", exact=True).click()
        assert catalog.locator(".task-card h3").all_inner_texts() == [
            catalog_tasks[0]["title"],
            catalog_tasks[2]["title"],
            catalog_tasks[1]["title"],
        ]
        page.get_by_role("button", name="Сортировка: Создано раньше", exact=True).click()
        sort_dialog = page.get_by_role("dialog", name="Сортировка", exact=True)
        sort_dialog.get_by_role("radio", name="Срок дальше", exact=True).click()
        assert catalog.locator(".task-card h3").all_inner_texts() == [
            catalog_tasks[0]["title"],
            catalog_tasks[2]["title"],
            catalog_tasks[1]["title"],
        ]
        page.get_by_role("button", name="Сортировка: Срок дальше", exact=True).click()
        sort_dialog = page.get_by_role("dialog", name="Сортировка", exact=True)
        sort_dialog.get_by_role("radio", name="Награда выше", exact=True).click()
        assert sort_dialog.count() == 0
        sorting = page.get_by_role("button", name="Сортировка: Награда выше", exact=True)
        assert "is-active" in (sorting.get_attribute("class") or "")
        assert catalog.locator(".task-card h3").all_inner_texts() == [
            catalog_tasks[1]["title"],
            catalog_tasks[2]["title"],
            catalog_tasks[0]["title"],
        ]
        assert catalog.locator(".task-card .task-meta span").filter(has_text="создано").count() == 3

        search = page.get_by_label("Поиск по названию и описанию", exact=True)
        assert search.get_attribute("placeholder") == "Название или описание"
        search.fill("району")
        assert catalog.locator(".task-card h3").all_inner_texts() == [catalog_tasks[1]["title"]]
        assert page.get_by_role("button", name="Фильтры", exact=True).is_visible()

        catalog_url = page.url
        page.get_by_role("button", name="Фильтры", exact=True).click()
        filters = page.get_by_role("dialog", name="Активные фильтры", exact=True)
        filters.wait_for()
        assert page.url == catalog_url
        assert page.locator('[data-screen-id="T02"]').count() == 0
        assert filters.locator(".catalog-filter-heading").count() == 0
        assert filters.get_by_label("Поиск", exact=True).count() == 0
        for label in (
            "Тип задания",
            "Формат",
            "Категория",
            "Размер",
            "Мест от",
            "Награда от",
            "Срок до",
        ):
            assert filters.get_by_label(label, exact=True).is_visible()
        assert filters.get_by_label("Город", exact=True).is_hidden()
        assert filters.evaluate(
            "node => { const shell = document.querySelector('.shell').getBoundingClientRect(); "
            "const box = node.getBoundingClientRect(); "
            "return box.top - shell.top >= 55 && box.top - shell.top <= 70; }"
        )

        filters.get_by_label("Тип задания", exact=True).select_option("group")
        filters.get_by_label("Формат", exact=True).select_option("offline")
        assert filters.get_by_label("Город", exact=True).is_visible()
        filters.get_by_label("Категория", exact=True).select_option("Практическая помощь")
        filters.get_by_label("Размер", exact=True).select_option("m")
        filters.get_by_label("Мест от", exact=True).fill("3")
        filters.get_by_label("Награда от", exact=True).fill("7")
        filters.get_by_label("Срок до", exact=True).fill("2026-08-31")
        filters.get_by_label("Город", exact=True).fill("Буэнос")
        assert page.evaluate("document.documentElement.scrollWidth - innerWidth") == 0
        filters.get_by_role("button", name="Применить", exact=True).click()

        active_filters = page.get_by_role("button", name="Фильтры, выбрано: 8")
        active_filters.wait_for()
        assert catalog.locator(".task-card h3").all_inner_texts() == [catalog_tasks[1]["title"]]
        assert (
            page.get_by_label("Поиск по названию и описанию", exact=True).input_value() == "району"
        )
        assert page.get_by_role("button", name="Сортировка: Награда выше", exact=True).is_visible()

        active_filters.click()
        page.get_by_role("dialog", name="Активные фильтры", exact=True).get_by_role(
            "button", name="Сбросить", exact=True
        ).click()
        catalog.wait_for()
        assert catalog.locator(".task-card h3").all_inner_texts() == [catalog_tasks[1]["title"]]
        search = page.get_by_label("Поиск по названию и описанию", exact=True)
        assert search.input_value() == "району"
        search.fill("")
        assert catalog.locator(".task-card").count() == 3
        assert page.get_by_role("button", name="Фильтры", exact=True).is_visible()
        browser.close()


def test_ui_next_work_lists_replace_legacy_hubs_with_catalog_pattern(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    assignee_id = "00000000-0000-0000-0000-000000000310"
    assignment_id = "00000000-0000-0000-0000-000000000301"
    assignment = {
        "id": assignment_id,
        "task_id": "00000000-0000-0000-0000-000000000302",
        "task_title": "Проверить новый список выполняемых заданий",
        "task_origin": "community",
        "created_at": "2026-08-20T10:00:00Z",
        "category_name": "Практическая помощь",
        "task_kind": "solo",
        "time_size": "m",
        "format": "online",
        "city": None,
        "credit_reward_per_performer": 4,
        "performer_slots": 1,
        "minimum_level": 1,
        "deadline_at": "2026-08-29T20:00:00Z",
        "assignment_status": "accepted",
        "accepted_at": "2026-08-26T10:00:00Z",
        "submitted_at": None,
        "review_deadline_at": None,
        "reject_dispute_deadline_at": None,
        "reviewed_at": None,
        "task_deadline_at": "2026-08-29T20:00:00Z",
        "result_summary": None,
        "case_status": None,
    }
    later_assignment = {
        **assignment,
        "id": "00000000-0000-0000-0000-000000000307",
        "task_id": "00000000-0000-0000-0000-000000000308",
        "task_title": "Второе активное назначение",
        "created_at": "2026-08-22T10:00:00Z",
        "credit_reward_per_performer": 2,
        "deadline_at": "2026-09-03T20:00:00Z",
        "task_deadline_at": "2026-09-03T20:00:00Z",
    }
    active_owned = {
        "id": "00000000-0000-0000-0000-000000000303",
        "title": "Созданное активное задание",
        "status": "published",
        "created_at": "2026-08-21T10:00:00Z",
        "category_name": "Практическая помощь",
        "task_kind": "solo",
        "time_size": "m",
        "format": "online",
        "city": None,
        "credit_reward_per_performer": 4,
        "minimum_level": 1,
        "performer_slots": 2,
        "deadline_at": "2026-08-30T20:00:00Z",
        "archived_at": None,
        "archive_role": "created",
        "performed_status": None,
        "assignees": [
            {
                "member_id": assignee_id,
                "display_name": "Исполнитель",
                "status": "accepted",
            }
        ],
        "cancellation_status": None,
        "cancellation_action": "request",
    }
    archived_owned = {
        **active_owned,
        "id": "00000000-0000-0000-0000-000000000304",
        "title": "Созданное архивное задание",
        "status": "completed",
        "archived_at": "2026-08-01T12:00:00Z",
        "assignees": [],
        "cancellation_action": None,
    }
    later_active_owned = {
        **active_owned,
        "id": "00000000-0000-0000-0000-000000000306",
        "title": "Второе созданное задание",
        "created_at": "2026-08-23T10:00:00Z",
        "credit_reward_per_performer": 2,
        "deadline_at": "2026-09-05T20:00:00Z",
        "assignees": [],
    }
    cancelled_owned = {
        **archived_owned,
        "id": "00000000-0000-0000-0000-000000000309",
        "title": "Отменённое архивное задание",
        "status": "cancelled",
        "archived_at": "2026-08-10T12:00:00Z",
    }
    performed_owned = {
        **active_owned,
        "id": "00000000-0000-0000-0000-000000000311",
        "title": "Выполненное мной задание",
        "status": "published",
        "archived_at": "2026-08-12T12:00:00Z",
        "archive_role": "performed",
        "performed_status": "approved",
        "cancellation_action": None,
        "assignees": [
            {
                "member_id": assignee_id,
                "display_name": "Исполнитель",
                "status": "approved",
            }
        ],
    }
    review = {
        "id": "00000000-0000-0000-0000-000000000305",
        "task_id": active_owned["id"],
        "task_title": "Проверить результат исполнителя",
        "performer_display_name": "Мария",
        "submitted_at": "2026-08-26T11:00:00Z",
        "review_deadline_at": "2026-08-27T11:00:00Z",
        "result": "Готово",
        "available_decisions": ["full", "partial", "reject"],
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 375, "height": 812})
        page.route("**/api/v1/me", lambda route: route.fulfill(json={"member_id": "member"}))
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload()),
        )
        page.route(
            "**/api/v1/assignments?*",
            lambda route: route.fulfill(
                json={"items": [later_assignment, assignment], "next_cursor": None}
            ),
        )

        def owned_tasks_route(route: Route) -> None:
            scope = parse_qs(urlsplit(route.request.url).query).get("scope", ["created"])[0]
            items = (
                [performed_owned]
                if scope == "performed"
                else [
                    later_active_owned,
                    active_owned,
                    archived_owned,
                    cancelled_owned,
                ]
            )
            route.fulfill(json={"items": items})

        page.route("**/api/v1/owned-tasks**", owned_tasks_route)
        page.route(
            "**/api/v1/assignment-reviews",
            lambda route: route.fulfill(json={"items": [review]}),
        )
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )
        page.route(
            f"**/api/v1/members/{assignee_id}/avatar",
            lambda route: route.fulfill(
                body='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"/>',
                content_type="image/svg+xml",
            ),
        )

        page.goto(mini_app_url + "?theme=light#/tasks")
        page.locator('[data-home-action="taken"]').click()
        taken = page.locator('[data-screen-id="M01"][data-ui-engine="next-work-list"]')
        taken.wait_for()
        assert taken.get_by_role("heading", name="Что я выполняю", exact=True).is_visible()
        assert taken.locator(".root-tabs").count() == 0
        assert taken.get_by_text("Мои задания", exact=True).count() == 0
        taken_search = taken.get_by_label("Поиск в выполняемых заданиях", exact=True)
        assert taken_search.get_attribute("placeholder") == "Название задания"
        assert taken.locator(".work-task-card").count() == 2
        taken_filter = taken.get_by_role("button", name="Фильтры", exact=True)
        taken_sort = taken.get_by_role("button", name="Сортировка: Создано позже", exact=True)
        assert taken_filter.is_visible()
        assert taken_sort.is_visible()
        assert taken_search.bounding_box()["x"] < taken_filter.bounding_box()["x"]
        assert taken_filter.bounding_box()["x"] < taken_sort.bounding_box()["x"]
        taken_sort.click()
        assert page.get_by_role("radio", name="Создано раньше", exact=True).is_visible()
        assert page.get_by_role("radio", name="Награда выше", exact=True).is_visible()
        page.get_by_role("radio", name="Срок ближе", exact=True).click()
        assert taken.locator(".work-task-card h3").first.text_content() == (
            "Проверить новый список выполняемых заданий"
        )
        taken_filter.click()
        taken_filters = page.get_by_role("dialog", name="Активные фильтры", exact=True)
        for label in (
            "Тип задания",
            "Формат",
            "Категория",
            "Размер",
            "Мест от",
            "Награда от",
            "Срок до",
        ):
            assert taken_filters.get_by_label(label, exact=True).is_visible()
        taken_filters.get_by_label("Награда от", exact=True).fill("4")
        taken_filters.get_by_role("button", name="Применить", exact=True).click()
        assert taken.locator(".work-task-card").count() == 1
        taken.get_by_role("button", name="Фильтры, выбрано: 1", exact=True).click()
        page.get_by_role("dialog", name="Активные фильтры", exact=True).get_by_role(
            "button", name="Сбросить", exact=True
        ).click()
        taken_search.fill("несуществующее")
        assert taken.get_by_text("По вашему запросу ничего не найдено.", exact=True).is_visible()
        taken_search.fill("новый список")
        assert taken.locator(".work-task-card").count() == 1

        taken.get_by_role("button", name="Назад к заданиям", exact=True).click()
        page.locator('[data-screen-id="UX02"]').wait_for()
        page.locator('[data-home-action="created"]').click()
        created = page.locator('[data-screen-id="M09"][data-ui-engine="next-work-list"]')
        created.wait_for()
        assert created.get_by_role("heading", name="Созданные мной", exact=True).is_visible()
        assert created.locator(".root-tabs").count() == 0
        assert created.get_by_text("Созданное активное задание", exact=True).is_visible()
        assert created.get_by_text("Созданное архивное задание", exact=True).count() == 0
        assert created.get_by_text("Требуется проверка", exact=True).is_visible()
        created_search = created.get_by_label("Поиск в созданных заданиях", exact=True)
        created_filter = created.get_by_role("button", name="Фильтры", exact=True)
        sort_button = created.get_by_role("button", name="Сортировка: Создано позже", exact=True)
        assert created_filter.is_visible()
        assert sort_button.is_visible()
        assert created_search.bounding_box()["x"] < created_filter.bounding_box()["x"]
        assert created_filter.bounding_box()["x"] < sort_button.bounding_box()["x"]
        sort_button.click()
        assert page.get_by_role("radio", name="Создано раньше", exact=True).is_visible()
        assert page.get_by_role("radio", name="Награда ниже", exact=True).is_visible()
        page.get_by_role("radio", name="Срок ближе", exact=True).click()
        assert created.locator(".owned-work-card h3").first.text_content() == (
            "Созданное активное задание"
        )
        created_search.fill("Мария")
        assert created.locator(".work-task-card").count() == 1
        assert created.get_by_text("Проверить результат исполнителя", exact=True).is_visible()

        created_search.fill("Созданное активное")
        created.locator(".owned-work-card").click()
        page.locator(".owned-task-assignee .person-avatar-photo").wait_for()
        assert page.get_by_role(
            "button", name="Назад к созданным заданиям", exact=True
        ).is_visible()
        assert page.get_by_role("button", name="Закрыть карточку задания").count() == 0
        page.get_by_role("button", name="Назад к созданным заданиям", exact=True).click()
        created.wait_for()

        created.get_by_role("button", name="Назад к заданиям", exact=True).click()
        page.locator('[data-home-action="archive"]').click()
        archive = page.locator(
            '[data-screen-id="M09"][data-ui-engine="next-work-list"][data-list-scope="archive"]'
        )
        archive.wait_for()
        assert page.url.endswith("#/work?view_state=m09&scope=archive")
        assert archive.get_by_role("heading", name="Архив заданий", exact=True).count() == 0
        assert archive.get_by_text("Созданное архивное задание", exact=True).is_visible()
        assert archive.get_by_text("Отменённое архивное задание", exact=True).is_visible()
        assert archive.get_by_text("Созданное активное задание", exact=True).count() == 0
        created_archive_tab = archive.get_by_role("button", name="Созданные", exact=True)
        performed_archive_tab = archive.get_by_role("button", name="Выполненные", exact=True)
        assert created_archive_tab.get_attribute("aria-pressed") == "true"
        assert performed_archive_tab.get_attribute("aria-pressed") == "false"
        assert archive.get_by_role("button", name="Фильтры архива", exact=True).is_visible()
        assert archive.get_by_role(
            "button", name="Сортировка: Недавно в архиве", exact=True
        ).is_visible()
        performed_archive_tab.click()
        archive.get_by_text("Выполненное мной задание", exact=True).wait_for()
        assert page.url.endswith("#/work?view_state=m09&scope=archive&archive_view=performed")
        assert archive.get_by_text("Созданное архивное задание", exact=True).count() == 0
        assert archive.get_by_role("button", name="Фильтры архива", exact=True).count() == 0
        assert archive.get_by_text("Ваш результат: Принято", exact=True).is_visible()
        archive.locator(".owned-work-card").click()
        assert page.get_by_text("Выполнено вами", exact=True).is_visible()
        assert page.get_by_role("button", name="Назад в архив", exact=True).is_visible()
        assert page.get_by_role("button", name="Отменить задание", exact=True).count() == 0
        page.get_by_role("button", name="Назад в архив", exact=True).click()
        archive.get_by_text("Выполненное мной задание", exact=True).wait_for()
        assert (
            archive.get_by_role("button", name="Выполненные", exact=True).get_attribute(
                "aria-pressed"
            )
            == "true"
        )
        archive.get_by_role("button", name="Созданные", exact=True).click()
        archive.get_by_text("Созданное архивное задание", exact=True).wait_for()
        archive.get_by_role("button", name="Фильтры архива", exact=True).click()
        page.get_by_role("heading", name="Фильтры архива", exact=True).wait_for()
        page.get_by_label("Добавлено в архив до", exact=True).fill("2026-08-07")
        page.get_by_role("button", name="Применить", exact=True).click()
        assert archive.get_by_text("Созданное архивное задание", exact=True).is_visible()
        assert archive.get_by_text("Отменённое архивное задание", exact=True).count() == 0
        browser.close()


@pytest.mark.parametrize("viewport", [(375, 812), (430, 932)])
def test_get_cache_navigation_ttl_dedup_and_invalidation(  # noqa: PLR0915
    mini_app_url: str,
    viewport: tuple[int, int],
) -> None:
    me, member = _cache_profile()
    task = {
        "id": "task-cache-old",
        "title": "Сохранённый каталог",
        "description": "Старое содержимое остаётся видимым.",
        "credit_reward_per_performer": 5,
        "performer_slots": 1,
        "deadline_at": "2026-08-21T20:00:00Z",
        "origin": "community",
    }
    refreshed_task = {**task, "id": "task-cache-new", "title": "Обновлённый каталог"}
    task_requests = 0
    pending: list[Route] = []

    def tasks_route(route: Route) -> None:
        nonlocal task_requests
        task_requests += 1
        if task_requests in {2, 3}:
            pending.append(route)
        elif task_requests == 4:
            route.fulfill(status=401, json={"code": "unauthorized"})
        else:
            payload = task if task_requests == 1 else refreshed_task
            route.fulfill(json={"items": [payload], "next_cursor": None})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
        page.add_init_script(
            "let cacheNow = 1000; Date.now = () => cacheNow; "
            "globalThis.advanceCacheClock = value => { cacheNow += value; };"
        )
        page.route("**/api/v1/me", lambda route: route.fulfill(json=me))
        page.route("**/api/v1/members/*", lambda route: route.fulfill(json=member))
        page.route("**/api/v1/tasks", tasks_route)
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload(empty=True)),
        )
        page.route("**/api/v1/me/profile", lambda route: route.fulfill(json=me))

        def open_profile() -> None:
            page.get_by_role("button", name="Параметры", exact=True).click()
            page.locator(".settings-list").wait_for()
            page.get_by_role("button", name="Профиль", exact=False).click()
            page.locator(".profile-overview").wait_for()

        def open_catalog() -> None:
            page.get_by_role("button", name="Задания", exact=True).click()
            page.locator('[data-screen-id="UX02"]').wait_for()
            page.get_by_role("button", name=re.compile("Найти задание")).click()
            page.locator('[data-screen-id="T01"]').wait_for()

        page.goto(mini_app_url + "#/catalog?view_state=t01")
        page.get_by_text("Сохранённый каталог", exact=True).wait_for()
        open_profile()
        page.locator("h2", has_text="Алекс").wait_for()
        open_catalog()
        assert page.get_by_text("Сохранённый каталог", exact=True).is_visible()
        assert page.get_by_text("Загружаем задания…").count() == 0
        assert task_requests == 1
        open_profile()
        assert page.locator("h2", has_text="Алекс").is_visible()
        assert page.get_by_text("Загружаем профиль…").count() == 0
        page.evaluate("advanceCacheClock(60001)")
        open_catalog()
        assert page.get_by_text("Сохранённый каталог", exact=True).is_visible()
        assert page.get_by_text("Загружаем задания…").count() == 0
        assert task_requests == 2
        pending.pop(0).fulfill(json={"items": [refreshed_task], "next_cursor": None})
        page.get_by_text("Обновлённый каталог", exact=True).wait_for()

        open_profile()
        page.get_by_role("button", name="Изменить имя", exact=True).click()
        page.get_by_role("textbox", name="Имя", exact=True).fill("Алекс")
        page.get_by_role("button", name="Сохранить").click()
        page.get_by_role("button", name="Изменить имя", exact=True).wait_for()
        page.locator("h2", has_text="Алекс").wait_for()
        page.get_by_role("button", name="Задания", exact=True).click()
        page.locator('[data-screen-id="UX02"]').wait_for()
        page.get_by_role("button", name=re.compile("Найти задание")).click()
        assert task_requests == 3
        pending.pop(0).fulfill(json={"items": [refreshed_task], "next_cursor": None})
        page.locator('[data-screen-id="T01"]').wait_for()
        page.get_by_text("Обновлённый каталог", exact=True).wait_for()

        open_profile()
        page.evaluate("advanceCacheClock(60001)")
        open_catalog()
        assert page.get_by_text("Обновлённый каталог", exact=True).is_visible()
        assert task_requests == 4
        page.wait_for_timeout(50)
        open_profile()
        page.locator("h2", has_text="Алекс").wait_for()
        open_catalog()
        page.get_by_text("Обновлённый каталог", exact=True).wait_for()
        assert task_requests == 5
        browser.close()


def test_assignment_action_eligibility_is_server_projected() -> None:
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'assignment.assignment_status === "accepted"' not in source
    assert "if (assignment.can_submit)" in source
    assert "if (assignment.can_cancel)" in source


def test_telegram_profile_photo_is_shared_persistent_and_keeps_initials_fallback(
    mini_app_url: str,
) -> None:
    me, member = _cache_profile("00000000-0000-0000-0000-000000000133")
    avatar_path = f"/api/v1/members/{me['member_id']}/avatar"
    avatar_requests: list[str] = []

    def avatar(route: Route) -> None:
        avatar_requests.append(urlsplit(route.request.url).path)
        route.fulfill(
            body='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"/>',
            content_type="image/svg+xml",
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 375, "height": 812})
        page.route("**/api/v1/me", lambda route: route.fulfill(json=me))
        page.route("**/api/v1/members/*", lambda route: route.fulfill(json=member))
        page.route(
            "**/api/v1/members?*",
            lambda route: route.fulfill(json={"items": [member], "next_cursor": None}),
        )
        page.route(f"**{avatar_path}", avatar)
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route("**/api/v1/task-home", lambda route: route.fulfill(json=_task_home_payload()))
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )
        page.goto(mini_app_url + "#/profile")
        image = page.locator(".profile-identity-card .person-avatar-photo")
        image.wait_for()
        assert image.get_attribute("src", timeout=1000).startswith("blob:")
        assert image.evaluate("node => getComputedStyle(node).objectFit") == "cover"
        avatar_node = page.locator(".profile-identity-card .person-avatar")
        assert avatar_requests == [avatar_path]
        assert avatar_node.evaluate("node => getComputedStyle(node).borderRadius") == "50%"
        assert avatar_node.evaluate("node => node.offsetWidth === node.offsetHeight")
        assert avatar_node.text_content() == "\N{CYRILLIC CAPITAL LETTER A}"

        page.reload()
        page.locator(".profile-identity-card .person-avatar-photo").wait_for()
        assert avatar_requests == [avatar_path]

        page.get_by_role("button", name="Комьюнити", exact=True).click()
        page.get_by_role("button", name="Люди", exact=True).click()
        page.locator(".member-row .person-avatar-photo").wait_for()
        assert avatar_requests == [avatar_path]
        page.locator(".member-row").click()
        page.locator(".foreign-profile .person-avatar-photo").wait_for()
        assert avatar_requests == [avatar_path]

        avatar_node = page.locator(".foreign-profile .person-avatar")
        image = page.locator(".foreign-profile .person-avatar-photo")
        assert avatar_node.evaluate("node => getComputedStyle(node).borderRadius") == "50%"
        assert avatar_node.evaluate("node => node.offsetWidth === node.offsetHeight")
        assert avatar_node.text_content() == "\N{CYRILLIC CAPITAL LETTER A}"

        missing_avatar = "/api/v1/members/missing/avatar"
        page.route(f"**{missing_avatar}", lambda route: route.abort())
        page.evaluate(
            "document.querySelector('.foreign-profile .person-avatar-photo').src="
            f"'{missing_avatar}'"
        )
        image.wait_for(state="detached")
        assert avatar_node.text_content() == "\N{CYRILLIC CAPITAL LETTER A}"
        browser.close()


def test_profile_avatar_picker_crops_uploads_and_restores_telegram(  # noqa: PLR0915
    mini_app_url: str,
    tmp_path: Path,
) -> None:
    me, member = _cache_profile("00000000-0000-0000-0000-000000000134")
    source = tmp_path / "wide-avatar.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="600">'
        '<rect width="900" height="600" fill="#6547ff"/>'
        '<circle cx="450" cy="300" r="180" fill="#d9ff57"/></svg>',
        encoding="utf-8",
    )
    telegram_source = tmp_path / "telegram-avatar.svg"
    telegram_source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512">'
        '<rect width="512" height="512" fill="#1ea7fd"/></svg>',
        encoding="utf-8",
    )
    custom = False
    avatar_mutations: list[tuple[str, str, int]] = []

    def preference(route: Route) -> None:
        nonlocal custom
        method = route.request.method
        if method == "PUT":
            body = route.request.post_data_buffer or b""
            avatar_mutations.append(
                (method, route.request.headers.get("content-type", ""), len(body))
            )
            custom = True
            route.fulfill(json={"custom": True, "revision": 1})
        elif method == "DELETE":
            avatar_mutations.append((method, "", 0))
            custom = False
            route.fulfill(json={"custom": False, "revision": None})
        else:
            route.fulfill(json={"custom": custom, "revision": 1 if custom else None})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 375, "height": 812})
        page.route("**/api/v1/me", lambda route: route.fulfill(json=me))
        page.route("**/api/v1/me/avatar", preference)
        page.route("**/api/v1/members/*", lambda route: route.fulfill(json=member))
        page.route(
            "**/api/v1/members/*/avatar",
            lambda route: route.fulfill(
                body=(source if custom else telegram_source).read_bytes(),
                content_type="image/svg+xml",
                headers={"Cache-Control": "private, max-age=900"},
            ),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route("**/api/v1/task-home", lambda route: route.fulfill(json=_task_home_payload()))
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )
        page.goto(mini_app_url + "#/profile")
        profile_photo = page.locator(".profile-identity-card .person-avatar-photo")
        profile_photo.wait_for()
        assert "#1ea7fd" in profile_photo.evaluate(
            "async image => await (await fetch(image.src)).text()"
        )
        page.get_by_role("button", name="Изменить фото профиля").click()
        page.locator("#profile-editor-sheet-title").wait_for()
        page.locator(".avatar-file-input").first.set_input_files(source)
        crop = page.locator(".avatar-crop-canvas")
        crop.wait_for()
        assert crop.evaluate("node => node.offsetWidth === node.offsetHeight")
        page.get_by_role("slider", name="Масштаб фотографии").fill("1.45")
        with page.expect_request(
            lambda request: request.url.endswith("/api/v1/me/avatar") and request.method == "PUT"
        ):
            page.get_by_role("button", name="Сохранить", exact=True).click()
        page.locator(".profile-editor-backdrop").wait_for(state="detached")

        assert len(avatar_mutations) == 1
        assert avatar_mutations[0][0] == "PUT"
        assert avatar_mutations[0][1].startswith("image/jpeg")
        assert avatar_mutations[0][2] > 1000
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        profile_photo = page.locator(".profile-identity-card .person-avatar-photo")
        profile_photo.wait_for()
        assert "#6547ff" in profile_photo.evaluate(
            "async image => await (await fetch(image.src)).text()"
        )

        page.get_by_role("button", name="Изменить фото профиля").click()
        restore = page.get_by_role("button", name="Вернуть фото из Telegram")
        restore.wait_for()
        with page.expect_request(
            lambda request: request.url.endswith("/api/v1/me/avatar") and request.method == "DELETE"
        ):
            restore.click()
        page.locator(".profile-editor-backdrop").wait_for(state="detached")
        assert avatar_mutations[-1][0] == "DELETE"
        profile_photo = page.locator(".profile-identity-card .person-avatar-photo")
        profile_photo.wait_for()
        assert "#1ea7fd" in profile_photo.evaluate(
            "async image => await (await fetch(image.src)).text()"
        )
        assert 'fetch(request, forceNetwork ? { cache: "reload" } : undefined)' in (
            STATIC_DIR / "app.js"
        ).read_text(encoding="utf-8")
        browser.close()


@pytest.mark.parametrize("viewport", [(375, 812), (430, 932)])
def test_profile_contract_links_back_focus_and_no_visible_reliability(  # noqa: C901, PLR0915
    mini_app_url: str,
    viewport: tuple[int, int],
    tmp_path: Path,
) -> None:
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert not any(
        token in source
        for token in ("reliabilityText", "reliabilityPercent", "Надёжность", ".reliability")
    )
    owner_id = "00000000-0000-0000-0000-000000000107"
    foreign_id = "00000000-0000-0000-0000-000000000108"
    link_id = "00000000-0000-0000-0000-000000000109"
    me: dict[str, Any] = {
        "member_id": owner_id,
        "telegram_username": "Alex_Test",
        "display_name": "Alex Oxitocin",
        "city": "Буэнос-Айрес",
        "short_bio": "Я ИИ-инженер и помогаю командам проектировать понятные продукты.",
        "skill_tags": ["AI agents", "Python", "Архитектура"],
        "profile_links": [
            {"id": link_id, "label": "LinkedIn", "url": "https://linkedin.com/in/alex"},
        ],
        "credit_balance": 4,
        "experience_total": 12,
        "level": {"number": 1, "display_name": "Первый шаг"},
        "statistics": {"completed_tasks": 8, "created_tasks": 5},
    }
    owner = {
        "member_id": owner_id,
        "telegram_username": "Alex_Test",
        "display_name": "Alex Oxitocin",
        "city": "Буэнос-Айрес",
        "short_bio": me["short_bio"],
        "skill_tags": me["skill_tags"],
        "profile_links": me["profile_links"],
        "experience_total": 12,
        "level_number": 1,
        "karma": {"score": 3, "count": 4},
        "reliability": {"accepted": 4, "approved_weight": "3", "no_show": 0, "rate": "0.75"},
        "can_rate_karma": False,
    }
    foreign = {
        **owner,
        "member_id": foreign_id,
        "telegram_username": "Foreign_User",
        "display_name": "Мария Крылова",
        "city": None,
        "short_bio": "Помогаю запускать сообщества.",
        "skill_tags": [],
        "can_rate_karma": True,
    }
    mutation_requests: list[dict[str, Any]] = []
    mutation_keys: list[str] = []
    fail_next_profile = {"value": False}

    def profile_update(route: Route) -> None:
        body = route.request.post_data_json
        assert isinstance(body, dict)
        mutation_requests.append(body)
        mutation_keys.append(route.request.headers["idempotency-key"])
        if fail_next_profile["value"]:
            fail_next_profile["value"] = False
            route.fulfill(status=502, body="retry", content_type="text/plain")
            return
        field = body["field"]
        if field == "profile_links":
            action = body["action"]
            if action == "delete":
                me["profile_links"] = [
                    item for item in me["profile_links"] if item["id"] != body["link_id"]
                ]
            elif action == "update":
                me["profile_links"] = [
                    {**item, "label": body["label"], "url": body["url"]}
                    if item["id"] == body["link_id"]
                    else item
                    for item in me["profile_links"]
                ]
            else:
                me["profile_links"] = [
                    *me["profile_links"],
                    {
                        "id": "00000000-0000-0000-0000-000000000110",
                        "label": body["label"],
                        "url": body["url"],
                    },
                ]
        elif field == "skill_tags":
            me[field] = [item for item in body["value"].splitlines() if item]
        else:
            me[field] = body["value"].strip()
        route.fulfill(json=me)

    evidence_root = tmp_path / "browser-evidence"
    viewport_name = f"{viewport[0]}x{viewport[1]}"
    capture_dir = evidence_root / viewport_name
    capture_dir.mkdir(parents=True, exist_ok=True)
    journey: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        bridge = (
            "globalThis.nativeLinks=[];globalThis.Telegram={WebApp:{ready(){},expand(){},"
            "openLink(url){nativeLinks.push(['openLink',url])},"
            "openTelegramLink(url){nativeLinks.push(['openTelegramLink',url])}}};"
        )
        page = _new_page(browser, bridge=bridge)
        page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
        page.route("**/api/v1/me", lambda route: route.fulfill(json=me))
        page.route("**/api/v1/me/profile", profile_update)
        page.route(f"**/api/v1/members/{owner_id}", lambda route: route.fulfill(json=owner))
        page.route(f"**/api/v1/members/{foreign_id}", lambda route: route.fulfill(json=foreign))
        page.route(
            "**/api/v1/members?*",
            lambda route: route.fulfill(json={"items": [foreign], "next_cursor": None}),
        )
        page.route(
            "**/api/v1/tasks", lambda route: route.fulfill(json={"items": [], "next_cursor": None})
        )
        page.route("**/api/v1/task-home", lambda route: route.fulfill(json=_task_home_payload()))
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )

        def capture(number: int, slug: str, assertion: str, focus: str | None = None) -> None:
            page.wait_for_timeout(30)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.get_by_text("Надёжность", exact=True).count() == 0
            if focus:
                assert page.locator(focus).evaluate("node => node === document.activeElement")
            path = capture_dir / f"{number:02d}-{slug}.png"
            page.screenshot(path=str(path))
            journey.append(
                {
                    "viewport": viewport_name,
                    "screen": number,
                    "route": page.url.split("#", 1)[-1],
                    "assertion": assertion,
                    "focus": focus,
                    "pass": True,
                }
            )

        page.goto(mini_app_url + "?case=own#/profile")
        page.get_by_role("heading", name="Alex Oxitocin").wait_for()
        assert page.get_by_text("@Alex_Test", exact=True).is_visible()
        assert page.get_by_text("Кредиты", exact=True).is_visible()
        assert page.get_by_text("Завершено заданий", exact=True).count() == 0
        assert page.locator(".profile-pencil").count() == 0
        for action in (
            "Изменить имя",
            "Изменить город",
            "Изменить о себе",  # noqa: RUF001
            "Изменить навыки",
            "Изменить ссылки",
        ):
            assert page.get_by_role("button", name=action, exact=True).is_visible()
        capture(1, "own-filled", "PR-01")

        page.goto(mini_app_url + f"?case=foreign#/members/{foreign_id}")
        page.get_by_role("heading", name="Мария Крылова").wait_for()
        assert page.get_by_text("Кредиты", exact=True).count() == 0
        assert page.get_by_role("button", name="Оценить карму").is_visible()
        page.get_by_role("button", name="@Foreign_User ↗").click()
        assert page.evaluate("nativeLinks.at(-1)[0]") == "openTelegramLink"
        page.evaluate(
            "Telegram.WebApp.openTelegramLink=()=>{throw new Error('native')};"
            "Telegram.WebApp.openLink=(url)=>nativeLinks.push(['openLink',url])"
        )
        page.get_by_role("button", name="@Foreign_User ↗").click()
        assert page.evaluate("nativeLinks.at(-1)[0]") == "openLink"
        page.evaluate(
            "Telegram.WebApp.openLink=()=>{throw new Error('native')};"
            "globalThis.open=(...args)=>{globalThis.fallbackArgs=args;return {}}"
        )
        page.locator(".public-link-row").click()
        assert page.evaluate("fallbackArgs") == [
            "https://linkedin.com/in/alex",
            "_blank",
            "noopener,noreferrer",
        ]
        page.evaluate(
            "Telegram.WebApp.openLink=undefined;Telegram.WebApp.openTelegramLink=undefined;"
            "globalThis.open=(...args)=>{globalThis.fallbackArgs=args;return {}}"
        )
        page.get_by_role("button", name="@Foreign_User ↗").click()
        assert page.evaluate("fallbackArgs") == [
            "https://t.me/Foreign_User",
            "_blank",
            "noopener,noreferrer",
        ]
        capture(2, "foreign", "PR-02")
        foreign["telegram_username"] = "bad!"
        page.reload()
        page.get_by_role("heading", name="Мария Крылова").wait_for()
        page.get_by_role("button", name=re.compile(r"^@")).wait_for(state="detached")
        assert page.get_by_role("button", name=re.compile(r"^@")).count() == 0
        foreign["telegram_username"] = None
        page.reload()
        page.get_by_role("heading", name="Мария Крылова").wait_for()
        page.get_by_role("button", name=re.compile(r"^@")).wait_for(state="detached")
        assert page.get_by_role("button", name=re.compile(r"^@")).count() == 0
        foreign.update(telegram_username="Foreign_User", can_rate_karma=False)
        page.reload()
        page.get_by_role("heading", name="Мария Крылова").wait_for()
        assert page.get_by_role("button", name="Оценить карму").count() == 0
        foreign["can_rate_karma"] = True

        me.update(short_bio=None, skill_tags=[], profile_links=[])
        page.goto(mini_app_url + "?case=partial#/profile")
        page.get_by_role("button", name="Изменить о себе", exact=True).wait_for()  # noqa: RUF001
        for label in ("Изменить о себе", "Изменить навыки", "Изменить ссылки"):  # noqa: RUF001
            assert page.get_by_role("button", name=label, exact=True).is_visible()
        for label in ("Добавить описание", "Добавить навыки", "Добавить ссылки"):
            assert page.get_by_text(label, exact=True).is_visible()
        capture(3, "own-partial", "PR-03")
        me.update(
            short_bio="Я ИИ-инженер и помогаю командам проектировать понятные продукты.",
            skill_tags=["AI agents", "Python", "Архитектура"],
        )

        before_back = len(mutation_requests)
        page.goto(mini_app_url + "?case=name#/profile/edit/name")
        page.get_by_role("textbox", name="Имя", exact=True).wait_for()
        page.reload()
        page.get_by_role("textbox", name="Имя", exact=True).wait_for()
        assert page.get_by_text(
            "Это имя увидят другие участники в профиле и заданиях.", exact=True
        ).is_visible()
        assert page.get_by_role("button", name="Отмена").count() == 0
        capture(4, "name", "PR-04", "input[required]")
        page.get_by_role("textbox", name="Имя", exact=True).fill("Несохранённое имя")
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Alex Oxitocin").wait_for()
        assert len(mutation_requests) == before_back

        page.goto(mini_app_url + "?case=city#/profile/edit/city")
        page.get_by_role("textbox", name="Город", exact=True).wait_for()
        capture(5, "city", "PR-05", "input[required]")

        page.goto(mini_app_url + "?case=bio#/profile/edit/bio")
        page.reload()
        bio = page.get_by_role("textbox", name="Описание", exact=True)
        bio.wait_for()
        assert page.locator("#screen-title").text_content() == "О себе"  # noqa: RUF001
        assert bio.input_value() == me["short_bio"]
        assert page.get_by_text(
            "Чем вы занимаетесь и чем можете быть полезны сообществу.", exact=True
        ).is_visible()
        capture(6, "bio", "PR-06", "textarea")

        page.goto(mini_app_url + "?case=skills#/profile/edit/skills")
        page.reload()
        skill_input = page.locator('input[maxlength="50"]')
        skill_input.wait_for()
        assert page.locator(".skill-draft-row strong").all_text_contents() == [
            "AI agents",
            "Python",
            "Архитектура",
        ]
        page.get_by_role("button", name="Удалить навык Архитектура").click()
        assert page.get_by_text("2 / 20 навыков", exact=True).is_visible()
        skill_input.fill("Архитектура")
        page.get_by_role("button", name="Добавить навык").click()
        assert page.get_by_text("3 / 20 навыков", exact=True).is_visible()
        skill_input.fill("python")
        page.get_by_role("button", name="Добавить навык").click()
        assert page.get_by_text("Такой навык уже добавлен.", exact=True).is_visible()
        page.get_by_role("button", name="Сохранить", exact=True).click()
        page.get_by_role("heading", name="Alex Oxitocin").wait_for()
        assert mutation_requests[-1] == {
            "field": "skill_tags",
            "value": "\n".join(me["skill_tags"]),
        }
        assert page.locator(".profile-chips span").all_text_contents() == [
            "AI agents",
            "Python",
            "Архитектура",
        ]
        page.goto(mini_app_url + "?case=skills-limit#/profile/edit/skills")
        skill_input = page.locator('input[maxlength="50"]')
        skill_input.wait_for()
        assert page.evaluate(
            "document.documentElement.scrollWidth === document.documentElement.clientWidth"
        )
        assert page.locator(".profile-editor").evaluate(
            "node => node.scrollWidth === node.clientWidth"
        )
        assert page.get_by_role("button", name="Назад").evaluate(
            "node => { const box=node.getBoundingClientRect();"
            " return box.left >= 0 && box.right <= innerWidth }"
        )
        capture(7, "skills", "PR-07", 'input[maxlength="50"]')
        for index in range(17):
            skill_input.fill(f"Навык {index}")
            page.get_by_role("button", name="Добавить навык").click()
        assert page.get_by_text("20 / 20 навыков", exact=True).is_visible()
        skill_input.fill("Лишний навык")
        page.get_by_role("button", name="Добавить навык").click()
        assert page.get_by_text("Проверьте навык или лимит 20.", exact=True).is_visible()
        page.reload()
        page.locator('input[maxlength="50"]').wait_for()
        assert page.locator(".skill-draft-row strong").all_text_contents() == [
            "AI agents",
            "Python",
            "Архитектура",
        ]

        me.update(
            short_bio="Я ИИ-инженер и помогаю командам проектировать понятные продукты.",
            skill_tags=["AI agents", "Python", "Архитектура"],
            profile_links=[
                {"id": link_id, "label": "LinkedIn", "url": "https://linkedin.com/in/alex"}
            ],
        )
        page.goto(mini_app_url + "?case=links#/profile/links")
        page.locator(".profile-links-manager").wait_for()
        assert page.locator(".link-trash").count() == 1
        capture(8, "links", "PR-08")
        page.get_by_role("button", name="Удалить ссылку LinkedIn").click()
        dialog = page.get_by_role("dialog")
        dialog.wait_for()
        assert page.locator("#screen-title").evaluate("node => node.inert")
        assert page.locator("#back").is_enabled()
        page.keyboard.press("Tab")
        assert dialog.get_by_role("button", name="Удалить", exact=True).evaluate(
            "node => node === document.activeElement"
        )
        page.keyboard.press("Shift+Tab")
        assert dialog.get_by_role("button", name="Удалить", exact=True).evaluate(
            "node => node === document.activeElement"
        )
        page.get_by_role("button", name="Назад").click()
        page.locator(".profile-links-manager").wait_for()
        page.wait_for_function(f"document.activeElement?.dataset.linkTrashId === '{link_id}'")
        assert page.get_by_role("button", name="Удалить ссылку LinkedIn").evaluate(
            "node => node === document.activeElement"
        )

        page.goto(mini_app_url + "?case=link-new#/profile/links/new")
        page.get_by_role("textbox", name="Название", exact=True).wait_for()
        page.reload()
        page.get_by_role("button", name="LinkedIn", exact=True).click()
        page.locator('input[type="url"]').fill("https://linkedin.com/in/alex")
        assert page.get_by_text(
            "Только полный адрес, начинающийся с https://",  # noqa: RUF001
            exact=True,
        ).is_visible()
        page.locator('input[maxlength="32"]').focus()
        capture(9, "link-new", "PR-09", 'input[maxlength="32"]')

        page.goto(mini_app_url + f"?case=link-edit#/profile/links/{link_id}")
        page.get_by_role("button", name="Удалить", exact=True).wait_for()
        page.reload()
        page.get_by_role("button", name="Удалить", exact=True).wait_for()
        assert page.get_by_role("button", name="Сохранить", exact=True).count() == 1
        capture(10, "link-edit", "PR-10", 'input[maxlength="32"]')
        page.get_by_role("button", name="Удалить", exact=True).click()
        page.get_by_role("dialog").wait_for()
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("button", name="Удалить", exact=True).wait_for()
        page.wait_for_function(f"document.activeElement?.dataset.linkDeleteId === '{link_id}'")
        assert page.get_by_role("button", name="Удалить", exact=True).evaluate(
            "node => node === document.activeElement"
        )
        page.goto(mini_app_url + f"?case=direct-confirm#/profile/links/{link_id}/delete")
        page.get_by_role("dialog").wait_for()
        page.reload()
        page.get_by_role("dialog").wait_for()
        page.get_by_role("button", name="Назад").click()
        page.locator(".profile-links-manager").wait_for()
        page.wait_for_function(f"document.activeElement?.dataset.linkId === '{link_id}'")
        assert page.get_by_role("button", name="Изменить ссылку LinkedIn").evaluate(
            "node => node === document.activeElement"
        )
        page.goto(mini_app_url + f"?case=direct-confirm-capture#/profile/links/{link_id}/delete")
        page.get_by_role("dialog").wait_for()
        page.reload()
        page.get_by_role("dialog").wait_for()
        capture(11, "link-delete-confirm", "PR-11", ".profile-confirm-sheet .profile-delete-large")
        page.get_by_role("dialog").get_by_role("button", name="Удалить", exact=True).click()
        page.locator(".profile-links-manager").wait_for()
        assert mutation_requests[-1] == {
            "field": "profile_links",
            "action": "delete",
            "link_id": link_id,
        }
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

        me["profile_links"] = [
            {
                "id": f"00000000-0000-0000-0000-{index:012d}",
                "label": f"Link {index}",
                "url": f"https://example.com/{index}",
            }
            for index in range(1, 6)
        ]
        page.goto(mini_app_url + "?case=max-five#/profile/links")
        page.locator(".profile-links-manager").wait_for()
        assert page.locator(".managed-link-copy strong").all_text_contents() == [
            "Link 1",
            "Link 2",
            "Link 3",
            "Link 4",
            "Link 5",
        ]
        assert page.get_by_role("button", name="Добавить ссылку").count() == 0

        before_retry = len(mutation_requests)
        page.goto(mini_app_url + "?case=retry#/profile/edit/name")
        name_input = page.get_by_role("textbox", name="Имя", exact=True)
        name_input.wait_for()
        name_input.fill("Новое имя")
        fail_next_profile["value"] = True
        page.get_by_role("button", name="Сохранить", exact=True).click()
        page.get_by_text(
            "Не удалось сохранить. Повторите попытку.",  # noqa: RUF001
            exact=True,
        ).wait_for()
        page.get_by_role("button", name="Сохранить", exact=True).click()
        page.get_by_role("heading", name="Новое имя").wait_for()
        assert len(mutation_requests) == before_retry + 2
        assert mutation_keys[-2] == mutation_keys[-1]
        page.goto(mini_app_url + "?case=new-key#/profile/edit/name")
        page.get_by_role("textbox", name="Имя", exact=True).fill("Ещё одно имя")
        page.get_by_role("button", name="Сохранить", exact=True).click()
        page.get_by_role("heading", name="Ещё одно имя").wait_for()
        assert mutation_keys[-1] != mutation_keys[-2]

        pending_member: list[Route] = []

        def hold_foreign(route: Route) -> None:
            pending_member.append(route)

        page.route(f"**/api/v1/members/{foreign_id}", hold_foreign)
        page.goto(mini_app_url + f"?case=late#/members/{foreign_id}")
        page.wait_for_timeout(50)
        assert len(pending_member) == 1
        page.goto(mini_app_url + "?case=late-own#/profile")
        page.get_by_role("heading", name="Ещё одно имя").wait_for()
        pending_member[0].fulfill(json=foreign)
        page.wait_for_timeout(50)
        assert page.get_by_role("heading", name="Ещё одно имя").is_visible()
        assert page.get_by_role("heading", name="Мария Крылова").count() == 0
        page.unroute(f"**/api/v1/members/{foreign_id}", hold_foreign)
        page.goto(mini_app_url + f"?case=direct-member#/members/{foreign_id}")
        page.get_by_role("heading", name="Мария Крылова").wait_for()
        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="P01"]').wait_for()
        browser.close()

    journey_path = evidence_root / "journey.json"
    existing = json.loads(journey_path.read_text(encoding="utf-8")) if journey_path.exists() else []
    existing = [item for item in existing if item.get("viewport") != viewport_name]
    journey_path.write_text(
        json.dumps([*existing, *journey], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_connected_concept_shell_and_legacy_absence(mini_app_url: str) -> None:
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    markup = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
    forbidden = (
        "globalThis.confirm",
        "renderPresentationScreen",
        "navigatePresentationScreen",
        "presentationContent",
        "renderCatalog",
        "renderAssignments",
        "renderProfile",
        "submission-preview",
        "app-header",
        'id="welcome"',
        "▣",
        "▤",
        "♙",
        "◇",
    )
    production = source + markup + styles
    assert {token: production.count(token) for token in forbidden} == dict.fromkeys(forbidden, 0)

    task = {
        "id": "00000000-0000-0000-0000-000000000097",
        "title": "Проверить доступность пандуса",
        "description": "Сделать три фотографии входа и коротко описать препятствия.",
        "credit_reward_per_performer": 5,
        "performer_slots": 1,
        "deadline_at": "2026-08-21T20:00:00Z",
        "origin": "community",
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width, height in ((375, 812), (430, 932)):
            page = _new_page(browser)
            page.set_viewport_size({"width": width, "height": height})
            page.route(
                "**/api/v1/me",
                lambda route: route.fulfill(
                    json={
                        "member_id": "me",
                        "display_name": "Алекс",
                        "city": None,
                        "timezone": "UTC",
                        "short_bio": None,
                        "current_goal": None,
                        "help_categories": [],
                        "skill_tags": [],
                        "availability": None,
                        "credit_balance": 0,
                        "experience_total": 0,
                        "level": {"number": 1, "display_name": "Новичок"},
                    }
                ),
            )
            page.route(
                "**/api/v1/moderation/cases?*",
                lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
            )
            page.route(
                "**/api/v1/tasks",
                lambda route: route.fulfill(json={"items": [task], "next_cursor": None}),
            )
            page.route(
                "**/api/v1/task-home",
                lambda route: route.fulfill(json=_task_home_payload()),
            )
            page.goto(mini_app_url)
            page.locator('[data-screen-id="UX02"][data-ui-engine="next-tasks-home"]').wait_for()
            page.get_by_role("button", name="Модерация").wait_for()
            assert page.get_by_role("navigation", name="Основное меню").get_by_role(
                "button"
            ).all_inner_texts() == [
                "Задания",
                "Комьюнити",
                "Параметры",
                "Модерация",
            ]
            geometry = page.evaluate(
                """() => {
                  const shell = document.querySelector('.shell');
                  const nav = document.querySelector('.bottom-nav');
                  const s = getComputedStyle(shell);
                  const n = getComputedStyle(nav);
                  const sr = shell.getBoundingClientRect();
                  const nr = nav.getBoundingClientRect();
                  return {
                    radius: s.borderRadius, border: s.borderTopWidth,
                    overflow: s.overflow, shellBottom: sr.bottom,
                    navBottom: nr.bottom, navHeight: nr.height,
                    navBorder: n.borderTopWidth,
                    icons: [...nav.querySelectorAll('svg.nav-icon')]
                      .filter(node => getComputedStyle(node).display !== 'none').length,
                    minTarget: Math.min(...[...nav.querySelectorAll('button')]
                      .map(node => node.getBoundingClientRect().height)),
                    overflowX: document.documentElement.scrollWidth - innerWidth,
                  };
                }"""
            )
            assert geometry == geometry | {
                "radius": "20px",
                "border": "1px",
                "overflow": "hidden",
                "navBorder": "1px",
                "icons": 4,
                "overflowX": 0,
            }
            assert abs(geometry["shellBottom"] - geometry["navBottom"]) <= 1
            assert 64 <= geometry["navHeight"] <= 96
            assert geometry["minTarget"] >= 56
            page.close()
        browser.close()


def test_catalog_actions_filters_and_list_density_are_compact(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    tasks = [
        {
            "id": f"00000000-0000-0000-0000-{index:012d}",
            "title": f"Задание {index}: помочь участнику сообщества",
            "description": (
                "Короткое публичное описание результата без переноса detail-полей "
                "в карточку списка."
            ),
            "credit_reward_per_performer": index + 1,
            "performer_slots": 1 + index % 2,
            "deadline_at": f"2026-08-{20 + index:02d}T20:00:00Z",
            "origin": "community",
            "author_display_name": "Сообщество",
            "category_name": "Продвижение" if index % 2 else "Практическая помощь",
            "task_kind": "solo" if index % 2 else "group",
            "format": "online" if index != 5 else "offline",
            "completion_criteria": "Результат проверяем по короткому списку условий.",
            "performer_instructions": "Откройте детали и выполните шаги.",
            "public_input": {},
            "materials": {},
        }
        for index in range(1, 6)
    ]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width, height in ((375, 812), (430, 932)):
            page = _new_page(browser)
            page.set_viewport_size({"width": width, "height": height})
            page.route(
                "**/api/v1/me",
                lambda route: route.fulfill(json={"member_id": "me", "display_name": "Алекс"}),
            )
            page.route(
                "**/api/v1/tasks",
                lambda route: route.fulfill(json={"items": tasks, "next_cursor": None}),
            )
            page.goto(mini_app_url + "#/catalog?view_state=t01")

            catalog = page.locator('[data-screen-id="T01"][data-state="content"]')
            catalog.wait_for()
            heading = page.get_by_role("heading", name="Задания", include_hidden=True)
            assert heading.count() == 1
            assert heading.evaluate(
                "node => { const box = node.parentElement.getBoundingClientRect(); "
                "return box.width <= 1 && box.height <= 1; }"
            )
            assert page.get_by_text("5 заданий доступно сейчас").count() == 0
            assert page.get_by_text("Доступно заданий: 5", exact=True).evaluate(
                "node => { const box = node.getBoundingClientRect(); "
                "return box.width <= 1 && box.height <= 1; }"
            )

            filters = page.get_by_role("button", name="Фильтры", exact=True)
            sort = page.get_by_role("button", name=re.compile("^Сортировка:"))
            assert filters.is_visible()
            assert sort.is_visible()
            assert page.get_by_role("button", name="+ Создать", exact=True).count() == 0
            cards = catalog.locator(".task-card")
            geometry = page.evaluate(
                """() => {
                  const nav = document.querySelector('.bottom-nav').getBoundingClientRect();
                  const rows = [...document.querySelectorAll('.catalog-view .task-card')]
                    .map(node => node.getBoundingClientRect());
                  return {
                    visibleCards: rows.filter(row => row.top >= 0 && row.bottom <= nav.top).length,
                    overflowX: document.documentElement.scrollWidth - innerWidth,
                  };
                }"""
            )
            assert geometry["visibleCards"] == (4 if width == 375 else 5), geometry
            assert geometry["overflowX"] == 0
            assert cards.count() == 5

            filters.click()
            page.get_by_role("heading", name="Активные фильтры").wait_for()
            page.get_by_role("button", name="Закрыть фильтры").click()
            catalog.wait_for()
            page.get_by_role("button", name="Фильтры", exact=True).click()
            page.get_by_label("Формат").select_option("online")
            page.get_by_label("Награда от").fill("3")
            page.get_by_role("button", name="Применить").click()
            active_filters = page.get_by_role("button", name="Фильтры, выбрано: 2")
            active_filters.wait_for()
            assert active_filters.locator(".catalog-filter-count").inner_text() == "2"
            assert active_filters.get_attribute("class").endswith("is-active")
            assert page.locator(".catalog-view .task-card").count() == 3
            filtered_task = page.locator(".catalog-view .task-card").first
            filtered_task.click()
            page.get_by_role("heading", name=tasks[1]["title"]).wait_for()
            detail_geometry = page.evaluate(
                """() => {
                  const meta = document.querySelector('.task-detail-meta').getBoundingClientRect();
                  const action = document.querySelector('.task-detail > .primary')
                    .getBoundingClientRect();
                  const description = [...document.querySelectorAll('.task-detail > .section')][0]
                    .getBoundingClientRect();
                  return {metaBottom: meta.bottom, actionTop: action.top,
                    descriptionTop: description.top,
                    overflowX: document.documentElement.scrollWidth - innerWidth};
                }"""
            )
            assert detail_geometry["metaBottom"] < height
            assert detail_geometry["actionTop"] < height
            assert detail_geometry["descriptionTop"] < height
            assert detail_geometry["overflowX"] == 0
            page.get_by_role("button", name="Назад").click()
            catalog.wait_for()
            assert page.locator(".catalog-view .task-card").count() == 3
            assert page.get_by_role("button", name="Фильтры, выбрано: 2").is_visible()
            page.close()
        browser.close()


def test_core_hash_routes_restore_authoritatively_and_fail_closed(
    mini_app_url: str,
) -> None:
    task_id = "00000000-0000-0000-0000-000000000090"
    assignment_id = "00000000-0000-0000-0000-000000000091"
    forbidden_id = "00000000-0000-0000-0000-000000000092"
    task = {
        "id": task_id,
        "title": "Восстановить экран",
        "author_display_name": "Мария",
        "category_name": None,
        "task_kind": "solo",
        "deadline_at": "2026-08-21T20:00:00Z",
        "credit_reward_per_performer": 2,
        "performer_slots": 1,
        "format": "online",
        "city": None,
        "description": "Проверить reload",
        "completion_criteria": "Экран восстановлен",
        "performer_instructions": "Обновить страницу",
        "public_input": {},
        "materials": {},
    }
    detail = {
        "task_title": "Авторитетное назначение",
        "assignment_status": "accepted",
        "task_deadline_at": "2026-08-21T20:00:00Z",
        "description": "SERVER-PROJECTION",
        "completion_criteria": "Экран восстановлен",
        "performer_instructions": "Обновить страницу",
        "result_summary": None,
        "review_deadline_at": None,
        "reject_dispute_deadline_at": None,
        "case_status": None,
        "can_dispute": False,
        "can_submit": False,
        "can_cancel": False,
    }
    task_fetches: list[str] = []
    detail_fetches: list[str] = []

    def tasks_route(route: Route) -> None:
        task_fetches.append(route.request.url)
        route.fulfill(json={"items": [task], "next_cursor": None})

    def detail_route(route: Route) -> None:
        requested_id = route.request.url.rsplit("/", maxsplit=1)[-1]
        detail_fetches.append(requested_id)
        if requested_id == forbidden_id:
            route.fulfill(status=403, json={"code": "PRIVATE-DENIAL"})
        else:
            route.fulfill(
                status=200 if requested_id == assignment_id else 404,
                json=detail if requested_id == assignment_id else {"code": "not_found"},
            )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 375, "height": 812})
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(json={"display_name": "Алекс", "member_id": "me"}),
        )
        page.route("**/api/v1/tasks", tasks_route)
        page.route(
            "**/api/v1/assignments?*",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload(empty=True)),
        )
        page.route("**/api/v1/assignments/*", detail_route)

        page.goto(mini_app_url + "#/catalog?view_state=t01")
        page.get_by_role("button", name="Восстановить экран").click()
        page.reload()
        page.get_by_role("heading", name="Восстановить экран").wait_for()
        assert len(task_fetches) == 2
        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="T01"]').wait_for()

        page.goto(mini_app_url + "?case=detail#/work/" + assignment_id + "?view_state=m03")
        page.get_by_text("SERVER-PROJECTION").wait_for()
        assert detail_fetches == [assignment_id]
        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="T01"]').wait_for()

        page.goto(mini_app_url + "?case=forbidden#/work/" + forbidden_id + "?view_state=m03")
        page.get_by_text("Назначения недоступны для этого аккаунта.").wait_for()
        assert "PRIVATE-DENIAL" not in page.locator("body").inner_text()
        page.goto(mini_app_url + "?case=malformed#/work/..%2Fmembers%2FPRIVATE-ID?view_state=m03")
        page.get_by_role("heading", name="Задания").wait_for()
        assert detail_fetches == [assignment_id, forbidden_id]
        assert page.evaluate("document.documentElement.scrollWidth") <= 375
        browser.close()


def test_fresh_telegram_session_handshake_is_exact_and_fail_closed(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    invitation = "first-launch-invitation"
    init_data = f"query_id=AAE&user=%7B%22id%22%3A1%7D&start_param={invitation}&hash=proof"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()

        page = _new_page(
            browser,
            bridge=f'globalThis.Telegram = {{WebApp: {{initData: "{init_data}"}}}};',
        )
        requests: list[Any] = []
        console_messages: list[str] = []
        page.on("console", lambda message: console_messages.append(message.text))
        me_calls = 0

        def me(route: Route) -> None:
            nonlocal me_calls
            me_calls += 1
            if me_calls == 1:
                route.fulfill(status=401, json={"code": "unauthorized"})
            else:
                assert "community_session=test" in route.request.headers.get("cookie", "")
                route.fulfill(json={"display_name": "Алекс"})

        def auth(route: Route) -> None:
            requests.append(route.request)
            assert route.request.headers["x-community-invitation"] == invitation
            route.fulfill(
                status=204,
                headers={"set-cookie": "community_session=test; Path=/; SameSite=Strict"},
            )

        page.route("**/api/v1/me", me)
        page.route("**/api/v1/auth/telegram", auth)
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload(empty=True)),
        )
        page.goto(mini_app_url)
        page.get_by_role("heading", name="Задания").wait_for()
        assert me_calls == 2
        assert len(requests) == 1
        assert requests[0].post_data == init_data
        assert requests[0].headers["content-type"] == "text/plain; charset=utf-8"
        assert requests[0].headers["origin"] == mini_app_url.rstrip("/")
        assert requests[0].url == mini_app_url + "api/v1/auth/telegram"
        assert page.evaluate("Object.keys(localStorage).sort()") == [
            "community_bot_ui_theme",
            "community_bot_ui_theme_preset",
        ]
        assert page.evaluate("sessionStorage.length") == 0
        assert all(init_data not in message for message in console_messages)

        existing = _new_page(
            browser,
            bridge=f'globalThis.Telegram = {{WebApp: {{initData: "{init_data}"}}}};',
        )
        auth_calls = 0

        def unexpected_auth(route: Route) -> None:
            nonlocal auth_calls
            auth_calls += 1
            route.abort()

        existing.route(
            "**/api/v1/me",
            lambda route: route.fulfill(json={"display_name": "Сессия"}),
        )
        existing.route("**/api/v1/auth/telegram", unexpected_auth)
        existing.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        existing.goto(mini_app_url)
        existing.get_by_role("heading", name="Задания").wait_for()
        assert auth_calls == 0

        invalid = _new_page(
            browser,
            bridge=f'globalThis.Telegram = {{WebApp: {{initData: "{init_data}"}}}};',
        )
        invalid_me_calls = 0
        invalid_task_calls = 0

        def invalid_me(route: Route) -> None:
            nonlocal invalid_me_calls
            invalid_me_calls += 1
            route.fulfill(status=401, json={"code": "unauthorized"})

        def invalid_tasks(route: Route) -> None:
            nonlocal invalid_task_calls
            invalid_task_calls += 1
            route.abort()

        invalid.route("**/api/v1/me", invalid_me)
        invalid.route(
            "**/api/v1/auth/telegram",
            lambda route: route.fulfill(status=403, json={"code": "invalid_telegram_proof"}),
        )
        invalid.route("**/api/v1/tasks", invalid_tasks)
        invalid.goto(mini_app_url)
        invalid.get_by_text("Нужно приглашение", exact=True).wait_for()
        assert invalid_me_calls == 1
        assert invalid_task_calls == 0

        outside = _new_page(browser)
        outside_auth_calls = 0
        task_calls = 0

        def outside_auth(route: Route) -> None:
            nonlocal outside_auth_calls
            outside_auth_calls += 1
            route.abort()

        def tasks(route: Route) -> None:
            nonlocal task_calls
            task_calls += 1
            route.abort()

        outside.route(
            "**/api/v1/me",
            lambda route: route.fulfill(status=401, json={"code": "unauthorized"}),
        )
        outside.route("**/api/v1/auth/telegram", outside_auth)
        outside.route("**/api/v1/tasks", tasks)
        outside.goto(mini_app_url)
        outside.get_by_text(
            "Не удалось открыть главный экран заданий. Проверьте локальную сессию.",  # noqa: RUF001
            exact=True,
        ).wait_for()
        assert outside_auth_calls == task_calls == 0
        browser.close()


def test_form_controls_keep_branded_theme_after_telegram_ready(mini_app_url: str) -> None:
    def contrast_ratio(foreground: str, background: str) -> float:
        def luminance(color: str) -> float:
            channels = [int(value) / 255 for value in re.findall(r"\d+", color)[:3]]
            linear = [
                value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                for value in channels
            ]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
        return (light + 0.05) / (dark + 0.05)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.emulate_media(color_scheme="light")
        page.add_init_script(
            """
            globalThis.visualViewportListeners = {};
            Object.defineProperty(globalThis, 'visualViewport', {
              configurable: true,
              value: {
                width: 350, height: 420, offsetLeft: 12, offsetTop: 4,
                addEventListener(name, callback) {
                  globalThis.visualViewportListeners[name] = callback;
                }
              }
            });
            globalThis.Telegram = {WebApp: {
              colorScheme: "light",
              isFullscreen: false,
              safeAreaInset: {top: 24, right: 0, bottom: 8, left: 0},
              contentSafeAreaInset: {top: 74, right: 0, bottom: 8, left: 0},
              themeParams: {
                bg_color: "#f6f8fc", secondary_bg_color: "#ffffff",
                text_color: "#171b26", hint_color: "#687187",
                button_color: "#08766f", button_text_color: "#ffffff"
              },
              ready() { globalThis.readyCalls = (globalThis.readyCalls || 0) + 1; },
              expand() { globalThis.expandCalls = (globalThis.expandCalls || 0) + 1; },
              requestFullscreen() {
                globalThis.fullscreenCalls = (globalThis.fullscreenCalls || 0) + 1;
              },
              onEvent(name, callback) {
                globalThis.telegramEvents = globalThis.telegramEvents || {};
                globalThis.telegramEvents[name] = callback;
              },
            }};
            """
        )
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(json={"display_name": "Алекс"}),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.goto(mini_app_url)
        assert page.evaluate("document.documentElement.dataset.keyboardOpen") == "true"
        assert (
            page.evaluate(
                "getComputedStyle(document.documentElement).getPropertyValue('--app-visual-viewport-width')"
            )
            == "350px"
        )
        assert (
            page.evaluate(
                "getComputedStyle(document.documentElement).getPropertyValue('--app-visual-viewport-height')"
            )
            == "420px"
        )
        modal_geometry = page.evaluate(
            """() => {
              const backdrop = document.createElement('section');
              backdrop.className = 'task-size-backdrop';
              const dialog = document.createElement('div');
              dialog.className = 'task-size-sheet content-editor-sheet';
              dialog.setAttribute('role', 'dialog');
              const input = document.createElement('textarea');
              input.className = 'content-editor-input';
              const done = document.createElement('button');
              done.className = 'content-editor-done';
              done.textContent = 'Готово';
              dialog.append(input, done);
              backdrop.append(dialog);
              document.querySelector('.shell').append(backdrop);
              const backdropBox = backdrop.getBoundingClientRect();
              const dialogBox = dialog.getBoundingClientRect();
              const doneBox = done.getBoundingClientRect();
              const result = {
                backdropWidth: Math.round(backdropBox.width),
                backdropHeight: Math.round(backdropBox.height),
                dialogWidth: Math.round(dialogBox.width),
                actionsVisible: doneBox.bottom <= backdropBox.bottom,
                inputFontSize: getComputedStyle(input).fontSize,
              };
              backdrop.remove();
              return result;
            }"""
        )
        assert modal_geometry == {
            "backdropWidth": 334,
            "backdropHeight": 404,
            "dialogWidth": 318,
            "actionsVisible": True,
            "inputFontSize": "16px",
        }
        assert page.evaluate("getComputedStyle(document.body).paddingTop") == "86px"
        assert (
            page.locator(".bottom-nav").evaluate(
                "node => Math.round(node.getBoundingClientRect().height)"
            )
            == 64
        )
        page.evaluate(
            """() => {
              Telegram.WebApp.contentSafeAreaInset.top = 90;
              globalThis.telegramEvents.contentSafeAreaChanged();
            }"""
        )
        assert page.evaluate("getComputedStyle(document.body).paddingTop") == "102px"
        page.locator("#content").evaluate(
            r"""node => {
              node.innerHTML = `<form class="task-form">
                <input value="Видимое значение" placeholder="Видимая подсказка">
                <select><option>Видимый вариант</option></select>
                <textarea placeholder="Видимая подсказка"></textarea>
              </form>`;
            }"""
        )

        controls = page.locator("input, select, textarea")
        for index in range(controls.count()):
            styles = controls.nth(index).evaluate(
                """node => {
                  const style = getComputedStyle(node);
                  return {
                    background: style.backgroundColor,
                    color: style.color,
                    caret: style.caretColor,
                    height: node.getBoundingClientRect().height,
                  };
                }"""
            )
            assert styles == {
                "background": "rgb(241, 239, 252)",
                "color": "rgb(25, 23, 39)",
                "caret": "rgb(96, 64, 255)",
                "height": styles["height"],
            }
            assert styles["height"] >= 44

        controls.first.focus()
        assert controls.first.evaluate("node => getComputedStyle(node).outlineColor") == (
            "rgb(109, 91, 255)"
        )
        focused = controls.first.evaluate(
            """node => {
              const style = getComputedStyle(node);
              return {background: style.backgroundColor, border: style.borderColor,
                focus: style.outlineColor, text: style.color};
            }"""
        )
        assert contrast_ratio(focused["text"], focused["background"]) >= 4.5
        assert contrast_ratio(focused["border"], focused["background"]) >= 3
        assert contrast_ratio(focused["focus"], focused["background"]) >= 3
        placeholder_styles = page.locator("input, textarea").evaluate_all(
            """nodes => nodes.map(node => {
              const placeholder = getComputedStyle(node, '::placeholder');
              const probe = document.createElement('span');
              probe.style.color = 'var(--app-placeholder)';
              node.after(probe);
              const token = getComputedStyle(probe).color;
              probe.remove();
              return {
                color: placeholder.color,
                fill: placeholder.webkitTextFillColor,
                text: getComputedStyle(node).color,
                token,
              };
            })"""
        )
        assert len(placeholder_styles) == 2
        assert {style["color"] for style in placeholder_styles} == {placeholder_styles[0]["token"]}
        assert all(style["fill"] == style["color"] for style in placeholder_styles)
        assert all(style["color"] != style["text"] for style in placeholder_styles)
        assert page.locator("option").evaluate("node => getComputedStyle(node).color") == (
            "rgb(25, 23, 39)"
        )
        controls.nth(1).evaluate("node => { node.disabled = true; }")
        assert controls.nth(1).evaluate("node => getComputedStyle(node).backgroundColor") == (
            "rgb(255, 255, 255)"
        )
        assert page.evaluate("getComputedStyle(document.documentElement).colorScheme") == "light"
        assert page.evaluate("getComputedStyle(document.body).backgroundImage") != "none"
        assert (
            page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(246, 246, 251)"
        )
        assert page.evaluate("globalThis.readyCalls") == 1
        assert page.evaluate("globalThis.expandCalls") == 1
        assert page.evaluate("globalThis.fullscreenCalls") == 1
        browser.close()


@pytest.mark.parametrize(
    ("preset", "theme", "gradient"),
    [
        (
            "acid",
            "light",
            "linear-gradient(145deg, rgb(227, 255, 92), rgb(154, 214, 0) 60%, rgb(118, 169, 0))",
        ),
        (
            "acid",
            "dark",
            "linear-gradient(145deg, rgb(242, 255, 138), rgb(201, 255, 50) 60%, rgb(174, 230, 0))",
        ),
        (
            "neon",
            "light",
            "linear-gradient(122deg, rgb(96, 64, 255) 0%, rgb(25, 205, 242) 68%)",
        ),
        (
            "neon",
            "dark",
            (
                "linear-gradient(122deg, rgb(154, 134, 255) 0%, "
                "rgb(154, 134, 255) 30%, rgb(63, 224, 255) 100%)"
            ),
        ),
    ],
)
def test_task_home_find_uses_theme_specific_deep_gradient(
    mini_app_url: str,
    preset: str,
    theme: str,
    gradient: str,
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.route("**/api/v1/me", lambda route: route.fulfill(json={"member_id": "member"}))
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload(empty=True)),
        )
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )

        page.goto(f"{mini_app_url}?preset={preset}&theme={theme}#/tasks")
        find_action = page.locator('[data-home-action="find"]')
        find_action.wait_for()

        assert find_action.evaluate("node => getComputedStyle(node).backgroundImage") == gradient
        browser.close()


@pytest.mark.parametrize(
    ("preset", "theme"),
    [("acid", "light"), ("acid", "dark"), ("neon", "light"), ("neon", "dark")],
)
def test_placeholders_use_one_subdued_token_in_every_theme(
    mini_app_url: str,
    preset: str,
    theme: str,
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(
                json={"member_id": "member", "display_name": "Алекс", "timezone": "UTC"}
            ),
        )
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload(empty=True)),
        )
        page.route(
            "**/api/v1/moderation/cases?*",
            lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
        )

        page.goto(f"{mini_app_url}?preset={preset}&theme={theme}#/tasks")
        page.locator('[data-screen-id="UX02"]').wait_for()
        page.locator("#content").evaluate(
            r"""node => {
              node.innerHTML = `<form class="task-form">
                <input placeholder="Бледная подсказка">
                <textarea class="content-editor-input" placeholder="Бледная подсказка"></textarea>
              </form>`;
            }"""
        )
        placeholder_styles = page.locator("input, textarea").evaluate_all(
            """nodes => nodes.map(node => {
              const placeholder = getComputedStyle(node, '::placeholder');
              const probe = document.createElement('span');
              probe.style.color = 'var(--app-placeholder)';
              node.after(probe);
              const token = getComputedStyle(probe).color;
              probe.remove();
              return {
                color: placeholder.color,
                fill: placeholder.webkitTextFillColor,
                text: getComputedStyle(node).color,
                token,
              };
            })"""
        )
        assert len(placeholder_styles) == 2
        assert all(style["color"] == style["token"] for style in placeholder_styles)
        assert all(style["fill"] == style["color"] for style in placeholder_styles)
        assert all(style["color"] != style["text"] for style in placeholder_styles)
        browser.close()


def test_catalog_detail_accept_is_literal_and_confirmed(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    malicious = "<img src=x onerror=alert(1)><script>bad()</script>"
    javascript_url = "javascript:globalThis.pwned=true"
    task_id = "00000000-0000-0000-0000-000000000053"
    other_task_id = "00000000-0000-0000-0000-000000000055"
    assignment_id = "00000000-0000-0000-0000-000000000054"
    other_assignment_id = "00000000-0000-0000-0000-000000000056"
    assignment_title = "Помочь с планом"  # noqa: RUF001
    other_assignment_title = "Проверить другой план"
    deadline = "2026-08-21T20:00:00Z"
    private_value = "PRIVATE-REVIEWER-42"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 375, "height": 812})
        requests: list[str] = []
        accept_keys: list[str] = []
        page.on("request", lambda request: requests.append(request.url))
        page.add_init_script(
            """
            globalThis.Telegram = {WebApp: {
              colorScheme: "light",
              themeParams: {
                bg_color: "#111111", secondary_bg_color: "#222222",
                text_color: "invalid", hint_color: "#444444",
                button_color: "#555555", button_text_color: "#666666"
              },
              ready() {}, expand() {}
            }};
            """
        )
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(json={"display_name": "Алекс"}),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(
                json={
                    "items": [
                        {
                            "id": task_id,
                            "origin": "member",
                            "author_display_name": "Мария",
                            "category_name": "Практическая помощь",
                            "category_icon": "⭐",
                            "task_kind": "group",
                            "time_size": "m",
                            "title": malicious,
                            "description": malicious,
                            "completion_criteria": malicious,
                            "performer_instructions": malicious,
                            "materials": {"url": javascript_url, "text": malicious},
                            "public_input": {malicious: javascript_url},
                            "credit_reward_per_performer": 3,
                            "performer_slots": 4,
                            "minimum_level": 1,
                            "format": "offline",
                            "city": "Буэнос-Айрес",
                            "deadline_at": deadline,
                            "status": "published",
                            "creator_id": "00000000-0000-0000-0000-000000000099",
                            "private_notes": private_value,
                        },
                        {
                            "id": other_task_id,
                            "origin": "community",
                            "author_display_name": "Сообщество",
                            "category_name": None,
                            "category_icon": None,
                            "task_kind": None,
                            "time_size": None,
                            "title": other_assignment_title,
                            "description": "Вторая карточка",
                            "completion_criteria": "План проверен",
                            "performer_instructions": "Сверить шаги",
                            "materials": {},
                            "public_input": {},
                            "credit_reward_per_performer": 2,
                            "performer_slots": 1,
                            "minimum_level": 1,
                            "format": "online",
                            "city": None,
                            "deadline_at": deadline,
                            "status": "published",
                        },
                    ],
                    "next_cursor": None,
                }
            ),
        )

        accepted_tasks: list[str] = []

        def accept(route: Route) -> None:
            assert route.request.method == "POST"
            accepted_task_id = route.request.url.split("/")[-2]
            operation_key = route.request.headers.get("idempotency-key", "")
            accepted_tasks.append(accepted_task_id)
            accept_keys.append(operation_key)
            assert re.fullmatch(r"[1-9][0-9]{0,18}", operation_key)
            assert int(operation_key) <= 2**63 - 1
            if accepted_task_id == task_id and accepted_tasks.count(task_id) == 1:
                route.fulfill(status=503, json={"code": "request_failed"})
                return
            accepted_assignment_id = (
                assignment_id if accepted_task_id == task_id else other_assignment_id
            )
            route.fulfill(
                status=201,
                json={
                    "id": accepted_assignment_id,
                    "task_id": accepted_task_id,
                    "slot_number": 1,
                    "status": "accepted",
                    "accepted_at": "2026-08-17T20:00:00Z",
                },
            )

        page.route("**/api/v1/tasks/*/assignments", accept)
        assignment = {
            "id": assignment_id,
            "task_id": task_id,
            "task_title": assignment_title,
            "task_origin": "member",
            "assignment_status": "submitted",
            "accepted_at": "2026-08-17T20:00:00Z",
            "submitted_at": "2026-08-17T20:30:00Z",
            "review_deadline_at": "2026-08-20T20:30:00Z",
            "reject_dispute_deadline_at": None,
            "reviewed_at": None,
            "task_deadline_at": "2026-08-21T20:00:00Z",
            "result_summary": "План отправлен",
            "case_status": None,
        }
        page.route(
            "**/api/v1/assignments?*",
            lambda route: route.fulfill(json={"items": [assignment], "next_cursor": None}),
        )

        def assignment_detail(route: Route) -> None:
            requested_id = route.request.url.rsplit("/", maxsplit=1)[-1]
            is_other = requested_id == other_assignment_id
            route.fulfill(
                json=(
                    assignment
                    if not is_other
                    else assignment
                    | {
                        "id": other_assignment_id,
                        "task_id": other_task_id,
                        "task_title": other_assignment_title,
                    }
                )
                | {
                    "category_name": "Практическая помощь",
                    "category_icon": None,
                    "task_kind": "solo",
                    "time_size": "s",
                    "description": "Собрать план",
                    "performer_instructions": "Проверить шаги",
                    "completion_criteria": "План понятен",
                    "reward_per_performer": 3,
                    "format": "online",
                    "city": None,
                    "minimum_level": 1,
                    "performer_slots": 1,
                    "submission_contract": None,
                    "can_submit": False,
                    "can_cancel": False,
                    "can_dispute": False,
                },
            )

        page.route("**/api/v1/assignments/*", assignment_detail)

        page.goto(mini_app_url + "?theme=dark&review=catalog-return-1#/catalog?view_state=t01")
        page.get_by_role("button", name=malicious).click()
        detail = page.locator("article.detail")
        assert detail.get_by_text("Мария", exact=True).count() == 1
        assert detail.get_by_text("Практическая помощь", exact=True).count() == 1
        assert detail.get_by_text("Групповое", exact=True).count() == 1
        assert detail.get_by_text("3 кредитов", exact=True).count() == 1
        assert detail.get_by_text("4", exact=True).count() == 1
        assert detail.get_by_text("Офлайн", exact=True).count() == 1
        assert detail.get_by_text("Буэнос-Айрес", exact=True).count() == 1
        expected_deadline = page.evaluate(
            """value => new Intl.DateTimeFormat("ru", {
              dateStyle: "medium", timeStyle: "short", timeZone: "UTC"
            }).format(new Date(value))""",
            deadline,
        )
        deadline_value = detail.locator(".task-detail-meta dt", has_text="Срок").locator(
            "xpath=following-sibling::dd[1]"
        )
        assert deadline_value.inner_text() == expected_deadline
        assert detail.locator(".task-detail-meta dt", has_text="Автор").evaluate(
            "node => Boolean(node.compareDocumentPosition("
            "node.closest('article').querySelector('button.primary')) "
            "& Node.DOCUMENT_POSITION_FOLLOWING)"
        )
        assert private_value not in detail.inner_text()
        assert "00000000-0000-0000-0000-000000000099" not in detail.inner_text()
        assert "undefined" not in detail.inner_text()
        assert "null" not in detail.inner_text()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert page.locator("body").inner_text().count(malicious) >= 4
        assert javascript_url in page.locator("body").inner_text()
        assert (
            page.locator(
                "#content img, #content a, #content [onerror], "
                "#content [onclick], #content [href^='javascript:']"
            ).count()
            == 0
        )
        assert page.locator("script").count() == 3
        assert page.evaluate("globalThis.pwned") is None
        assert (
            page.evaluate(
                "getComputedStyle(document.documentElement)"
                ".getPropertyValue('--app-background').trim()"
            )
            == "#070807"
        )

        page.get_by_role("button", name="Принять задание").click()
        assert page.url.endswith(f"#/tasks/{task_id}?view_state=t03a")
        assert page.get_by_role("button", name="Изменить", exact=True).count() == 0
        assert page.locator(".confirm-actions button").count() == 1
        page.reload()
        page.locator('[data-screen-id="T03"]').wait_for()
        assert page.url.endswith(f"#/tasks/{task_id}?view_state=t03")
        page.get_by_role("button", name="Принять задание").click()
        assert page.url.endswith(f"#/tasks/{task_id}?view_state=t03a")
        page.get_by_role("button", name="Принять слот").click()
        page.get_by_text("Задание сейчас недоступно.").wait_for()
        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="T03"]').wait_for()
        assert page.url.endswith(f"#/tasks/{task_id}?view_state=t03")
        page.go_back()
        page.locator('[data-screen-id="T03"]').wait_for()
        page.go_back()
        page.locator('[data-screen-id="T01"]').wait_for()
        page.get_by_role("button", name=other_assignment_title).click()
        other_detail = page.locator("article.detail")
        assert other_detail.get_by_text("Сообщество", exact=True).count() == 1
        assert other_detail.get_by_text("Онлайн", exact=True).count() == 1
        assert other_detail.locator(".card-chips .chip").all_inner_texts() == ["Онлайн"]
        assert other_detail.locator(".task-detail-meta dt", has_text="Город").count() == 0
        assert "undefined" not in other_detail.inner_text()
        assert "null" not in other_detail.inner_text()
        accepted_before = len(accepted_tasks)
        page.get_by_role("button", name="Принять задание").click()
        _connected_control(page, "PE-024", "authoritative_accept_success").click()
        page.get_by_role("heading", name=other_assignment_title).wait_for()
        assert len(accepted_tasks) == accepted_before + 1
        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="M01"]').wait_for()
        page.evaluate(
            """
            history.pushState({screen: "catalog"}, "", "#/catalog?view_state=t01");
            dispatchEvent(new PopStateEvent("popstate", {state: {screen: "catalog"}}));
            """
        )
        page.locator('[data-screen-id="T01"]').wait_for()
        page.get_by_role("button", name=malicious).click()
        page.get_by_role("button", name="Принять задание").click()
        page.get_by_role("button", name="Принять слот").click()
        page.get_by_role("heading", name=assignment_title).wait_for()
        assert accepted_tasks == [task_id, other_task_id, task_id]
        assert accept_keys[0] == accept_keys[2]
        assert accept_keys[1] != accept_keys[0]
        assert page.get_by_role("button", name="Принять задание").count() == 0
        assert not any(url.startswith("javascript:") for url in requests)

        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="M01"]').wait_for()
        page.evaluate(
            """
            history.pushState({screen: "catalog"}, "", "#/catalog?view_state=t01");
            dispatchEvent(new PopStateEvent("popstate", {state: {screen: "catalog"}}));
            """
        )
        catalog_trigger = page.get_by_role("button", name=malicious)
        catalog_trigger.wait_for()

        page.evaluate(
            """
            Telegram.WebApp.themeParams = {
              bg_color: "#ffffff", secondary_bg_color: "#ffffff",
              text_color: "#000000", hint_color: "#595959",
              button_color: "#777777", button_text_color: "#000000"
            };
            """
        )
        page.evaluate("import('/mini-assets/platform.js').then(m => m.applyPlatformTheme())")
        assert (
            page.evaluate(
                "getComputedStyle(document.documentElement)"
                ".getPropertyValue('--app-background').trim()"
            )
            == "#070807"
        )
        browser.close()


def test_moderation_disputes_detail_confirm_retry_conflict_and_back_focus(  # noqa: C901, PLR0915
    mini_app_url: str,
) -> None:
    malicious = "<img src=x onerror=alert(1)><script>bad()</script>"
    mode: dict[str, Any] = {"name": "pending"}
    pending: list[Route] = []
    requests: list[tuple[str, str]] = []
    registration_requests: list[str] = []
    resolution_keys: list[str] = []
    resolution_mode = {"name": "retry"}

    def moderation_route(route: Route) -> None:
        requests.append((route.request.method, route.request.url))
        if route.request.url.endswith("?limit=1"):
            route.fulfill(json={"items": [], "next_cursor": None})
            return
        if mode["name"] == "pending":
            pending.append(route)
        elif mode["name"] == "empty":
            route.fulfill(json={"items": []})
        elif mode["name"] == "closed":
            route.fulfill(status=403, json={"code": "moderation_unavailable"})
        elif mode["name"] == "unauthorized":
            route.fulfill(status=401, json={"code": "unauthorized"})
        else:
            route.abort()

    def detail_route(route: Route) -> None:
        route.fulfill(
            json={
                "id": "00000000-0000-0000-0000-000000000061",
                "status": "open",
                "revision": 0,
                "task_title": "Проверить отчёт",
                "task_origin": "member",
                "credit_reward_per_performer": 4,
                "assignment_status": "disputed",
                "result_summary": malicious,
                "dispute_reason": "Результат отклонён без пояснений",
                "allowed_resolution_codes": ["full_payment", "partial_payment"],
                "opened_at": "2026-08-17T20:00:00Z",
            }
        )

    def registration_route(route: Route) -> None:
        registration_requests.append(route.request.url)
        route.fulfill(json={"items": []})

    def resolution_route(route: Route) -> None:
        assert route.request.method == "POST"
        resolution_keys.append(route.request.headers["idempotency-key"])
        assert route.request.post_data_json == {
            "expected_revision": 0,
            "code": "partial_payment",
            "reason": "Подтверждена половина результата",
        }
        if resolution_mode["name"] == "retry" and len(resolution_keys) == 1:
            route.fulfill(status=502, body="upstream unavailable", content_type="text/plain")
        elif resolution_mode["name"] == "conflict":
            route.fulfill(status=409, json={"code": "moderation_unavailable"})
        else:
            mode["name"] = "empty"
            route.fulfill(status=204, body="")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.add_init_script(
            "let cacheNow = 1000; Date.now = () => cacheNow; "
            "globalThis.advanceCacheClock = value => { cacheNow += value; };"
        )
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(json={"display_name": "Алекс"}),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route("**/api/v1/moderation/cases?*", moderation_route)
        page.route(
            "**/api/v1/moderation/registrations?*",
            registration_route,
        )
        page.route("**/api/v1/moderation/cases/*/resolution", resolution_route)
        page.route("**/api/v1/moderation/cases/*", detail_route)

        page.goto(mini_app_url + "#/moderation?view_state=s01")
        moderation_nav = page.get_by_role("button", name="Модерация")
        page.get_by_text("Загружаем споры…").wait_for()
        assert len(pending) == 1
        pending.pop().fulfill(
            json={
                "items": [
                    {
                        "id": "00000000-0000-0000-0000-000000000061",
                        "assignment_id": "00000000-0000-0000-0000-000000000062",
                        "case_type": "dispute",
                        "status": "open",
                        "revision": 0,
                        "current_code": None,
                        "opened_at": "2026-08-17T20:00:00Z",
                        "resolved_at": None,
                        "reason": "PRIVATE_REASON",
                        "evidence": "PRIVATE_EVIDENCE",
                    }
                ]
            }
        )
        page.get_by_role("button", name="Споры · 1").wait_for()
        page.get_by_text("Спор по заданию").wait_for()
        assert page.get_by_role("button", name=re.compile("Регистрации|Обращения")).count() == 0
        assert registration_requests == []
        assert "PRIVATE_REASON" not in page.locator("body").inner_text()
        assert "PRIVATE_EVIDENCE" not in page.locator("body").inner_text()
        assert page.locator("#content img, #content [onerror], #content [onclick]").count() == 0
        assert page.locator("script").count() == 3

        page.get_by_role("button", name="Спор по заданию").click()
        page.locator('[data-screen-id="S02"]').wait_for()
        page.get_by_role("combobox", name="Решение").wait_for()
        assert page.locator(".moderation-resolution-card").count() == 1
        assert page.locator(".moderation-dispute-fact").all_inner_texts() == [
            "От участника",
            "4 кредита",
        ]
        assert page.locator(".moderation-dispute-copy").count() == 2
        assert page.get_by_role("textbox", name="Причина решения").evaluate(
            "node => node.getBoundingClientRect().height <= 120"
        )
        assert malicious in page.locator("body").inner_text()
        assert page.locator("#content img, #content [onerror], #content [onclick]").count() == 0
        resolution = page.get_by_role("combobox", name="Решение")
        assert resolution.evaluate("node => node === document.activeElement")
        resolution.select_option("partial_payment")
        reason = page.get_by_role("textbox", name="Причина решения")
        reason.fill("Подтверждена половина результата")
        reason.press("Tab")
        review = page.get_by_role("button", name="Проверить решение")
        assert review.evaluate("node => node === document.activeElement")
        review.press("Enter")
        assert page.url.endswith("#/moderation/00000000-0000-0000-0000-000000000061?view_state=s03")
        page.get_by_role("button", name="Изменить").click()
        page.locator('[data-screen-id="S02"]').wait_for()
        assert page.url.endswith("#/moderation/00000000-0000-0000-0000-000000000061?view_state=s02")
        page.get_by_role("combobox", name="Решение").select_option("partial_payment")
        page.get_by_role("textbox", name="Причина решения").fill("Подтверждена половина результата")
        page.get_by_role("button", name="Проверить решение").click()
        page.reload()
        page.locator('[data-screen-id="S02"]').wait_for()
        assert page.url.endswith("#/moderation/00000000-0000-0000-0000-000000000061?view_state=s02")
        page.get_by_role("combobox", name="Решение").select_option("partial_payment")
        page.get_by_role("textbox", name="Причина решения").fill("Подтверждена половина результата")
        page.get_by_role("button", name="Проверить решение").click()
        confirm = page.get_by_role("button", name="Применить решение")
        assert confirm.evaluate("node => node === document.activeElement")
        assert resolution_keys == []
        confirm.click()
        page.get_by_text("Не удалось применить решение.").wait_for()  # noqa: RUF001
        resolution_before = len(resolution_keys)
        _connected_control(page, "PE-068", "authoritative_resolution_success").click()
        page.get_by_role("button", name="К спорам").click()  # noqa: RUF001
        page.get_by_text("Открытых споров нет").wait_for()
        assert len(resolution_keys) == resolution_before + 1
        assert len(resolution_keys) == 2
        assert resolution_keys[0] == resolution_keys[1]

        assert page.locator("#primary-navigation").is_visible()
        assert page.get_by_role("button", name="Назад").is_hidden()
        page.get_by_role("button", name="Задания", exact=True).click()
        page.get_by_role("heading", name="Задания").wait_for()

        mode["name"] = "pending"
        resolution_mode["name"] = "conflict"
        page.evaluate("advanceCacheClock(60001)")
        moderation_nav.click()
        pending.pop().fulfill(
            json={
                "items": [
                    {
                        "id": "00000000-0000-0000-0000-000000000061",
                        "assignment_id": "00000000-0000-0000-0000-000000000062",
                        "case_type": "dispute",
                        "status": "open",
                        "revision": 0,
                        "current_code": None,
                        "opened_at": "2026-08-17T20:00:00Z",
                        "resolved_at": None,
                    }
                ]
            }
        )
        page.get_by_role("button", name="Споры · 1").wait_for()
        page.get_by_role("button", name="Спор по заданию").click()
        page.get_by_role("combobox", name="Решение").select_option("partial_payment")
        page.get_by_role("textbox", name="Причина решения").fill("Подтверждена половина результата")
        page.get_by_role("button", name="Проверить решение").click()
        assert page.url.endswith("#/moderation/00000000-0000-0000-0000-000000000061?view_state=s03")
        page.get_by_role("button", name="Применить решение").click()
        page.get_by_text("Спор уже изменился").wait_for()
        page.get_by_role("button", name="Изменить").click()
        page.locator('[data-screen-id="S02"]').wait_for()
        assert page.url.endswith("#/moderation/00000000-0000-0000-0000-000000000061?view_state=s02")
        page.evaluate("advanceCacheClock(60001)")
        with page.expect_request("**/api/v1/moderation/cases?*"):
            page.get_by_role("button", name="Закрыть спор").click()
        pending.pop().fulfill(
            json={
                "items": [
                    {
                        "id": "00000000-0000-0000-0000-000000000061",
                        "assignment_id": "00000000-0000-0000-0000-000000000062",
                        "case_type": "dispute",
                        "status": "open",
                        "revision": 0,
                        "current_code": None,
                        "opened_at": "2026-08-17T20:00:00Z",
                        "resolved_at": None,
                    }
                ]
            }
        )
        page.get_by_role("button", name="Спор по заданию").wait_for()
        assert page.get_by_role("button", name="Спор по заданию").evaluate(
            "node => node === document.activeElement"
        )
        page.get_by_role("button", name="Задания", exact=True).click()
        page.get_by_role("heading", name="Задания").wait_for()

        mode["name"] = "empty"
        page.evaluate("advanceCacheClock(60001)")
        moderation_nav.click()
        page.get_by_text("Открытых споров нет").wait_for()
        page.get_by_role("button", name="Задания", exact=True).click()
        page.get_by_role("heading", name="Задания").wait_for()

        mode["name"] = "closed"
        page.evaluate("advanceCacheClock(60001)")
        with page.expect_response(lambda response: response.status == 403):
            moderation_nav.click()
        page.get_by_text("Открытых споров нет").wait_for()
        assert page.get_by_text("Споры недоступны").count() == 0
        assert "Moderator" not in page.locator("body").inner_text()
        page.get_by_role("button", name="Задания", exact=True).click()
        page.get_by_role("heading", name="Задания").wait_for()

        mode["name"] = "unauthorized"
        page.evaluate("advanceCacheClock(60001)")
        with page.expect_response(lambda response: response.status == 401):
            moderation_nav.click()
        page.get_by_text("Открытых споров нет").wait_for()
        moderation_nav.click()
        page.get_by_text("Сессия истекла. Закройте и снова откройте Mini App.").wait_for()
        page.get_by_role("button", name="Задания", exact=True).click()
        page.get_by_role("heading", name="Задания").wait_for()

        mode["name"] = "network"
        moderation_nav.click()
        page.get_by_text("Не удалось загрузить споры.").wait_for()  # noqa: RUF001
        assert page.get_by_role("button", name="Повторить").count() == 1
        assert requests
        assert all(method == "GET" for method, _url in requests)
        assert registration_requests == []
        browser.close()


@pytest.mark.parametrize("width", [320, 390])
def test_new_achievement_filters_use_supported_backend_metrics(
    mini_app_url: str, width: int
) -> None:
    def leaderboard_route(route: Route) -> None:
        query = parse_qs(urlsplit(route.request.url).query)
        metric = query["metric"][0]
        if metric.startswith("achievement:"):
            assert query["period"] == ["all"]
        try:
            CommunityStatsService.validate_metric(metric, period="all", topic_id=None)
        except ValueError:
            route.fulfill(status=422, json={"code": "invalid_request"})
            return
        route.fulfill(
            json={
                "items": [
                    {
                        "member_id": "00000000-0000-0000-0000-000000000068",
                        "display_name": f"Лидер {metric}",
                        "rank": 1,
                        "value": 2,
                    }
                ],
                "tracking_started_at": "2026-08-28T00:00:00Z",
                "calculated_at": "2026-09-04T12:00:00Z",
            }
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": width, "height": 812})
        page.route(
            "**/api/v1/**", lambda route: route.fulfill(status=403, json={"code": "forbidden"})
        )
        page.route("**/api/v1/me", lambda route: route.fulfill(json=_cache_profile()[0]))
        page.route("**/api/v1/community-stats/leaderboard?*", leaderboard_route)
        page.goto(mini_app_url + "?theme=light#/members?view_state=p05")
        page.get_by_text("Лидер experience", exact=True).wait_for()
        for label, code in (
            ("Будильник", "wake_up"),
            ("Хлеб-соль", "bread_and_salt"),
            ("Онбордист", "onboarder"),
        ):
            page.locator(".leaderboard-filter-trigger").click()
            page.get_by_role("dialog", name="Рейтинг по").get_by_role(
                "radio",
                name=label,
                exact=True,
            ).click()
            page.get_by_text(f"Лидер achievement:{code}", exact=True).wait_for()
            assert page.get_by_text("Статистика временно недоступна.", exact=False).count() == 0
            assert not page.get_by_role("button", name="Неделя", exact=True).is_enabled()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth") is True
        browser.close()


def test_profile_and_leaderboard_are_safe_retryable_and_stale_safe(  # noqa: C901, PLR0915
    mini_app_url: str,
) -> None:
    member_id = "00000000-0000-0000-0000-000000000068"
    malicious = "<img src=x onerror=alert(1)><script>bad()</script>"
    private_marker = "PRIVATE_PROFILE_MARKER"
    me = {
        "member_id": member_id,
        "display_name": malicious,
        "city": "Буэнос-Айрес",
        "timezone": "America/Argentina/Buenos_Aires",
        "short_bio": "Помогаю собирать ясные планы.",
        "current_goal": "Найти партнёров для пилота.",
        "help_categories": ["Стратегия", "Текст"],
        "skill_tags": ["Фасилитация", "Редактура"],
        "availability": "По вечерам",
        "credit_balance": 7,
        "experience_total": 12,
        "level": {"number": 2, "display_name": "Участник"},
        "statistics": {"completed_tasks": 8, "created_tasks": 5},
        "private_top_level": private_marker,
    }
    member = {
        "member_id": member_id,
        "telegram_username": private_marker,
        "display_name": malicious,
        "city": "Буэнос-Айрес",
        "short_bio": "Публичное описание",
        "current_goal": "LEGACY_GOAL_VALUE",
        "help_categories": ["LEGACY_HELP_VALUE"],
        "skill_tags": ["Фасилитация", "Редактура"],
        "availability": "LEGACY_AVAILABILITY_VALUE",
        "experience_total": 12,
        "level_number": 2,
        "karma": {"score": 3, "count": 4, "comment": private_marker},
        "reliability": {
            "accepted": 4,
            "approved_weight": "3.5",
            "no_show": 1,
            "rate": "0.96",
            "private": private_marker,
        },
        "unknown": private_marker,
    }
    leaderboard = {
        "items": [
            {
                "rank": 1,
                "member_id": private_marker,
                "display_name": malicious,
                "value": 12,
                "unknown": private_marker,
            }
        ],
        "private": private_marker,
    }
    modes = {"member": "pending", "leaderboard": "pending"}
    pending: list[Route] = []
    requests: list[tuple[str, str]] = []
    profile_update_keys: list[str] = []
    capture_requests = False

    def me_route(route: Route) -> None:
        route.fulfill(json=me)

    def fulfill_by_mode(route: Route, mode: str, payload: dict[str, Any]) -> None:
        if mode == "pending":
            pending.append(route)
        elif mode == "error":
            route.fulfill(status=503, json={"code": "request_failed"})
        else:
            route.fulfill(json=payload)

    def member_route(route: Route) -> None:
        fulfill_by_mode(route, modes["member"], member)

    def leaderboard_route(route: Route) -> None:
        payload = {"items": []} if modes["leaderboard"] == "empty" else leaderboard
        fulfill_by_mode(route, modes["leaderboard"], payload)

    def profile_update_route(route: Route) -> None:
        assert route.request.method == "PUT"
        profile_update_keys.append(route.request.headers["idempotency-key"])
        body = route.request.post_data_json
        assert body is not None
        if len(profile_update_keys) == 1:
            assert body == {"field": "city", "value": "Rosario"}
            route.abort()
        elif len(profile_update_keys) == 2:
            assert body == {"field": "city", "value": "Rosario"}
            route.fulfill(status=502, body="upstream unavailable")
        elif len(profile_update_keys) == 3:
            assert body == {"field": "city", "value": "Rosario"}
            me["city"] = "Rosario"
            route.fulfill(json=me)
        else:
            assert body == {"field": "city", "value": "x"}
            route.fulfill(status=422, json={"code": "invalid_request"})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.set_viewport_size({"width": 375, "height": 812})
        page.on(
            "request",
            lambda request: (
                requests.append((request.method, urlsplit(request.url).path))
                if capture_requests
                else None
            ),
        )
        page.route("**/api/v1/me", me_route)
        page.route("**/api/v1/me/profile", profile_update_route)
        page.route(f"**/api/v1/members/{member_id}", member_route)
        page.route(
            "**/api/v1/members?*",
            lambda route: route.fulfill(json={"items": [member]}),
        )
        page.route("**/api/v1/community-stats/leaderboard?*", leaderboard_route)
        page.route(
            "**/api/v1/community-stats/pulse?*",
            lambda route: route.fulfill(status=503, json={"code": "community_stats_unavailable"}),
        )
        page.route(
            "**/api/v1/task-cities?*",
            lambda route: route.fulfill(
                json={
                    "items": [
                        {
                            "value": "Rosario",
                            "label": "Rosario",
                            "timezone": "America/Argentina/Cordoba",
                        }
                    ]
                }
            ),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.goto(mini_app_url)
        page.get_by_role("heading", name="Задания").wait_for()

        capture_requests = True
        settings_nav = page.get_by_role("button", name="Параметры", exact=True)

        def open_profile() -> None:
            settings_nav.click()
            page.locator(".settings-link-row").click()

        open_profile()
        page.get_by_text("Загружаем профиль…").wait_for()
        page.wait_for_timeout(50)
        assert {urlsplit(route.request.url).path for route in pending} == {
            f"/api/v1/members/{member_id}"
        }
        member_pending = next(route for route in pending if "/members/" in route.request.url)
        member_pending.fulfill(json=member)
        pending.remove(member_pending)

        page.locator("h2", has_text=malicious).wait_for()
        assert page.get_by_role("heading", name="Лидерборд").count() == 0
        for value in ("7", "12", "3"):
            assert page.get_by_text(value, exact=True).count() >= 1
        for label in ("Кредиты", "Опыт", "Карма"):
            assert page.get_by_text(label, exact=True).count() == 1
        for removed_label in (
            "Завершено заданий",
            "Создано заданий",
            "Надёжность",
            "Принято заданий",
            "Подтверждённый вес",
            "Неявки",
        ):
            assert page.get_by_text(removed_label, exact=True).count() == 0
        body = page.locator("body").inner_text()
        assert malicious in body
        assert private_marker not in body
        assert page.locator("#content img, #content [onerror], #content [onclick]").count() == 0
        assert page.locator("script").count() == 3
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for editable_value in ("Буэнос-Айрес", "Помогаю собирать ясные планы."):
            assert page.get_by_text(editable_value, exact=True).count() == 1
        for legacy_value in (
            "America/Argentina/Buenos_Aires",
            "Найти партнёров для пилота.",
            "Стратегия, Текст",
            "По вечерам",
            "LEGACY_GOAL_VALUE",
            "LEGACY_HELP_VALUE",
            "LEGACY_AVAILABILITY_VALUE",
        ):
            assert page.get_by_text(legacy_value, exact=True).count() == 0
        for legacy_label in (
            "Часовой пояс",
            "Текущая цель",
            "Категории помощи",
            "Доступность",
        ):
            assert page.get_by_text(legacy_label, exact=True).count() == 0
        assert page.locator(".leaderboard-row, .leaderboard-list").count() == 0
        assert page.locator(".profile-overview").is_visible()
        assert page.url.endswith("#/profile")
        assert page.locator("[data-profile-action]").count() == 5

        page.locator('[data-profile-action="city"]').click()
        page.get_by_role("searchbox", name="Поиск города").fill("Rosario")
        city_option = page.get_by_role("option", name="Rosario")
        city_option.click()
        page.get_by_text(
            "Не удалось сохранить город. Повторите попытку."  # noqa: RUF001
        ).wait_for()
        assert page.get_by_role("searchbox", name="Поиск города").input_value() == "Rosario"
        city_option.click()
        page.get_by_text(
            "Не удалось сохранить город. Повторите попытку."  # noqa: RUF001
        ).wait_for()
        profile_updates_before = len(profile_update_keys)
        city_option.click()
        page.locator('[data-profile-action="city"]').click()
        assert page.get_by_role("searchbox", name="Поиск города").input_value() == "Rosario"
        assert len(profile_update_keys) == profile_updates_before + 1
        assert profile_update_keys[0] == profile_update_keys[1] == profile_update_keys[2]
        assert page.get_by_text("Не удалось сохранить.", exact=False).count() == 0  # noqa: RUF001

        page.get_by_role("button", name="Закрыть редактор").click()
        updates_before_cancel = len(profile_update_keys)
        page.get_by_role("button", name="Изменить о себе").click()  # noqa: RUF001
        page.get_by_label("Описание").fill("Несохранённое значение профиля")
        page.get_by_role("button", name="Закрыть редактор").click()
        assert len(profile_update_keys) == updates_before_cancel
        assert page.get_by_text("Помогаю собирать ясные планы.", exact=True).count() == 1

        modes.update(member="success", leaderboard="success")
        me["skill_tags"] = []
        open_profile()
        page.locator("h2", has_text=malicious).wait_for()
        assert page.get_by_role("heading", name="Навыки").count() == 0
        assert page.locator(".leaderboard-row, .leaderboard-list").count() == 0
        assert private_marker not in page.locator("body").inner_text()

        modes.update(member="error", leaderboard="success")
        requests_before_cached_profile = len(requests)
        open_profile()
        page.locator("h2", has_text=malicious).wait_for()
        assert page.get_by_text("Не удалось загрузить профиль.").count() == 0  # noqa: RUF001
        assert len(requests) == requests_before_cached_profile
        assert page.get_by_text("Лидерборд").count() == 0
        modes["member"] = "success"

        modes["leaderboard"] = "error"
        page.get_by_role("button", name="Комьюнити", exact=True).click()
        page.get_by_role("button", name="Люди", exact=True).click()
        page.locator('[data-screen-id="P01"][data-state="content"]').wait_for()
        page.get_by_role("button", name="Лидерборд").click()
        page.get_by_text("Статистика временно недоступна.", exact=False).wait_for()
        page.get_by_role("button", name="Рейтинг по: Опыт").click()
        page.get_by_role("dialog", name="Рейтинг по").get_by_role("radio", name="Сообщения").click()
        modes["leaderboard"] = "success"
        page.get_by_role("button", name="Повторить").click()
        page.get_by_text("12 сообщ.").wait_for()
        assert page.get_by_text("Получатели помощи: 3").count() == 0
        assert page.get_by_text("Неявки: 1").count() == 0

        page.evaluate("Date.now = () => Number.MAX_SAFE_INTEGER")
        modes["leaderboard"] = "empty"
        assert page.locator("#primary-navigation").is_visible()
        page.locator("#participants-nav").click()
        page.get_by_role("button", name="Люди", exact=True).click()
        page.locator('[data-screen-id="P01"][data-state="content"]').wait_for()
        page.get_by_role("button", name="Лидерборд").click()
        page.get_by_text("В лидерборде пока никого нет.").wait_for()  # noqa: RUF001

        page.locator("#participants-nav").click()
        page.get_by_role("button", name="Люди", exact=True).click()
        page.locator('[data-screen-id="P01"][data-state="content"]').wait_for()
        page.get_by_role("button", name="Задания", exact=True).click()
        page.get_by_role("heading", name="Задания").wait_for()
        modes.update(member="pending", leaderboard="pending")
        open_profile()
        page.locator("h2", has_text=malicious).wait_for()
        assert page.get_by_text("Загружаем профиль…").count() == 0
        page.wait_for_timeout(50)
        assert {urlsplit(route.request.url).path for route in pending} == {
            f"/api/v1/members/{member_id}"
        }
        catalog_nav = page.get_by_role("button", name="Задания", exact=True)
        assert page.get_by_role("button", name="Назад").is_visible()
        catalog_nav.click()
        page.get_by_role("heading", name="Задания").wait_for()
        late_member = next(route for route in pending if "/members/" in route.request.url)
        late_member.fulfill(json=member)
        pending.remove(late_member)
        page.wait_for_timeout(50)
        assert page.get_by_role("heading", name="Профиль").count() == 0
        assert catalog_nav.evaluate("node => node === document.activeElement")
        assert requests
        assert {
            ("PUT", "/api/v1/me/profile"),
            ("GET", "/api/v1/me"),
            ("GET", "/api/v1/members"),
            ("GET", f"/api/v1/members/{member_id}"),
            ("GET", "/api/v1/community-stats/leaderboard"),
            ("GET", "/api/v1/task-cities"),
            ("GET", "/api/v1/task-home"),
        } == set(requests)
        assert {
            "/api/v1/me",
            "/api/v1/members",
            f"/api/v1/members/{member_id}",
            "/api/v1/community-stats/leaderboard",
            "/api/v1/task-cities",
            "/api/v1/task-home",
            "/api/v1/me/profile",
        } == {path for _method, path in requests}
        browser.close()


def test_participants_density_and_leaderboard_periods_are_race_safe(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    member_ids = [f"00000000-0000-0000-0000-{index:012d}" for index in range(101, 107)]
    names = [
        "Мария Крылова",
        "Илья Петров",
        "Анна Соколова",
        "Денис Волков",
        "Елена Ли",
        "Макс Орлов",
    ]
    members = [
        {
            "member_id": member_id,
            "telegram_username": f"member{index}",
            "display_name": name,
            "city": None if index == 0 else ("Buenos Aires" if index % 2 else "Córdoba"),
            "short_bio": None,
            "current_goal": None,
            "help_categories": [],
            "skill_tags": [] if index == 0 else ["Дизайн", "Исследования"],
            "availability": "LEGACY_AVAILABILITY_VALUE",
            "experience_total": 20 - index,
            "level_number": 7 - index,
            "karma": {"score": 12 - index, "count": 4},
            "reliability": {
                "accepted": 5,
                "approved_weight": "5",
                "no_show": 0,
                "rate": "0.98",
            },
        }
        for index, (member_id, name) in enumerate(zip(member_ids, names, strict=True))
    ]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        pulse_variants = (
            (
                375,
                812,
                4,
                "2026-08-01T00:00:00Z",
                (
                    *(f"2025-{month:02d}-01" for month in range(9, 13)),
                    *(f"2026-{month:02d}-01" for month in range(1, 9)),
                ),
                "Сообщения по месяцам",
                12,
                11,
            ),
            (
                430,
                932,
                5,
                "2024-03-01T00:00:00Z",
                tuple(f"{year}-01-01" for year in range(2022, 2027)),
                "Сообщения по годам",
                5,
                2,
            ),
        )
        for (
            width,
            height,
            minimum_visible,
            tracking_started_at,
            all_bucket_dates,
            all_chart_label,
            all_column_count,
            all_zero_column_count,
        ) in pulse_variants:
            page = _new_page(browser)
            page.set_viewport_size({"width": width, "height": height})
            period_requests: list[str] = []
            pending_week: list[Route] = []
            pending_all: list[Route] = []

            page.route(
                "**/api/v1/me",
                lambda route: route.fulfill(
                    json={
                        "member_id": member_ids[0],
                        "display_name": names[0],
                        "credit_balance": None,
                        "experience_total": None,
                        "level": {"number": 7, "display_name": "Участник"},
                        "statistics": {"completed_tasks": None, "created_tasks": None},
                    }
                ),
            )
            page.route(
                "**/api/v1/members?*",
                lambda route: route.fulfill(json={"items": members}),
            )
            page.route(
                "**/api/v1/members/*",
                lambda route: route.fulfill(
                    json=next(
                        item for item in members if route.request.url.endswith(item["member_id"])
                    )
                ),
            )
            page.route(
                "**/api/v1/tasks",
                lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
            )

            def pulse_route(
                route: Route,
                *,
                bound_all_bucket_dates: tuple[str, ...] = all_bucket_dates,
                bound_tracking_started_at: str = tracking_started_at,
                bound_all_zero_count: int = all_zero_column_count,
            ) -> None:
                period = parse_qs(urlsplit(route.request.url).query)["period"][0]
                bucket_dates = {
                    "week": [f"2026-08-{day:02d}" for day in range(22, 29)],
                    "month": [f"2026-08-{day:02d}" for day in range(1, 31)],
                    "year": [f"2025-{month:02d}-01" for month in range(1, 13)],
                    "all": bound_all_bucket_dates,
                }[period]
                route.fulfill(
                    json={
                        "member_id": member_ids[0],
                        "tracking_started_at": bound_tracking_started_at,
                        "calculated_at": "2026-08-28T12:00:00Z",
                        "summary": {
                            "messages": 42,
                            "reactions_given": 20,
                            "reactions_received": 16,
                        },
                        "series": [
                            {
                                "bucket_start": bucket_start,
                                "messages": (
                                    0
                                    if index < (bound_all_zero_count if period == "all" else 1)
                                    else index + 1
                                ),
                                "reactions_given": 0 if index == 0 else index % 5 + 1,
                                "reactions_received": 0 if index == 0 else index % 4 + 1,
                            }
                            for index, bucket_start in enumerate(bucket_dates)
                        ],
                        "reaction_breakdown": [
                            {
                                "reaction": {"type": "emoji", "emoji": emoji},
                                "given": 16 - index,
                                "received": 8 - index,
                            }
                            for index, emoji in enumerate(
                                ("👍", "🔥", "💗", "👏", "🎉", "😁", "🤝", "⚡")
                            )
                        ],
                        "achievements": [
                            {
                                "code": code,
                                "level": level,
                                "current": current,
                                "next_level_at": threshold,
                                "message_url": (
                                    "https://t.me/c/1234567890/42"
                                    if code in {"star", "consilium"}
                                    else None
                                ),
                                "unlocked": level > 0
                                or (code in {"star", "consilium"} and current > 0),
                            }
                            for code, level, current, threshold in (
                                ("speaker", 2, 42, 60),
                                ("magnet", 3, 26, 30),
                                ("petrosyan", 1, 8, 15),
                                ("sharp", 0, 3, 5),
                                ("firefighter", 0, 4, 5),
                                ("heartbreaker", 1, 6, 15),
                                ("support", 3, 64, 120),
                                ("regular", 0, 2, 3),
                                ("explorer", 0, 1, 2),
                                ("streak", 0, 2, 3),
                                ("dialog", 0, 9, 10),
                                ("wake_up", 0, 0, 1),
                                ("bread_and_salt", 0, 0, 1),
                                ("onboarder", 0, 0, 1),
                                ("star", 0, 37, None),
                                ("consilium", 0, 8, None),
                                ("wealth", 3, 70, 100),
                                ("manager", 0, 0, 1),
                            )
                        ],
                    }
                )

            page.route("**/api/v1/community-stats/pulse?*", pulse_route)

            def leaderboard_route(
                route: Route,
                *,
                bound_requests: list[str] = period_requests,
                bound_pending: list[Route] = pending_week,
                bound_pending_all: list[Route] = pending_all,
            ) -> None:
                period = parse_qs(urlsplit(route.request.url).query)["period"][0]
                bound_requests.append(period)
                if period == "week" and not bound_pending:
                    bound_pending.append(route)
                    return
                if period == "all" and not bound_pending_all:
                    bound_pending_all.append(route)
                    return
                offset = {"week": 10, "month": 20, "year": 25, "all": 30}[period]
                route.fulfill(
                    json={
                        "items": [
                            {
                                "rank": index,
                                "member_id": member_id,
                                "display_name": names[index - 1],
                                "value": offset - index + 1,
                            }
                            for index, member_id in enumerate(member_ids, start=1)
                        ],
                        "tracking_started_at": "2026-08-01T00:00:00Z",
                        "calculated_at": "2026-08-28T12:00:00Z",
                    }
                )

            page.route("**/api/v1/community-stats/leaderboard?*", leaderboard_route)
            page.goto(mini_app_url)
            page.get_by_role("button", name="Комьюнити", exact=True).click()
            page.locator('[data-screen-id="P08"][data-state="content"]').wait_for()
            expect(page.get_by_role("button", name="Пульс", exact=True)).to_have_attribute(
                "aria-pressed", "true"
            )
            page.get_by_role("button", name="Люди", exact=True).click()
            page.locator(".member-row").nth(5).wait_for()
            assert page.get_by_text("LEGACY_AVAILABILITY_VALUE", exact=True).count() == 0

            geometry = page.evaluate(
                """() => {
                  const screen = document.querySelector('.screen').getBoundingClientRect();
                  const tabs = document.querySelector('.participants-tabs').getBoundingClientRect();
                  const rows = [...document.querySelectorAll('.member-row')]
                    .map((node) => node.getBoundingClientRect());
                  const first = rows[0];
                  return {
                    visible: rows.filter((row) => (
                      row.top >= screen.top && row.bottom <= screen.bottom
                    )).length,
                    firstVisible: first.top >= screen.top && first.bottom <= screen.bottom,
                    scrollTop: document.querySelector('.screen').scrollTop,
                    overflow: document.documentElement.scrollWidth > innerWidth,
                    tabsOffset: tabs.top - screen.top,
                  };
                }"""
            )
            assert geometry["firstVisible"] is True
            assert geometry["scrollTop"] == 0
            assert geometry["overflow"] is False
            assert geometry["tabsOffset"] < 20
            assert geometry["visible"] >= minimum_visible
            heading_box = page.locator(".screen-heading").bounding_box()
            assert heading_box is not None
            assert heading_box["width"] <= 1
            assert heading_box["height"] <= 1
            assert page.get_by_text("Имя или @username", exact=True).count() == 0
            assert page.get_by_role("button", name="Найти", exact=True).count() == 0
            search = page.get_by_placeholder("Найти участника")
            assert search.get_attribute("aria-label") == "Найти участника"
            search.fill(" \u0430 ")
            with page.expect_request(lambda request: "query=%D0%B0" in request.url):
                search.press("Enter")
            assert page.get_by_text("Минимум", exact=False).count() == 0

            page.locator(".member-row").first.click()
            page.locator('[data-screen-id="P02"]').wait_for()
            for legacy_label in (
                "Текущая цель",
                "Категории помощи",
                "Доступность",
            ):
                assert page.get_by_text(legacy_label, exact=True).count() == 0
            assert page.get_by_text("LEGACY_AVAILABILITY_VALUE", exact=True).count() == 0
            page.get_by_role("button", name="Назад").click()
            page.locator('[data-screen-id="P01"]').wait_for()

            page.get_by_role("button", name="Пульс", exact=True).click()
            page.locator('[data-screen-id="P08"][data-state="content"]').wait_for()
            assert page.locator(".participants-tabs button").all_text_contents() == [
                "Пульс",
                "Люди",
                "Лидерборд",
            ]
            assert page.locator(".pulse-card h2, .pulse-helper").count() == 0
            assert page.get_by_text("получено реакций", exact=True).count() == 1
            assert page.get_by_text("поставлено реакций", exact=True).count() == 1
            assert page.get_by_text("Сообщения по дням", exact=True).is_visible()
            assert page.locator(".pulse-chart-week .pulse-chart-column.is-zero").count() == 1
            assert (
                page.locator(".pulse-chart-week .pulse-chart-column")
                .nth(1)
                .locator(".pulse-chart-bar")
                .get_attribute("title")
                == "2"
            )
            zero_geometry = page.locator(".pulse-chart-week .pulse-chart-column").first.evaluate(
                """column => {
                  const zero = column.querySelector('.pulse-chart-zero').getBoundingClientRect();
                  const bar = column.parentElement.children[1]
                    .querySelector('.pulse-chart-bar').getBoundingClientRect();
                  return {
                    zeroBottom: zero.bottom,
                    barBottom: bar.bottom,
                    pseudoBottom: getComputedStyle(
                      column.querySelector('.pulse-chart-zero'),
                      '::after',
                    ).bottom,
                  };
                }"""
            )
            assert abs(zero_geometry["zeroBottom"] - zero_geometry["barBottom"]) <= 0.5
            assert zero_geometry["pseudoBottom"] == "0px"
            messages_metric = page.get_by_role("button", name=re.compile(r"^\d+ сообщений$"))
            received_reactions = page.get_by_role(
                "button", name=re.compile(r"^\d+ получено реакций$")
            )
            given_reactions = page.get_by_role(
                "button", name=re.compile(r"^\d+ поставлено реакций$")
            )
            assert messages_metric.get_attribute("aria-pressed") == "true"
            assert received_reactions.get_attribute("aria-pressed") == "false"
            assert given_reactions.get_attribute("aria-pressed") == "false"
            visual_panel = page.locator(".pulse-visual-panel")
            visual_panel_handle = visual_panel.element_handle()
            visual_height = visual_panel.evaluate("node => node.getBoundingClientRect().height")
            pulse_card_height = page.locator(".pulse-card").evaluate(
                "node => node.getBoundingClientRect().height"
            )
            pulse_scroll_before = page.locator(".screen").evaluate("node => node.scrollTop")
            received_reactions.click()
            assert visual_panel_handle.evaluate("node => node.isConnected") is True
            assert page.locator(".screen").evaluate("node => node.scrollTop") == pulse_scroll_before
            assert messages_metric.get_attribute("aria-pressed") == "false"
            assert received_reactions.get_attribute("aria-pressed") == "true"
            assert given_reactions.get_attribute("aria-pressed") == "false"
            assert visual_panel.get_attribute("aria-label") == "Полученные реакции по дням"
            received_bar_styles = page.locator(".pulse-chart-week .pulse-chart-bar").evaluate_all(
                "nodes => nodes.map(node => node.getAttribute('style'))"
            )
            assert len(received_bar_styles) == 6
            assert (
                visual_panel.evaluate("node => node.getBoundingClientRect().height")
                == visual_height
            )
            assert (
                page.locator(".pulse-card").evaluate("node => node.getBoundingClientRect().height")
                == pulse_card_height
            )
            given_reactions.click()
            assert page.locator(".screen").evaluate("node => node.scrollTop") == pulse_scroll_before
            assert messages_metric.get_attribute("aria-pressed") == "false"
            assert received_reactions.get_attribute("aria-pressed") == "false"
            assert given_reactions.get_attribute("aria-pressed") == "true"
            assert visual_panel.get_attribute("aria-label") == "Поставленные реакции по дням"
            given_bar_styles = page.locator(".pulse-chart-week .pulse-chart-bar").evaluate_all(
                "nodes => nodes.map(node => node.getAttribute('style'))"
            )
            assert given_bar_styles != received_bar_styles
            assert (
                visual_panel.evaluate("node => node.getBoundingClientRect().height")
                == visual_height
            )
            assert (
                page.locator(".pulse-card").evaluate("node => node.getBoundingClientRect().height")
                == pulse_card_height
            )
            messages_metric.click()
            assert messages_metric.get_attribute("aria-pressed") == "true"
            assert page.get_by_text("Сообщения по дням", exact=True).is_visible()
            assert (
                visual_panel.evaluate("node => node.getBoundingClientRect().height")
                == visual_height
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth") is True
            assert page.get_by_role("button", name="Год", exact=True).is_visible()
            assert page.get_by_role("button", name="Всё время", exact=True).is_visible()
            assert page.locator(".achievement-tile.is-unlocked").count() == 8
            assert page.locator(".achievement-tile.is-locked").count() == 10
            assert page.locator(".achievement-tile.is-record").count() == 2
            assert page.get_by_role("button", name="Петросян, уровень 1", exact=True).is_visible()
            assert page.get_by_role("button", name="Будильник, не открыто", exact=True).is_visible()
            assert page.get_by_role("button", name="Хлеб-соль, не открыто", exact=True).is_visible()
            assert page.get_by_role("button", name="Онбордист, не открыто", exact=True).is_visible()
            assert page.get_by_role(
                "button",
                name="Звезда, личный рекорд 37 реакций",
                exact=True,
            ).is_visible()
            assert page.get_by_role(
                "button",
                name="Консилиум, личный рекорд 8 участников",
                exact=True,
            ).is_visible()
            achievement_geometry = page.locator(".achievements-card").evaluate(
                """card => {
                  const tiles = [...card.querySelectorAll('.achievement-tile')];
                  const icons = [...card.querySelectorAll('.achievement-icon')];
                  return {
                    cardHeight: Math.round(card.getBoundingClientRect().height),
                    tileHeights: [...new Set(tiles.map(tile => (
                      Math.round(tile.getBoundingClientRect().height)
                    )))],
                    iconSizes: [...new Set(icons.map(icon => (
                      Math.round(icon.getBoundingClientRect().height)
                    )))],
                    rows: new Set(tiles.map(tile => (
                      Math.round(tile.getBoundingClientRect().top)
                    ))).size,
                  };
                }"""
            )
            assert achievement_geometry["cardHeight"] <= 550
            assert achievement_geometry["tileHeights"] == [72]
            assert achievement_geometry["iconSizes"] == [34]
            assert achievement_geometry["rows"] == 6
            assert page.locator(".achievement-detail-sheet").count() == 0
            achievement = page.get_by_role("button", name="Магнит, уровень 3", exact=True)
            page.set_viewport_size({"width": width, "height": 620})
            achievement.evaluate("node => node.scrollIntoView({block: 'center'})")
            scroll_before = page.locator(".screen").evaluate("node => node.scrollTop")
            assert scroll_before > 0
            achievement.click()
            detail = page.locator(".achievement-detail-sheet")
            detail.wait_for()
            assert page.locator(".screen").evaluate("node => node.scrollTop") == scroll_before
            assert detail.get_by_text("Как получить", exact=True).is_visible()
            assert detail.get_by_text(
                "Получайте реакции на свои сообщения.",
                exact=True,
            ).is_visible()
            assert detail.get_by_text("Уровни:", exact=False).count() == 0
            assert detail.get_by_text("26 из 30", exact=True).is_visible()
            page.get_by_role("button", name="Закрыть достижение", exact=True).click()
            assert page.locator(".achievement-detail-sheet").count() == 0
            assert page.locator(".screen").evaluate("node => node.scrollTop") == scroll_before
            assert page.evaluate("document.activeElement?.dataset.achievementCode") == "magnet"
            star = page.get_by_role(
                "button",
                name="Звезда, личный рекорд 37 реакций",
                exact=True,
            )
            star.click()
            detail = page.locator(".achievement-detail-sheet")
            detail.wait_for()
            assert detail.get_by_text("Личный рекорд", exact=True).is_visible()
            assert detail.get_by_text("37", exact=True).is_visible()
            assert detail.get_by_text(
                "реакций на одном сообщении",
                exact=True,
            ).is_visible()
            assert detail.locator(".achievement-progress-track").count() == 0
            record_link = detail.get_by_role("link", name="Открыть сообщение в Telegram")
            assert record_link.get_attribute("href") == "https://t.me/c/1234567890/42"
            assert record_link.get_attribute("rel") == "noopener noreferrer"
            page.evaluate(
                "window.recordLinks=[]; "
                "window.Telegram={WebApp:{openTelegramLink:u=>recordLinks.push(u)}}"
            )
            record_link.click()
            assert page.evaluate("recordLinks") == ["https://t.me/c/1234567890/42"]
            page.get_by_role("button", name="Закрыть достижение", exact=True).click()
            page.get_by_role(
                "button", name="Консилиум, личный рекорд 8 участников", exact=True
            ).click()
            detail = page.locator(".achievement-detail-sheet")
            assert detail.get_by_role("link", name="Открыть сообщение в Telegram").is_visible()
            page.get_by_role("button", name="Закрыть достижение", exact=True).click()
            page.set_viewport_size({"width": width, "height": height})
            page.get_by_role("button", name="Месяц", exact=True).click()
            page.locator(".pulse-chart-month .pulse-chart-bar").first.wait_for()
            assert page.locator(".pulse-chart-month .pulse-chart-bar").count() == 29
            assert page.locator(".pulse-chart-month .pulse-chart-column.is-zero").count() == 1
            assert page.locator(".pulse-chart-month .pulse-chart-label").count() == 0
            assert page.get_by_text("Сообщения по дням", exact=True).is_visible()
            page.get_by_role("button", name="Год", exact=True).click()
            page.get_by_text("Сообщения по месяцам", exact=True).wait_for()
            assert page.locator(".pulse-chart-year .pulse-chart-column.is-zero").count() == 1
            page.get_by_role("button", name="Всё время", exact=True).click()
            page.get_by_text(all_chart_label, exact=True).wait_for()
            assert page.locator(".pulse-chart-all .pulse-chart-column").count() == all_column_count
            assert (
                page.locator(".pulse-chart-all .pulse-chart-column.is-zero").count()
                == all_zero_column_count
            )
            assert page.locator(".pulse-chart-empty").count() == 0
            page.get_by_role("button", name="Неделя", exact=True).click()

            page.get_by_role("button", name="Лидерборд").click()
            assert page.get_by_text("Рейтинг активности", exact=True).count() == 0
            assert page.get_by_text("Выберите, что сравнивать.", exact=True).count() == 0
            assert page.locator(".leaderboard-metrics, .leaderboard-heading").count() == 0
            leaderboard_filter = page.get_by_role("button", name="Рейтинг по: Опыт")
            assert leaderboard_filter.get_attribute("aria-expanded") == "false"
            leaderboard_scroll = page.locator(".screen").evaluate("node => node.scrollTop")
            leaderboard_filter.click()
            metric_dialog = page.get_by_role("dialog", name="Рейтинг по")
            metric_dialog.wait_for()
            assert leaderboard_filter.get_attribute("aria-expanded") == "true"
            assert metric_dialog.get_by_role("radio").count() == 21
            assert metric_dialog.get_by_text("Основное", exact=True).is_visible()
            assert metric_dialog.get_by_text("Активность", exact=True).is_visible()
            assert metric_dialog.get_by_text("Достижения · уровень", exact=True).is_visible()
            assert (
                metric_dialog.get_by_role("radio", name="Опыт").get_attribute("aria-checked")
                == "true"
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth") is True
            metric_dialog.get_by_role("radio", name="Сообщения").click()
            leaderboard_filter = page.get_by_role("button", name="Рейтинг по: Сообщения")
            assert page.locator(".leaderboard-filter-sheet").count() == 0
            assert page.locator(".screen").evaluate("node => node.scrollTop") == leaderboard_scroll
            expect(leaderboard_filter).to_be_focused()
            page.get_by_role("button", name="Месяц").click()
            page.get_by_text("20 сообщ.").wait_for()
            pending_week[0].fulfill(
                json={
                    "items": [
                        {
                            "rank": 1,
                            "member_id": member_ids[0],
                            "display_name": names[0],
                            "value": 10,
                        }
                    ]
                }
            )
            page.wait_for_timeout(50)
            assert page.get_by_text("20 сообщ.").count() == 1
            assert page.get_by_text("10 сообщ.").count() == 0
            page.get_by_role("button", name="Всё время").click()
            page.get_by_role("button", name="Неделя").click()
            page.get_by_text("10 сообщ.").wait_for()
            assert page.get_by_text("Загружаем данные…", exact=True).count() == 0
            pending_all[0].fulfill(
                json={
                    "items": [
                        {
                            "rank": 1,
                            "member_id": member_ids[0],
                            "display_name": names[0],
                            "value": 30,
                        }
                    ]
                }
            )
            page.wait_for_timeout(50)
            assert page.get_by_text("10 сообщ.").count() == 1
            assert page.get_by_text("30 сообщ.").count() == 0
            page.get_by_role("button", name="Всё время").click()
            page.get_by_text("30 сообщ.").wait_for()
            assert set(period_requests) == {"week", "month", "all"}
            assert page.locator(".leaderboard-row").count() == 1
            page.get_by_role("button", name="Месяц").click()
            page.get_by_text("20 сообщ.").wait_for()
            assert page.locator(".leaderboard-row").count() == len(member_ids)
            assert page.locator(".leaderboard-row.is-current").count() == 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            leaderboard_scroll = page.locator(".screen").evaluate("node => node.scrollTop")
            leaderboard_filter.click()
            metric_dialog = page.get_by_role("dialog", name="Рейтинг по")
            metric_dialog.get_by_role("radio", name="Магнит").click()
            achievement_filter = page.get_by_role("button", name="Рейтинг по: Магнит")
            expect(achievement_filter).to_be_focused()
            assert (
                page.get_by_role("button", name="Всё время", exact=True).get_attribute(
                    "aria-pressed"
                )
                == "true"
            )
            assert page.get_by_role("button", name="Всё время", exact=True).is_enabled()
            for locked_period in ("Неделя", "Месяц", "Год"):
                locked_button = page.get_by_role("button", name=locked_period, exact=True)
                assert locked_button.is_disabled()
                assert locked_button.get_attribute("aria-pressed") == "false"
            assert page.locator(".screen").evaluate("node => node.scrollTop") == leaderboard_scroll
            assert page.locator(".leaderboard-value").first.text_content().startswith("Ур. ")  # noqa: RUF001
            achievement_filter.click()
            page.get_by_role("button", name="Закрыть выбор рейтинга", exact=True).click()
            assert achievement_filter.evaluate("node => document.activeElement === node") is True
            achievement_filter.click()
            page.get_by_role("dialog", name="Рейтинг по").get_by_role("radio", name="Опыт").click()
            experience_filter = page.get_by_role("button", name="Рейтинг по: Опыт")
            expect(experience_filter).to_be_focused()
            assert (
                page.get_by_role("button", name="Месяц", exact=True).get_attribute("aria-pressed")
                == "true"
            )
            for active_period in ("Неделя", "Месяц", "Год", "Всё время"):
                assert page.get_by_role("button", name=active_period, exact=True).is_enabled()

            page.get_by_role("button", name="Параметры", exact=True).click()
            page.locator(".settings-link-row:not(.settings-theme-row)").click()
            page.locator(".profile-overview").wait_for()
            assert page.url.endswith("#/profile")
            heading_box = page.locator("#screen-title").bounding_box()
            assert heading_box is None or (heading_box["width"] <= 1 and heading_box["height"] <= 1)
            assert page.locator("#screen-title").text_content() == "Профиль"
            assert page.get_by_text("Карма", exact=True).count() == 1
            assert page.get_by_text("Надёжность", exact=True).count() == 0
            assert page.get_by_text("—", exact=True).count() >= 2
            assert page.locator("[data-profile-action]").count() == 6
            assert page.locator('[data-screen-id="P07"]').count() == 0
            page.close()
        browser.close()


def test_karma_vote_retries_one_action_and_refreshes_safe_profile(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    actor_id = "00000000-0000-0000-0000-000000000082"
    target_id = "00000000-0000-0000-0000-000000000083"
    private_comment = "Очень полезная совместная работа"
    me = {"member_id": actor_id, "display_name": "Алекс"}
    own_member = {
        "member_id": actor_id,
        "display_name": "Алекс",
        "karma": {"score": 0, "count": 0},
        "reliability": {"rate": None},
    }
    target_member = {
        "member_id": target_id,
        "display_name": "Мария",
        "karma": {"score": 2, "count": 2},
        "reliability": {"rate": "1.0"},
        "can_rate_karma": True,
    }
    actions: list[tuple[str, str]] = []
    target_reads = 0

    def member_route(route: Route) -> None:
        nonlocal target_reads
        if route.request.url.endswith(actor_id):
            route.fulfill(json=own_member)
            return
        target_reads += 1
        if target_reads > 1:
            target_member["karma"] = {"score": 3, "count": 3}
        route.fulfill(json=target_member)

    def karma_route(route: Route) -> None:
        assert route.request.method == "POST"
        body = route.request.post_data_json
        assert body is not None
        action = body["action"]
        key = route.request.headers["idempotency-key"]
        actions.append((action, key))
        if action == "begin":
            route.fulfill(
                json={
                    "action": action,
                    "target_id": target_id,
                    "step": "value",
                    "revision": 0,
                    "aggregate": None,
                }
            )
        elif action == "save_value" and sum(item[0] == action for item in actions) == 1:
            route.abort()
        elif action == "save_value":
            assert body["expected_revision"] == 0
            route.fulfill(
                json={
                    "action": action,
                    "target_id": target_id,
                    "step": "comment",
                    "revision": 1,
                    "aggregate": None,
                }
            )
        elif action == "save_comment":
            assert body["expected_revision"] == 1
            assert body["comment"] == private_comment
            route.fulfill(
                json={
                    "action": action,
                    "target_id": target_id,
                    "step": "confirm",
                    "revision": 2,
                    "aggregate": None,
                }
            )
        else:
            assert action == "confirm"
            assert body["expected_revision"] == 2
            route.fulfill(
                json={
                    "action": action,
                    "target_id": target_id,
                    "step": "confirmed",
                    "revision": 1,
                    "aggregate": {"score": 3, "count": 3},
                }
            )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        console_messages: list[str] = []
        page.on("console", lambda message: console_messages.append(message.text))
        page.route("**/api/v1/me", lambda route: route.fulfill(json=me))
        page.route("**/api/v1/members/*/karma-vote", karma_route)
        page.route("**/api/v1/members/*", member_route)
        page.route(
            "**/api/v1/members?*",
            lambda route: route.fulfill(
                json={
                    "items": [
                        target_member
                        | {
                            "telegram_username": "maria",
                            "level_number": 2,
                        }
                    ]
                }
            ),
        )
        page.route(
            "**/api/v1/community-stats/leaderboard?*",
            lambda route: route.fulfill(
                json={
                    "items": [
                        {
                            "rank": 1,
                            "member_id": target_id,
                            "display_name": "Мария",
                            "value": 10,
                        }
                    ]
                }
            ),
        )
        page.route(
            "**/api/v1/community-stats/pulse?*",
            lambda route: route.fulfill(status=503, json={"code": "community_stats_unavailable"}),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.goto(mini_app_url)
        page.get_by_role("button", name="Комьюнити", exact=True).click()
        page.get_by_role("button", name="Лидерборд").click()
        page.locator(".leaderboard-row", has_text="Мария").click()
        page.locator('[data-screen-id="P02"]').wait_for()
        assert page.get_by_role("heading", name="Оценить взаимодействие").count() == 0
        page.get_by_role("button", name="Оценить карму").click()
        page.get_by_role("heading", name="Оценить взаимодействие").wait_for()
        page.get_by_label(re.compile("^Комментарий")).fill(private_comment)
        page.get_by_role("button", name="Подтвердить оценку").click()
        page.get_by_role("button", name="Сохранить оценку").click()
        page.get_by_text("Оценка недоступна", exact=False).wait_for()
        actions_before = len(actions)
        _connected_control(page, "PE-059", "authoritative_karma_success").click()
        page.get_by_role("button", name="К профилю").click()  # noqa: RUF001
        karma_metric = page.locator(".metric-card", has_text="Карма")
        karma_metric.locator("strong", has_text="3").wait_for()
        assert len(actions) == actions_before + 3

        value_keys = [key for action, key in actions if action == "save_value"]
        assert len(value_keys) == 2
        assert value_keys[0] == value_keys[1]
        assert [action for action, _key in actions] == [
            "begin",
            "save_value",
            "save_value",
            "save_comment",
            "confirm",
        ]
        assert private_comment not in page.locator("body").inner_text()
        assert all(private_comment not in message for message in console_messages)
        browser.close()


def test_assignment_states_and_late_detail_are_safe(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    assignment_id = "00000000-0000-0000-0000-000000000054"
    assignment = {
        "id": assignment_id,
        "task_id": "00000000-0000-0000-0000-000000000053",
        "task_title": "Собрать план",
        "task_origin": "member",
        "assignment_status": "submitted",
        "accepted_at": "2026-08-17T20:00:00Z",
        "submitted_at": "2026-08-17T20:30:00Z",
        "review_deadline_at": "2026-08-20T20:30:00Z",
        "reject_dispute_deadline_at": None,
        "reviewed_at": None,
        "task_deadline_at": "2026-08-21T20:00:00Z",
        "result_summary": "План отправлен",
        "case_status": None,
    }
    detail = assignment | {
        "category_name": "Практическая помощь",
        "category_icon": None,
        "task_kind": "solo",
        "time_size": "s",
        "description": "Собрать понятный план",
        "performer_instructions": "Проверить шаги",
        "completion_criteria": "План понятен",
        "reward_per_performer": 3,
        "format": "online",
        "city": None,
        "minimum_level": 1,
        "performer_slots": 1,
        "submission_contract": None,
        "can_submit": False,
        "can_cancel": False,
        "can_dispute": False,
    }
    list_mode: dict[str, Any] = {"status": 200, "items": []}
    detail_mode: dict[str, Any] = {"status": 200, "pending": False}
    pending_routes: list[Route] = []
    dispute_keys: list[str] = []

    def assignments_route(route: Route) -> None:
        route.fulfill(
            status=list_mode["status"],
            json={"items": list_mode["items"], "next_cursor": None},
        )

    def detail_route(route: Route) -> None:
        if detail_mode["pending"]:
            pending_routes.append(route)
            return
        route.fulfill(status=detail_mode["status"], json=detail)

    def dispute_route(route: Route) -> None:
        assert route.request.method == "POST"
        dispute_keys.append(route.request.headers["idempotency-key"])
        assert route.request.post_data_json == {"comment": "Нужна независимая проверка"}
        detail.update(assignment_status="disputed", case_status="open", can_dispute=False)
        route.fulfill(status=204)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.add_init_script(
            "let cacheNow = 1000; Date.now = () => cacheNow; "
            "globalThis.advanceCacheClock = value => { cacheNow += value; };"
        )
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(
                json={
                    "display_name": "Алекс",
                    "timezone": "America/Argentina/Buenos_Aires",
                }
            ),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route("**/api/v1/assignments?*", assignments_route)
        page.route(f"**/api/v1/assignments/{assignment_id}", detail_route)
        page.route(f"**/api/v1/assignments/{assignment_id}/disputes", dispute_route)
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(mini_app_url + "#/work?view_state=m01")
        page.get_by_text("Активных заданий пока нет.").wait_for()

        list_mode["status"] = 503
        page.evaluate("advanceCacheClock(60001)")
        with page.expect_response(lambda response: response.status == 503):
            page.reload()
        page.get_by_text("Не удалось загрузить активные назначения.").wait_for()  # noqa: RUF001

        list_mode["status"] = 401
        with page.expect_response(lambda response: response.status == 401):
            page.reload()
        page.get_by_text("Сессия истекла. Закройте и снова откройте Mini App.").wait_for()
        assert page.get_by_role("button", name="Повторить").count() == 0

        list_mode["status"] = 403
        page.reload()
        page.get_by_text("Назначения недоступны для этого аккаунта.").wait_for()
        assert page.get_by_role("button", name="Повторить").count() == 0

        list_mode.update(status=200, items=[assignment])
        page.reload()
        row = page.get_by_role("button", name=re.compile("Собрать план"))
        row.wait_for()
        assert row.get_by_text("План отправлен").count() == 1
        assert row.get_by_text(re.compile(r"до 21 авг"), exact=False).count() == 1

        detail_mode["status"] = 401
        row.click()
        page.get_by_text("Сессия истекла. Закройте и снова откройте Mini App.").wait_for()
        page.get_by_role("button", name="Назад").click()
        row = page.get_by_role("button", name=re.compile("Собрать план"))
        row.wait_for()

        detail_mode["status"] = 403
        row.click()
        page.get_by_text("Назначения недоступны для этого аккаунта.").wait_for()
        page.get_by_role("button", name="Назад").click()
        row = page.get_by_role("button", name=re.compile("Собрать план"))
        row.wait_for()

        detail_mode["status"] = 404
        row.click()
        page.get_by_text("Назначение больше не входит в активные.").wait_for()
        page.get_by_role("button", name="Назад").click()
        row = page.get_by_role("button", name=re.compile("Собрать план"))
        row.wait_for()

        detail_mode.update(status=200, pending=True)
        row.click()
        page.get_by_text("Загружаем назначение…").wait_for()
        assert len(pending_routes) == 1
        page.get_by_role("button", name="Назад").click()
        page.locator("h2", has_text="Что я выполняю").wait_for()
        pending_routes.pop().fulfill(status=200, json=detail)
        page.wait_for_timeout(50)
        assert page.get_by_text("Собрать понятный план").count() == 0
        assert page.get_by_role("button", name=re.compile("Собрать план")).count() == 1

        detail.update(
            assignment_status="rejected_pending_dispute",
            reject_dispute_deadline_at="2026-08-21T20:30:00Z",
            case_status=None,
            can_dispute=True,
        )
        detail_mode["pending"] = False
        page.get_by_role("button", name=re.compile("Собрать план")).click()
        page.get_by_text("Условия спора").wait_for()
        assert page.locator("time[datetime='2026-08-21T20:30:00Z']").count() == 1
        assert page.get_by_label("Причина пересмотра").count() == 0
        page.get_by_role("button", name="Подать спор").click()
        page.get_by_label("Причина пересмотра").fill("Нужна независимая проверка")
        disputes_before = len(dispute_keys)
        _connected_control(page, "PE-044", "open_dispute_materials").click()
        page.get_by_text("Передан команде модерации").wait_for()
        assert len(dispute_keys) == disputes_before + 1

        page.get_by_role("button", name="Назад").click()
        page.locator("h2", has_text="Что я выполняю").wait_for()
        detail.update(
            assignment_status="rejected_pending_dispute", case_status=None, can_dispute=False
        )
        page.get_by_role("button", name=re.compile("Собрать план")).click()
        page.get_by_text("Срок подачи спора истёк.").wait_for()
        assert page.get_by_role("button", name="Подать спор").count() == 0
        browser.close()


def _freeform_submission_rows() -> tuple[str, str, dict[str, object], dict[str, object]]:
    assignment_id = "00000000-0000-0000-0000-000000000071"
    draft_id = "00000000-0000-0000-0000-000000000072"
    assignment = {
        "id": assignment_id,
        "task_id": "00000000-0000-0000-0000-000000000070",
        "task_title": "Проверить форму",
        "task_origin": "member",
        "assignment_status": "accepted",
        "accepted_at": "2026-08-17T20:00:00Z",
        "submitted_at": None,
        "review_deadline_at": None,
        "reject_dispute_deadline_at": None,
        "reviewed_at": None,
        "task_deadline_at": "2026-08-21T20:00:00Z",
        "result_summary": None,
        "case_status": None,
    }
    detail = assignment | {
        "category_name": "Практическая помощь",
        "category_icon": None,
        "task_kind": "solo",
        "time_size": "s",
        "description": "Проверить форму без исполнения HTML",
        "performer_instructions": "Заполнить результат",
        "completion_criteria": "Есть понятный итог",
        "reward_per_performer": 3,
        "format": "online",
        "city": None,
        "minimum_level": 1,
        "performer_slots": 1,
        "submission_contract": "freeform_result_v1",
        "can_submit": True,
        "can_cancel": True,
        "can_dispute": False,
    }
    submitted = detail | {
        "assignment_status": "submitted",
        "result_summary": "Результат отправлен",
        "can_cancel": False,
    }
    return assignment_id, draft_id, assignment, submitted


def test_assignment_cancellation_returns_to_active_list(mini_app_url: str) -> None:
    assignment_id, _draft_id, assignment, submitted = _freeform_submission_rows()
    detail = submitted | {
        "assignment_status": "accepted",
        "result_summary": None,
        "can_cancel": True,
    }
    items = [assignment]
    operation_keys: list[str] = []

    def cancel(route: Route) -> None:
        assert route.request.method == "POST"
        operation_keys.append(route.request.headers["idempotency-key"])
        assert route.request.post_data_json == {"reason": "Cannot finish before deadline"}
        items.clear()
        route.fulfill(status=204)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(
                json={
                    "display_name": "Алекс",
                    "timezone": "America/Argentina/Buenos_Aires",
                }
            ),
        )
        page.route(
            "**/api/v1/tasks", lambda route: route.fulfill(json={"items": [], "next_cursor": None})
        )
        page.route(
            "**/api/v1/assignments?*",
            lambda route: route.fulfill(json={"items": items, "next_cursor": None}),
        )
        page.route(
            f"**/api/v1/assignments/{assignment_id}/cancellation",
            cancel,
        )
        page.route(
            f"**/api/v1/assignments/{assignment_id}", lambda route: route.fulfill(json=detail)
        )
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(mini_app_url + "#/work?view_state=m01")
        page.get_by_role("button", name=re.compile("Проверить форму")).click()
        page.locator('[data-screen-id="M03"]').wait_for()
        assert page.get_by_label("Причина отказа").count() == 0
        page.get_by_role("button", name="Отказаться от задания").click()
        page.get_by_label("Причина отказа").fill(" Cannot finish before deadline ")
        cancellations_before = len(operation_keys)
        _connected_control(page, "PE-036", "withdrawal_outcome").click()
        page.get_by_text("Активных заданий пока нет.").wait_for()
        assert len(operation_keys) == cancellations_before + 1
        assert page.url.endswith("/#/work?view_state=m01")
        assert page.evaluate("history.state") == {"screen": "assignments"}
        browser.close()


def test_freeform_submission_uses_preview_confirm_and_detail_refresh(  # noqa: C901, PLR0915
    mini_app_url: str,
) -> None:
    assignment_id, draft_id, assignment, submitted = _freeform_submission_rows()
    detail = submitted | {"assignment_status": "accepted", "result_summary": None}
    current_detail: dict[str, Any] = {"value": detail}
    result_text = "<script>globalThis.pwned=true</script> " + "Подробный результат. " * 80
    begin_keys: list[str] = []
    confirm_keys: list[str] = []
    review_keys: list[str] = []
    review_pending = {"value": True}
    owned_cancel_keys: list[str] = []
    assignment_task_id = assignment["task_id"]
    assert isinstance(assignment_task_id, str)
    owned_items = [
        {
            "id": assignment_task_id[:-1] + str(index),
            "title": f"Созданное задание {index}",
            "status": "published",
            "performer_slots": 2,
            "deadline_at": "2026-08-21T20:00:00Z",
            "assignees": (
                [
                    {
                        "member_id": "00000000-0000-0000-0000-000000000410",
                        "display_name": "Исполнитель",
                        "status": "submitted",
                    }
                ]
                if index == 1
                else []
            ),
            "cancellation_status": None,
            "cancellation_action": "request" if index == 1 else "cancel",
        }
        for index in range(1, 6)
    ]
    pending_confirm: list[Route] = []
    review = {
        "id": assignment_id,
        "task_title": "Проверить форму",
        "performer_display_name": "Участник",
        "review_deadline_at": "2026-08-20T20:30:00Z",
        "result": "<script>globalThis.pwned=true</script>",
        "available_decisions": ["full", "partial", "reject"],
    }

    def save(route: Route) -> None:
        request = route.request
        assert request.method == "PUT"
        assert request.headers["idempotency-key"].isdecimal()
        body = request.post_data_json
        assert isinstance(body, dict)
        assert body["expected_revision"] == 0
        assert body["payload"]["result"] == result_text
        route.fulfill(json={"id": draft_id, "revision": 1, "result": body["payload"]["result"]})

    def begin(route: Route) -> None:
        assert route.request.method == "POST"
        begin_keys.append(route.request.headers["idempotency-key"])
        if len(begin_keys) == 1:
            route.abort()
        else:
            route.fulfill(json={"id": draft_id, "revision": 0, "result": None})

    def confirm(route: Route) -> None:
        assert route.request.method == "POST"
        confirm_keys.append(route.request.headers["idempotency-key"])
        assert route.request.post_data_json == {"expected_revision": 1}
        if len(confirm_keys) == 1:
            route.fulfill(status=502, body="upstream unavailable", content_type="text/plain")
            return
        current_detail["value"] = submitted
        pending_confirm.append(route)

    def decide(route: Route) -> None:
        assert route.request.method == "POST"
        review_keys.append(route.request.headers["idempotency-key"])
        assert route.request.post_data_json == {
            "decision": "reject",
            "rejection_reason": "requirements_not_met",
            "rejection_comment": "Результат не соответствует критериям.",
        }
        if len(review_keys) == 1:
            route.abort()
        else:
            review_pending["value"] = False
            route.fulfill(status=204)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.route("**/api/v1/me", lambda route: route.fulfill(json={"display_name": "Алекс"}))
        page.route(
            "**/api/v1/tasks", lambda route: route.fulfill(json={"items": [], "next_cursor": None})
        )
        page.route(
            "**/api/v1/assignments?*",
            lambda route: route.fulfill(json={"items": [assignment], "next_cursor": None}),
        )
        page.route(
            f"**/api/v1/assignments/{assignment_id}",
            lambda route: route.fulfill(json=current_detail["value"]),
        )
        page.route(
            f"**/api/v1/assignments/{assignment_id}/submission-drafts",
            begin,
        )
        page.route(f"**/api/v1/submission-drafts/{draft_id}", save)
        page.route(f"**/api/v1/submission-drafts/{draft_id}/confirm", confirm)
        page.route(
            "**/api/v1/assignment-reviews",
            lambda route: route.fulfill(
                json={"items": [review] if review_pending["value"] else []}
            ),
        )
        page.route(
            "**/api/v1/owned-tasks",
            lambda route: route.fulfill(json={"items": owned_items}),
        )

        def cancel_owned(route: Route) -> None:
            owned_cancel_keys.append(route.request.headers["idempotency-key"])
            assert route.request.post_data is None
            if len(owned_cancel_keys) == 1:
                route.fulfill(status=502, body="retry", content_type="text/plain")
                return
            owned_items[0]["cancellation_status"] = "pending"
            owned_items[0]["cancellation_action"] = None
            route.fulfill(json={"status": "pending"})

        page.route("**/api/v1/owned-tasks/*/cancellation", cancel_owned)
        page.route(
            f"**/api/v1/assignment-reviews/{assignment_id}",
            lambda route: route.fulfill(json=review),
        )
        page.route(f"**/api/v1/assignment-reviews/{assignment_id}/decision", decide)
        page.goto(mini_app_url + "#/work?view_state=m01")
        page.get_by_role("button", name=re.compile("Проверить форму")).click()
        page.locator('[data-screen-id="M03"]').wait_for()
        assert page.get_by_role("textbox", name="Результат").count() == 0
        assert page.get_by_label("Причина отказа").count() == 0
        page.get_by_role("button", name="Отправить результат").click()
        page.get_by_role("button", name="Начать отправку").click()
        page.get_by_text("Сеть недоступна. Повторите запрос — он останется тем же.").wait_for()
        assert not page.get_by_role("button", name="Начать отправку").is_disabled()
        begins_before = len(begin_keys)
        _connected_control(page, "PE-030", "open_result_versions").click()
        result = page.get_by_role("textbox", name="Результат")
        assert len(begin_keys) == begins_before + 1
        assert result.evaluate("node => node === document.activeElement")
        assert begin_keys[0] == begin_keys[1]
        result.fill(result_text)
        page.locator(".screen").evaluate("node => { node.scrollTop = node.scrollHeight; }")
        page.get_by_role("button", name="Предпросмотр").click()
        page.locator('[data-screen-id="M05"]').wait_for()
        page.get_by_text(result_text, exact=True).wait_for()
        assert page.evaluate("globalThis.pwned") is None
        assert page.locator(".screen").evaluate("node => node.scrollTop") == 0
        page.locator(".screen").evaluate("node => { node.scrollTop = node.scrollHeight; }")
        page.get_by_role("button", name="Продолжить").click()
        page.locator('[data-screen-id="M06"]').wait_for()
        assert page.locator(".screen").evaluate("node => node.scrollTop") == 0
        assert page.locator("#screen-title").bounding_box()["y"] >= 0
        assert page.locator("#back").bounding_box()["y"] >= 0
        page.get_by_role("button", name="Отправить результат").click()
        page.get_by_text("Не удалось сохранить результат.").wait_for()  # noqa: RUF001
        confirms_before = len(confirm_keys)
        _connected_control(page, "PE-034", "authoritative_submit_success").click()
        assert len(confirm_keys) == confirms_before + 1
        assert confirm_keys[0] == confirm_keys[1]
        assert len(pending_confirm) == 1
        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="M03"]').wait_for()
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Мои задания").wait_for()
        pending_confirm.pop().fulfill(status=204)
        page.wait_for_timeout(50)
        assert page.get_by_role("heading", name="Мои задания").count() == 1
        page.get_by_role("button", name=re.compile("Проверить форму")).click()
        page.get_by_text("Результат отправлен").first.wait_for()
        assert page.get_by_role("button", name="Отправить результат").count() == 1
        assert page.locator("#primary-navigation").is_hidden()
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Мои задания").wait_for()
        page.get_by_role("button", name="Созданные мной").click()
        page.locator('[data-screen-id="M09"]').wait_for()
        assert page.get_by_role("button", name="Назад").is_hidden()
        assert page.locator("#primary-navigation").is_visible()
        assert page.get_by_role("heading", name="Мои опубликованные задания").count() == 0
        page.set_viewport_size({"width": 375, "height": 812})
        assert page.locator(".owned-task-card").evaluate_all(
            "nodes => nodes.slice(0, 4).every(node => "
            "node.getBoundingClientRect().bottom <= innerHeight)"
        )
        page.set_viewport_size({"width": 430, "height": 932})
        assert page.locator(".owned-task-card").evaluate_all(
            "nodes => nodes.slice(0, 5).every(node => "
            "node.getBoundingClientRect().bottom <= innerHeight)"
        )
        page.get_by_role("button", name=re.compile("Созданное задание 1")).click()
        page.get_by_role("button", name="Запросить отмену").click()
        assert page.get_by_role("button", name="Изменить", exact=True).count() == 0
        assert page.locator(".confirm-actions button").count() == 1
        assert page.locator(".confirm-actions").evaluate(
            "node => Math.abs(node.clientWidth - node.firstElementChild.offsetWidth) < 1"
        )
        page.get_by_role("button", name="Отправить запрос").click()
        page.get_by_text("Не удалось применить отмену").wait_for()  # noqa: RUF001
        page.get_by_role("button", name="Отправить запрос").click()
        page.get_by_text("Запрос на отмену отправлен исполнителям.").wait_for()
        assert owned_cancel_keys[0] == owned_cancel_keys[1]
        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="M09"]').wait_for()
        review_button = page.get_by_role(
            "button", name=re.compile("Ожидает проверки Проверить форму")
        )
        review_button.click()
        assert page.evaluate("globalThis.pwned") is None
        page.get_by_role("button", name="Назад").click()
        assert review_button.evaluate("node => node === document.activeElement")
        review_button.click()
        assert page.url.endswith(f"#/work/{assignment_id}?view_state=m11")
        _connected_control(page, "PE-040", "authoritative_review_success").last.click()
        assert page.url.endswith(f"#/work/{assignment_id}?view_state=m12")
        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="M11"]').wait_for()
        assert page.url.endswith(f"#/work/{assignment_id}?view_state=m11")
        _connected_control(page, "PE-040", "authoritative_review_success").last.click()
        assert page.url.endswith(f"#/work/{assignment_id}?view_state=m12")
        page.reload()
        page.locator('[data-screen-id="M11"]').wait_for()
        assert page.url.endswith(f"#/work/{assignment_id}?view_state=m11")
        _connected_control(page, "PE-040", "authoritative_review_success").last.click()
        page.get_by_label("Не соответствует условиям", exact=True).check()  # noqa: RUF001
        page.get_by_label("Комментарий к отклонению", exact=True).fill(
            "Результат не соответствует критериям."
        )
        for _attempt in range(2):
            reviews_before = len(review_keys)
            _connected_control(page, "PE-040", "authoritative_review_success").click()
            assert len(review_keys) == reviews_before + 1
            if len(review_keys) == 1:
                page.get_by_text("ключ останется тем же").wait_for()
        assert review_keys[0] == review_keys[1]
        page.get_by_role("button", name="К созданным заданиям").click()  # noqa: RUF001
        page.locator(".owned-review-list").wait_for(state="detached")
        browser.close()


def test_context_transitions_reset_both_scroll_axes_at_supported_viewports(
    mini_app_url: str,
) -> None:
    assignment_id = "00000000-0000-0000-0000-000000000073"
    draft_id = "00000000-0000-0000-0000-000000000074"
    member_id = "00000000-0000-0000-0000-000000000075"
    detail = {
        "id": assignment_id,
        "task_title": "Длинное назначение",
        "assignment_status": "accepted",
        "task_deadline_at": "2026-09-01T20:00:00Z",
        "description": "Описание " * 80,
        "completion_criteria": "Критерии " * 60,
        "performer_instructions": "Инструкция " * 60,
        "result_summary": None,
        "review_deadline_at": None,
        "reject_dispute_deadline_at": None,
        "case_status": None,
        "can_dispute": False,
        "can_submit": True,
        "can_cancel": False,
    }
    member = {
        "member_id": member_id,
        "telegram_username": "maria",
        "display_name": "Мария",
        "city": None,
        "short_bio": None,
        "current_goal": None,
        "help_categories": [],
        "skill_tags": [],
        "availability": None,
        "level_number": 2,
        "karma": {"score": 4, "count": 5},
        "reliability": {"rate": "0.9"},
    }

    def assert_top_left(page: Any) -> None:  # noqa: ANN401
        geometry = page.evaluate(
            """() => {
              const shell = document.querySelector('#app');
              const screen = document.querySelector('.screen');
              const back = document.querySelector('#back');
              const title = document.querySelector('#screen-title');
              const shellBox = shell.getBoundingClientRect();
              const backBox = back.getBoundingClientRect();
              const titleBox = title.getBoundingClientRect();
              return {
                windowX: scrollX, windowY: scrollY,
                documentX: document.scrollingElement.scrollLeft,
                documentY: document.scrollingElement.scrollTop,
                shellX: shell.scrollLeft, shellY: shell.scrollTop,
                screenX: screen.scrollLeft, screenY: screen.scrollTop,
                shellLeft: shellBox.left, backLeft: backBox.left,
                titleVisible: title.offsetParent !== null,
                titleLeft: titleBox.left, titleTop: titleBox.top,
              };
            }"""
        )
        assert (
            geometry
            | {
                "windowX": 0,
                "windowY": 0,
                "documentX": 0,
                "documentY": 0,
                "shellX": 0,
                "shellY": 0,
                "screenX": 0,
                "screenY": 0,
            }
            == geometry
        )
        assert geometry["backLeft"] >= geometry["shellLeft"]
        if geometry["titleVisible"]:
            assert geometry["titleLeft"] >= geometry["shellLeft"]
            assert geometry["titleTop"] >= 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width, height in ((375, 812), (430, 932)):
            page = _new_page(browser)
            page.set_viewport_size({"width": width, "height": height})
            page.route(
                "**/api/v1/me",
                lambda route: route.fulfill(
                    json={"member_id": "00000000-0000-0000-0000-000000000076"}
                ),
            )
            page.route(
                "**/api/v1/tasks",
                lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
            )
            page.route(
                "**/api/v1/moderation/cases?*",
                lambda route: route.fulfill(status=403, json={"code": "forbidden"}),
            )
            page.route(
                f"**/api/v1/assignments/{assignment_id}/submission-drafts",
                lambda route: route.fulfill(json={"id": draft_id, "revision": 0, "result": None}),
            )
            page.route(
                f"**/api/v1/submission-drafts/{draft_id}",
                lambda route: route.fulfill(
                    json={
                        "id": draft_id,
                        "revision": 1,
                        "result": route.request.post_data_json["payload"]["result"],
                    }
                ),
            )
            page.route(
                f"**/api/v1/assignments/{assignment_id}",
                lambda route: route.fulfill(json=detail),
            )
            page.route(
                f"**/api/v1/members/{member_id}",
                lambda route: route.fulfill(json=member),
            )

            page.goto(mini_app_url + f"#/work/{assignment_id}?view_state=m03")
            page.locator('[data-screen-id="M03"]').wait_for()
            assert (
                page.locator(".screen").evaluate("node => getComputedStyle(node).paddingTop")
                == "12px"
            )
            page.evaluate(
                "document.documentElement.dataset.telegramFullscreen = 'true'; "
                "document.documentElement.style.setProperty("
                "'--tg-content-safe-area-inset-top', '74px')"
            )
            assert (
                page.locator(".screen").evaluate("node => getComputedStyle(node).paddingTop")
                == "80px"
            )
            assert page.locator("#back").evaluate(
                "node => node.getBoundingClientRect().top "
                "- document.querySelector('.screen').getBoundingClientRect().top"
            ) == pytest.approx(80, abs=0.5)
            assert_top_left(page)
            page.get_by_role("button", name="Отправить результат").click()
            sheet = page.get_by_role("dialog", name="Отправить результат")
            sheet.wait_for()
            assert page.locator(".assignment-action-sheet").bounding_box()["y"] < 100
            sheet.get_by_role("button", name="Закрыть окно").click()
            page.locator('[data-screen-id="M03"]').wait_for()
            assert page.url.endswith(f"#/work/{assignment_id}?view_state=m03")

            page.close()
        browser.close()


def test_task_creation_recovers_preview_and_back_never_restarts(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    draft_id = "00000000-0000-0000-0000-000000000070"
    task_id = "00000000-0000-0000-0000-000000000071"
    state: dict[str, Any] = {"stage": "none", "values": {}}
    actions: list[str] = []
    commands: list[tuple[str, str, dict[str, object]]] = []
    failed_start = False
    rejected_save = False
    failed_publish = False
    saved_count = 0
    timezone_label = f"UTC{chr(0x2212)}03:00"

    def creation(route: Route) -> None:
        nonlocal failed_publish, failed_start, rejected_save, saved_count
        if route.request.method == "GET":
            values = state["values"]
            preview = None
            needs_edit = state["stage"] == "expired"
            if state["stage"] == "preview":
                preview = {
                    "title": values["title"],
                    "description": values["description"],
                    "completion_criteria": values["completion_criteria"],
                    "reward_total": 6,
                }
            route.fulfill(
                json={
                    "categories": [
                        {
                            "id": task_id,
                            "code": "practical_help",
                            "name": "Практическая помощь",
                            "description": "Помочь руками в конкретном действии.",
                            "icon": "⭐",
                        }
                    ],
                    "credit_balance": 7,
                    "time_sizes": [
                        {
                            "value": "s",
                            "label": "15-40 минут",
                            "reward_options": [2, 3, 4],
                            "minimum_reward": 2,
                        },
                        {
                            "value": "xl",
                            "label": "больше 8 часов",
                            "reward_options": [],
                            "minimum_reward": 11,
                        },
                    ],
                    "draft": None
                    if state["stage"] == "none"
                    else {
                        "id": draft_id,
                        "revision": 0 if state["stage"] == "draft" else 1 if needs_edit else 2,
                        "values": values,
                    },
                    "preview": preview,
                    "needs_edit": needs_edit,
                }
            )
            return
        assert route.request.method == "POST"
        body = route.request.post_data_json
        assert body is not None
        actions.append(body["action"])
        operation_key = route.request.headers["idempotency-key"]
        assert operation_key.isdecimal()
        commands.append((body["action"], operation_key, body))
        if body["action"] == "start" and not failed_start:
            failed_start = True
            route.fulfill(status=503, json={"code": "request_failed"})
            return
        if body["action"] == "start":
            state["stage"] = "draft"
        if body["action"] == "save" and not rejected_save:
            rejected_save = True
            route.fulfill(status=422, json={"detail": "raw validation payload"})
            return
        if body["action"] == "save":
            saved_count += 1
            state["values"] = body["form"]
            state["stage"] = "expired" if saved_count == 1 else "preview"
        if body["action"] == "publish":
            if not failed_publish:
                failed_publish = True
                route.fulfill(status=503, json={"code": "request_failed"})
                return
            route.fulfill(json={"task_id": task_id})
        else:
            route.fulfill(status=204)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(
                json={
                    "display_name": "Алекс",
                    "timezone": "America/Argentina/Buenos_Aires",
                }
            ),
        )
        page.route(
            "**/api/v1/tasks", lambda route: route.fulfill(json={"items": [], "next_cursor": None})
        )
        page.route("**/api/v1/task-creation", creation)
        page.route(
            "**/api/v1/task-cities?*",
            lambda route: route.fulfill(
                json={
                    "items": [
                        {
                            "value": "Buenos Aires — Argentina",
                            "label": "Buenos Aires — Argentina",
                            "timezone": "America/Argentina/Buenos_Aires",
                        }
                    ]
                }
            ),
        )
        page.goto(mini_app_url)
        _open_blank_task_creation(page)
        assert actions == []
        assert page.locator('[data-screen-id="T04B"]').count() == 0
        required_labels = (
            "Тип задания *",
            "Число исполнителей *",
            "Формат *",
            "Категория *",
            "Название *",
            "Что нужно сделать *",
            "Критерии приёмки *",
            "Размер *",
            "Награда за исполнителя *",
            "Срок *",
        )
        required_controls = [page.get_by_label(label, exact=True) for label in required_labels]
        assert [control.count() for control in required_controls] == [1] * len(required_labels)
        assert all(control.evaluate("node => node.required") for control in required_controls)
        materials = page.get_by_label("Материалы", exact=True)
        assert materials.evaluate("node => !node.required")
        assert materials.get_attribute("class") == "visually-hidden"
        assert page.locator(".creation-group").count() == 3
        assert page.locator(".creation-group-title").evaluate_all(
            "nodes => nodes.map(node => node.textContent)"
        ) == [
            "Содержание",
            "Условия",
        ]
        group_title = (
            "node => { const group = node.closest('.creation-group'); "
            "return group.getAttribute('aria-label') || "
            "group.querySelector('.creation-group-title').textContent; }"
        )
        assert page.get_by_label("Размер *", exact=True).evaluate(group_title) == "Формат задания"
        assert (
            page.get_by_label("Награда за исполнителя *", exact=True).evaluate(group_title)
            == "Формат задания"
        )
        assert (
            page.get_by_label("Критерии приёмки *", exact=True).evaluate(group_title) == "Условия"
        )
        assert page.get_by_label("Срок *", exact=True).evaluate(group_title) == "Условия"
        assert page.locator(".deadline-choice-field > .field-label").count() == 0
        assert (
            page.get_by_role("button", name="Выбрать срок", exact=True)
            .get_by_text("Выберите срок *", exact=True)
            .is_visible()
        )
        assert materials.evaluate(group_title) == "Содержание"
        assert (
            page.locator(".creation-submit-bar").evaluate("node => getComputedStyle(node).position")
            == "sticky"
        )
        assert page.get_by_role(
            "button", name="Редактировать что нужно сделать", exact=True
        ).evaluate("node => node.getBoundingClientRect().height < 90")
        materials_trigger = page.get_by_role("button", name="Редактировать материалы", exact=True)
        assert materials_trigger.is_visible()
        assert materials_trigger.get_by_text("Материалы (необязательно)", exact=True).is_visible()
        assert page.get_by_text("+ Добавить материалы", exact=True).count() == 0
        materials_trigger.click()
        materials_dialog = page.get_by_role("dialog", name="Материалы", exact=True)
        materials_editor = materials_dialog.get_by_label("Материалы: текст", exact=True)
        materials_editor.fill("https://example.com/source")
        materials_dialog.get_by_role("button", name="Готово", exact=True).click()
        assert materials.input_value() == "https://example.com/source"
        assert materials_trigger.get_by_text("https://example.com/source", exact=True).is_visible()
        materials_trigger.click()
        materials_editor = page.get_by_role("dialog", name="Материалы", exact=True).get_by_label(
            "Материалы: текст", exact=True
        )
        materials_editor.fill("")
        page.get_by_role("dialog", name="Материалы", exact=True).get_by_role(
            "button", name="Готово", exact=True
        ).click()
        assert materials.input_value() == ""
        assert materials.get_attribute("class") == "visually-hidden"
        assert page.get_by_text("Ссылка", exact=True).count() == 0
        assert page.locator('[name="material_url"]').count() == 0
        page.get_by_role("button", name="Предварительный просмотр", exact=True).click()
        assert actions == []
        assert page.get_by_label("Название *", exact=True).evaluate(
            "node => node.matches(':invalid')"
        )
        assert page.locator(".field-error:not(.hidden)").count() >= 1
        page.get_by_role("button", name="Редактировать название", exact=True).click()
        title_dialog = page.get_by_role("dialog", name="Название", exact=True)
        title_dialog.get_by_label("Название: текст", exact=True).fill("Коротко")
        assert title_dialog.get_by_text("7 / 80", exact=True).is_visible()
        title_dialog.get_by_role("button", name="Готово", exact=True).click()
        local_title = "Черновик " + "\u0430" * 60
        page.get_by_role("button", name="Редактировать название", exact=True).click()
        title_dialog = page.get_by_role("dialog", name="Название", exact=True)
        title_dialog.get_by_label("Название: текст", exact=True).fill(local_title)
        assert title_dialog.get_by_text(f"{len(local_title)} / 80", exact=True).is_visible()
        title_dialog.get_by_role("button", name="Готово", exact=True).click()
        page.get_by_text("Сохранено на устройстве", exact=True).wait_for()
        page.goto(mini_app_url)
        _open_blank_task_creation(page)
        assert page.get_by_label("Название *", exact=True).input_value() == local_title
        page.get_by_role("button", name="Редактировать что нужно сделать", exact=True).click()
        description_dialog = page.get_by_role("dialog", name="Что нужно сделать", exact=True)
        description_editor = description_dialog.get_by_label("Что нужно сделать: текст", exact=True)
        description_editor.fill("Строка\n" * 40)
        assert description_editor.evaluate(
            "node => { const style = getComputedStyle(node); "
            "return node.getBoundingClientRect().height <= 260 && style.overflowY === 'auto'; }"
        )
        description_dialog.get_by_role("button", name="Готово", exact=True).click()
        slots = page.get_by_label("Число исполнителей *", exact=True)
        assert slots.input_value() == "1"
        assert slots.is_disabled()
        assert slots.is_hidden()
        assert page.get_by_label("Город").count() == 0
        assert page.locator(".creation-choice-row").evaluate(
            "node => { const [kind, format] = node.querySelectorAll('.creation-choice-trigger'); "
            "const difference = kind.getBoundingClientRect().y - format.getBoundingClientRect().y; "
            "return Math.abs(difference) < 1; }"
        )
        _choose_creation_option(
            page,
            trigger="Выбрать тип задания",
            dialog="Тип задания",
            option="Групповое",
        )
        assert slots.is_enabled()
        assert slots.is_visible()
        assert slots.get_attribute("min") == "2"
        slots.fill("3")
        _choose_creation_option(
            page,
            trigger="Выбрать тип задания",
            dialog="Тип задания",
            option="Личное",
        )
        assert slots.input_value() == "1"
        assert slots.is_disabled()
        assert slots.is_hidden()
        _choose_creation_option(
            page,
            trigger="Выбрать тип задания",
            dialog="Тип задания",
            option="Групповое",
        )
        assert slots.input_value() == "3"
        page.get_by_role("button", name="Выбрать категорию", exact=True).click()
        category_dialog = page.get_by_role("dialog", name="Категория", exact=True)
        assert category_dialog.get_by_text(
            "Помочь руками в конкретном действии.", exact=True
        ).is_visible()
        category_dialog.get_by_role("button", name=re.compile("^Практическая помощь,")).click()
        page.get_by_role("button", name="Выбрать размер задания", exact=True).click()
        size_dialog = page.get_by_role("dialog", name="Размер задания", exact=True)
        assert size_dialog.is_visible()
        size_dialog.get_by_role(
            "button", name="XL, больше 8 часов, награда от 11 кредитов", exact=True
        ).click()
        assert page.get_by_text("Для размера XL доступно от 11 кредитов", exact=True).is_visible()
        assert page.get_by_text("11 кредитов", exact=True).is_visible()
        assert page.get_by_role("button", name="Уменьшить награду").is_disabled()
        page.get_by_role("button", name="Увеличить награду").click()
        assert page.get_by_text("12 кредитов", exact=True).is_visible()
        page.get_by_role("button", name="Выбрать размер задания", exact=True).click()
        page.get_by_role(
            "button", name="S, 15-40 минут, награда 2\u20134 кредита", exact=True
        ).click()
        assert page.get_by_text("Для размера S доступно 2\u20134 кредита", exact=True).is_visible()
        assert page.get_by_role("radio", name="2 кредита", exact=True).count() == 1
        assert page.get_by_role("radio", name="3 кредита", exact=True).count() == 1
        assert page.get_by_role("radio", name="4 кредита", exact=True).count() == 1
        page.get_by_role("radio", name="3 кредита", exact=True).click()
        assert page.get_by_text("3 исполнителя \u00d7 3 кредита", exact=True).is_visible()
        assert page.get_by_text("9 из 7 кредитов", exact=True).is_visible()
        assert page.locator(".reserve-summary.is-over-limit").is_visible()
        _fill_creation_content(
            page,
            trigger="Редактировать название",
            dialog="Название",
            value="<script>globalThis.pwned=true</script>",
        )
        _fill_creation_content(
            page,
            trigger="Редактировать что нужно сделать",
            dialog="Что нужно сделать",
            value="Проверить безопасный предпросмотр.",
        )
        _fill_creation_content(
            page,
            trigger="Редактировать критерии приёмки",
            dialog="Критерии приёмки",
            value="Есть результат.",
        )
        page.get_by_label("Срок *", exact=True).fill("2099-08-21T20:00")
        page.get_by_label("Число исполнителей *", exact=True).fill("2")
        assert page.locator(".reserve-summary.is-over-limit").count() == 0
        assert page.get_by_text("6 из 7 кредитов", exact=True).is_visible()
        _choose_creation_option(
            page,
            trigger="Выбрать формат задания",
            dialog="Формат задания",
            option="Офлайн",
        )
        city = page.get_by_label("Город *", exact=True)
        assert city.evaluate("node => node.required")
        assert city.get_attribute("class") == "visually-hidden"
        page.get_by_role("button", name="Выбрать город", exact=True).click()
        city_dialog = page.get_by_role("dialog", name="Город", exact=True)
        city_dialog.get_by_label("Поиск города", exact=True).fill("Buenos Aires")
        city_option = city_dialog.get_by_role("option", name="Buenos Aires — Argentina")
        assert city_option.locator("small").inner_text() == timezone_label
        city_option.click()
        assert city.input_value() == "Buenos Aires — Argentina"
        assert (
            page.get_by_role("button", name="Выбрать город", exact=True)
            .get_by_text("Buenos Aires — Argentina", exact=True)
            .is_visible()
        )
        assert (
            page.get_by_role("button", name="Выбрать город", exact=True)
            .locator("small")
            .inner_text()
            == timezone_label
        )
        _choose_creation_option(
            page,
            trigger="Выбрать формат задания",
            dialog="Формат задания",
            option="Онлайн",
        )
        assert page.get_by_label("Город *", exact=True).count() == 0
        _choose_creation_option(
            page,
            trigger="Выбрать формат задания",
            dialog="Формат задания",
            option="Офлайн",
        )
        city = page.get_by_label("Город *", exact=True)
        page.get_by_role("button", name="Выбрать город", exact=True).click()
        city_dialog = page.get_by_role("dialog", name="Город", exact=True)
        city_dialog.get_by_label("Поиск города", exact=True).fill("Buenos Aires")
        city_dialog.get_by_role("option", name="Buenos Aires — Argentina").click()
        assert city.input_value() == "Buenos Aires — Argentina"
        page.get_by_role("button", name="Предварительный просмотр", exact=True).click()
        page.get_by_text("Не удалось сохранить задание").wait_for()  # noqa: RUF001
        with page.expect_request(
            lambda request: request.method == "POST" and request.post_data_json["action"] == "save"
        ):
            page.get_by_role("button", name="Предварительный просмотр", exact=True).click()
        page.get_by_text("Не удалось сохранить задание").wait_for()  # noqa: RUF001
        assert actions[:3] == ["start", "start", "save"]
        assert page.get_by_role("button", name="Опубликовать").count() == 0
        assert page.get_by_text("raw validation payload").count() == 0
        page.get_by_role("button", name="Предварительный просмотр", exact=True).click()
        page.get_by_text("Предпросмотр устарел").wait_for()
        assert (
            page.evaluate(
                "Object.keys(localStorage).filter(key => "
                "key.startsWith('community-bot:task-form:')).length"
            )
            == 0
        )
        page.get_by_role("button", name="Редактировать черновик").click()
        page.get_by_role("button", name="Выбрать срок", exact=True).click()
        deadline_dialog = page.get_by_role("dialog", name="Срок", exact=True)
        deadline_dialog.locator('[data-date="2099-08-22"]').click()
        deadline_dialog.get_by_label("Время срока", exact=True).fill("20:00")
        deadline_dialog.get_by_role("button", name="Готово", exact=True).click()
        assert page.get_by_label("Срок *", exact=True).input_value() == "2099-08-22T20:00"
        assert page.locator("#app").evaluate("node => node.scrollTop === 0")
        page.locator(".screen").evaluate("node => node.scrollTo({ top: 0, behavior: 'instant' })")
        assert page.locator(".screen-heading").evaluate(
            "node => node.getBoundingClientRect().top >= "
            "node.parentElement.getBoundingClientRect().top"
        )
        page.get_by_role("button", name="Предварительный просмотр", exact=True).click()
        commands_before = len(commands)
        page.locator('[data-screen-id="T06"]').wait_for()
        preview_form = commands[-1][2]["form"]
        assert isinstance(preview_form, dict)
        assert preview_form["deadline_at"] == "2099-08-22T23:00:00.000Z"
        publish = page.get_by_role("button", name="Опубликовать", exact=True)
        assert publish.evaluate("node => node.parentElement.matches('.preview-task-card')")
        assert page.url.endswith(f"#/compose/tasks/{draft_id}?view_state=t06")
        state["values"]["materials"] = {"url": "https://legacy.example/material"}
        page.reload()
        page.locator('[data-screen-id="T06"]').wait_for()
        assert page.url.endswith(f"#/compose/tasks/{draft_id}?view_state=t06")
        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="T05"]').wait_for()
        assert page.url.endswith(f"#/compose/tasks/{draft_id}?view_state=t05")
        assert page.get_by_label("Материалы", exact=True).input_value() == (
            "https://legacy.example/material"
        )
        page.go_forward()
        page.locator('[data-screen-id="T06"]').wait_for()
        assert page.url.endswith(f"#/compose/tasks/{draft_id}?view_state=t06")
        assert page.get_by_role("button", name="Продолжить").count() == 0
        assert page.locator('[data-screen-id="T07"]').count() == 0
        page.get_by_role("button", name="Опубликовать").click()
        page.get_by_text("Не удалось опубликовать задание").wait_for()  # noqa: RUF001
        page.get_by_role("button", name="Опубликовать").click()
        page.get_by_text("Задание опубликовано").wait_for()
        assert len(commands) == commands_before + 2
        assert page.evaluate("globalThis.pwned") is None
        page.get_by_role("button", name="К заданиям").click()  # noqa: RUF001
        page.get_by_role("button", name="+ Создать", exact=True).wait_for()
        assert actions == ["start", "start", "save", "save", "save", "publish", "publish"]
        assert commands[0][1:] == commands[1][1:]
        assert commands[2][2] == commands[3][2]
        assert commands[2][1] != commands[3][1]
        saved_form = commands[2][2]["form"]
        assert isinstance(saved_form, dict)
        assert set(saved_form) == {
            "category_id",
            "city",
            "completion_criteria",
            "credit_reward_per_performer",
            "deadline_at",
            "description",
            "format",
            "materials",
            "performer_slots",
            "task_kind",
            "time_size",
            "title",
        }
        assert saved_form["materials"] == {}
        assert saved_form["city"] == "Buenos Aires — Argentina"
        assert commands[-2][1:] == commands[-1][1:]
        assert commands[4][2]["expected_revision"] == 1
        repaired_form = commands[4][2]["form"]
        assert isinstance(repaired_form, dict)
        repaired_deadline = repaired_form["deadline_at"]
        assert isinstance(repaired_deadline, str)
        assert "2099-08-22" in repaired_deadline
        assert len({key for _action, key, _body in commands[1:]}) == 5
        browser.close()


@pytest.mark.browser_smoke
def test_task_creation_entry_recovers_or_starts_new_without_dead_screens(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    removed = (
        "Кто будет выполнять?",
        "Основа задания",
        "Шаблоны сервера не подключены",
        "Создать без шаблона",
        "Без шаблона",
        'presentationLocationFor("T04")',
        'presentationLocationFor("T04A")',
    )
    assert {text: source.count(text) for text in removed} == dict.fromkeys(removed, 0)
    old_id = "00000000-0000-0000-0000-000000000072"
    new_id = "00000000-0000-0000-0000-000000000073"
    category_id = "00000000-0000-0000-0000-000000000074"
    current = old_id
    fail_next_get = False
    start_keys: list[str] = []

    def creation(route: Route) -> None:
        nonlocal current, fail_next_get
        if route.request.method == "GET":
            if fail_next_get:
                fail_next_get = False
                route.fulfill(status=503, json={"code": "request_failed"})
                return
            stale = current == old_id
            route.fulfill(
                json={
                    "categories": [
                        {"id": category_id, "name": "Практическая помощь", "icon": "⭐"}
                    ],
                    "time_sizes": [
                        {
                            "value": "s",
                            "label": "15-40 минут",
                            "reward_options": [2, 3, 4],
                            "minimum_reward": 2,
                        }
                    ],
                    "draft": {
                        "id": current,
                        "revision": 7 if stale else 0,
                        "values": {
                            "title": "Сохранённое задание" if stale else None,
                            "deadline_at": "2000-01-01T00:00:00Z" if stale else None,
                        },
                    },
                    "preview": None,
                    "needs_edit": stale,
                }
            )
            return
        body = route.request.post_data_json
        assert body == {"action": "start_new", "draft_id": old_id, "expected_revision": 7}
        start_keys.append(route.request.headers["idempotency-key"])
        if len(start_keys) == 1:
            route.fulfill(status=503, json={"code": "request_failed"})
            return
        current = new_id
        fail_next_get = True
        route.fulfill(status=204)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.route("**/api/v1/me", lambda route: route.fulfill(json={"display_name": "Алекс"}))
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route("**/api/v1/task-home", lambda route: route.fulfill(json=_task_home_payload()))
        page.route("**/api/v1/task-creation", creation)
        page.goto(mini_app_url)
        page.locator('[data-home-action="create"]').click()
        page.get_by_text("Сохранённое задание", exact=True).wait_for()
        assert page.get_by_text("Предпросмотр устарел", exact=False).count() == 1
        assert page.get_by_role("button", name="Редактировать черновик").count() == 1
        assert start_keys == []
        assert page.get_by_text("Кто будет выполнять?").count() == 0
        assert page.get_by_text("Основа задания").count() == 0
        assert page.get_by_text("Шаблоны сервера не подключены", exact=False).count() == 0

        page.get_by_role("button", name="Создать новое").click()
        page.get_by_text("Не удалось создать новый черновик").wait_for()  # noqa: RUF001
        assert page.get_by_role("button", name="Редактировать черновик").is_enabled()
        page.get_by_role("button", name="Создать новое").click()
        page.get_by_text("Новый черновик создан", exact=False).wait_for()
        assert page.get_by_role("button", name="Создать новое").is_disabled()
        assert start_keys[0] == start_keys[1]
        page.get_by_role("button", name="Редактировать черновик").click()
        page.locator('[data-screen-id="T05"]').wait_for()
        assert len(start_keys) == 2
        assert page.get_by_label("Название *", exact=True).input_value() == ""
        assert page.url.endswith(f"#/compose/tasks/{new_id}?view_state=t05")
        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="T04B"]').wait_for()
        assert page.get_by_text("Предпросмотр устарел", exact=False).count() == 0
        browser.close()


def test_deadline_dialog_keeps_done_visible_on_short_desktop(mini_app_url: str) -> None:
    category_id = "00000000-0000-0000-0000-000000000138"

    def creation(route: Route) -> None:
        route.fulfill(
            json={
                "categories": [
                    {
                        "id": category_id,
                        "name": "Практическая помощь",
                        "icon": "⭐",
                    }
                ],
                "credit_balance": 7,
                "time_sizes": [
                    {
                        "value": "s",
                        "label": "15-40 минут",
                        "reward_options": [2, 3, 4],
                        "minimum_reward": 2,
                    }
                ],
                "draft": None,
                "preview": None,
                "needs_edit": False,
            }
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(
            browser,
            bridge="globalThis.Telegram={WebApp:{colorScheme:'light',ready(){},expand(){}}};",
        )
        page.set_viewport_size({"width": 489, "height": 650})
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(json={"display_name": "Алекс"}),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route(
            "**/api/v1/task-home",
            lambda route: route.fulfill(json=_task_home_payload()),
        )
        page.route("**/api/v1/task-creation", creation)
        page.goto(mini_app_url)

        _open_blank_task_creation(page)
        page.get_by_role("button", name="Выбрать срок", exact=True).click()
        dialog = page.get_by_role("dialog", name="Срок", exact=True)
        dialog.locator(".deadline-day:not(:disabled)").first.click()
        done = dialog.get_by_role("button", name="Готово", exact=True)
        content = dialog.locator(".deadline-choice-content")

        assert done.is_visible()
        assert done.is_enabled()
        assert done.evaluate(
            "node => { const dialog = node.closest('[role=dialog]').getBoundingClientRect(); "
            "const button = node.getBoundingClientRect(); "
            "return button.top >= dialog.top && button.bottom <= dialog.bottom; }"
        )
        assert content.evaluate("node => getComputedStyle(node).overflowY === 'auto'")
        assert content.evaluate("node => node.scrollHeight >= node.clientHeight")

        done.click()
        assert page.get_by_label("Срок *", exact=True).input_value()
        browser.close()


def test_expired_task_draft_and_secondary_action_keep_ui_ready_truth(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    draft_id = "00000000-0000-0000-0000-000000000088"
    category_id = "00000000-0000-0000-0000-000000000089"

    def creation(route: Route) -> None:
        if route.request.method == "POST":
            route.fulfill(status=204)
            return
        route.fulfill(
            json={
                "categories": [{"id": category_id, "name": "Практическая помощь", "icon": "⭐"}],
                "time_sizes": [
                    {
                        "value": "s",
                        "label": "15-40 минут",
                        "reward_options": [2, 3, 4],
                        "minimum_reward": 2,
                    }
                ],
                "draft": {
                    "id": draft_id,
                    "revision": 1,
                    "values": {"deadline_at": "2000-01-01T00:00:00Z"},
                },
                "preview": None,
                "needs_edit": False,
            }
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for color_scheme, viewport in (
            ("dark", {"width": 375, "height": 812}),
            ("light", {"width": 375, "height": 812}),
            ("dark", {"width": 430, "height": 932}),
            ("light", {"width": 430, "height": 932}),
        ):
            page = _new_page(
                browser,
                bridge=(
                    "globalThis.Telegram={WebApp:{colorScheme:'"
                    + color_scheme
                    + "',ready(){},expand(){}}};"
                ),
            )
            page.set_viewport_size(viewport)
            page.route(
                "**/api/v1/me",
                lambda route: route.fulfill(json={"display_name": "Алекс"}),
            )
            page.route(
                "**/api/v1/tasks",
                lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
            )
            page.route(
                "**/api/v1/task-home",
                lambda route: route.fulfill(json=_task_home_payload()),
            )
            page.route(
                "**/api/v1/assignments?*",
                lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
            )
            page.route("**/api/v1/task-creation", creation)
            page.goto(mini_app_url)

            _open_blank_task_creation(page)
            deadline = page.get_by_label("Срок *", exact=True)
            preview = page.get_by_role("button", name="Предварительный просмотр", exact=True)
            assert deadline.get_attribute("min") > "2000-01-01T00:00"
            assert deadline.get_attribute("aria-invalid") == "true"
            page.get_by_text("Выберите будущий срок.").wait_for()
            assert preview.is_disabled()

            minimum = deadline.get_attribute("min")
            page.get_by_role("button", name="Выбрать срок", exact=True).click()
            deadline_dialog = page.get_by_role("dialog", name="Срок", exact=True)
            nearest_time = minimum[11:16]
            time_input = deadline_dialog.get_by_label("Время срока", exact=True)
            assert time_input.input_value() == nearest_time
            assert time_input.evaluate("node => node.validity.valid")
            assert deadline_dialog.get_by_text(
                f"Установлено ближайшее допустимое время — {nearest_time}.",
                exact=True,
            ).is_visible()
            assert not deadline_dialog.get_by_role(
                "button", name="Готово", exact=True
            ).is_disabled()
            deadline_dialog.get_by_role("button", name="Закрыть выбор срока", exact=True).click()

            deadline.fill("2099-01-01T09:59")
            assert deadline.get_attribute("aria-invalid") == "false"
            assert page.get_by_text("Выберите будущий срок.").is_hidden()
            assert not preview.is_disabled()
            page.get_by_role("button", name="Выбрать срок", exact=True).click()
            deadline_dialog = page.get_by_role("dialog", name="Срок", exact=True)
            future_time = deadline_dialog.get_by_label("Время срока", exact=True)
            assert future_time.input_value() == "09:59"
            assert future_time.evaluate("node => node.validity.valid")
            deadline_dialog.get_by_role("button", name="Закрыть выбор срока", exact=True).click()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            input_styles = deadline.evaluate(
                "node => { const style = getComputedStyle(node); return {"
                "color: style.color, background: style.backgroundColor, "
                "fontSize: parseFloat(style.fontSize)}; }"
            )
            assert input_styles["color"] == "rgb(246, 248, 252)"
            assert input_styles["background"] != "rgb(0, 0, 0)"
            assert input_styles["fontSize"] >= 16

            assert page.locator("#primary-navigation").is_hidden()
            page.get_by_role("button", name="Назад").click()
            page.locator('[data-screen-id="T04B"]').wait_for()
            page.get_by_role("button", name="Назад").click()
            page.get_by_role("heading", name="Задания").wait_for()
            page.get_by_role("button", name="Мои задания").click()
            secondary = page.get_by_role("button", name="Созданные мной")
            styles = secondary.evaluate(
                """node => {
                  const style = getComputedStyle(node);
                  return {className: node.className, height: node.getBoundingClientRect().height,
                    radius: style.borderRadius, color: style.color, cursor: style.cursor};
                }"""
            )
            assert styles == {
                "className": "back",
                "height": styles["height"],
                "radius": "10px",
                "color": "rgb(169, 177, 196)",
                "cursor": "pointer",
            }
            assert styles["height"] >= 44
            for _ in range(8):
                page.keyboard.press("Tab")
                if secondary.evaluate("node => node === document.activeElement"):
                    break
            assert secondary.evaluate("node => node === document.activeElement")
            assert secondary.evaluate("node => getComputedStyle(node).outlineWidth") == "3px"
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            assert all(
                width >= 44 and height >= 44
                for width, height in page.locator("button:visible").evaluate_all(
                    "buttons => buttons.map(button => {"
                    "const box = button.getBoundingClientRect(); return [box.width, box.height];})"
                )
            )
            page.close()
        browser.close()
