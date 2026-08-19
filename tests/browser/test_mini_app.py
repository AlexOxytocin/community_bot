from __future__ import annotations

import functools
import http.server
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Route

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


def test_assignment_action_eligibility_is_server_projected() -> None:
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'assignment.assignment_status === "accepted"' not in source
    assert "if (assignment.can_submit)" in source
    assert "if (assignment.can_cancel)" in source


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
        page.route("**/api/v1/assignments/*", detail_route)

        page.goto(mini_app_url)
        page.get_by_role("button", name="Восстановить экран").click()
        page.reload()
        page.get_by_role("heading", name="Восстановить экран").wait_for()
        assert len(task_fetches) == 2
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Каталог").wait_for()

        page.get_by_role("button", name="Мои задания").click()
        page.reload()
        page.get_by_role("heading", name="Взятые мной").wait_for()
        page.get_by_role("button", name="Каталог").click()
        page.goto(mini_app_url + "?case=detail#assignment/" + assignment_id)
        page.get_by_text("SERVER-PROJECTION").wait_for()
        assert detail_fetches == [assignment_id]
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Каталог").wait_for()

        page.goto(mini_app_url + "?case=forbidden#assignment/" + forbidden_id)
        page.get_by_text("Назначения недоступны для этого аккаунта.").wait_for()
        assert "PRIVATE-DENIAL" not in page.locator("body").inner_text()
        page.goto(mini_app_url + "?case=malformed#assignment/..%2Fmembers%2FPRIVATE-ID")
        page.get_by_text("Назначение больше не входит в активные.").wait_for()
        assert detail_fetches == [assignment_id, forbidden_id, "..%2Fmembers%2FPRIVATE-ID"]
        assert page.evaluate("document.documentElement.scrollWidth") <= 375
        browser.close()


def test_fresh_telegram_session_handshake_is_exact_and_fail_closed(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    init_data = "query_id=AAE&user=%7B%22id%22%3A1%7D&hash=proof"
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
        page.goto(mini_app_url)
        page.get_by_text("Алекс, выберите понятное задание").wait_for()
        assert me_calls == 2
        assert len(requests) == 1
        assert requests[0].post_data == init_data
        assert requests[0].headers["content-type"] == "text/plain; charset=utf-8"
        assert requests[0].headers["origin"] == mini_app_url.rstrip("/")
        assert requests[0].url == mini_app_url + "api/v1/auth/telegram"
        assert page.evaluate("[localStorage.length, sessionStorage.length]") == [0, 0]
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
        existing.get_by_text("Сессия, выберите понятное задание").wait_for()
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
        invalid.get_by_text("Откройте Mini App ещё раз.").wait_for()
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
        outside.get_by_text("Откройте Mini App ещё раз.").wait_for()
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
            globalThis.Telegram = {WebApp: {
              colorScheme: "light",
              themeParams: {
                bg_color: "#f6f8fc", secondary_bg_color: "#ffffff",
                text_color: "#171b26", hint_color: "#687187",
                button_color: "#08766f", button_text_color: "#ffffff"
              },
              ready() { globalThis.readyCalls = (globalThis.readyCalls || 0) + 1; }, expand() {}
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
                "background": "rgb(23, 27, 38)",
                "color": "rgb(246, 248, 252)",
                "caret": "rgb(46, 230, 214)",
                "height": styles["height"],
            }
            assert styles["height"] >= 44

        controls.first.focus()
        assert controls.first.evaluate("node => getComputedStyle(node).outlineColor") == (
            "rgb(196, 181, 253)"
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
        assert (
            controls.nth(2).evaluate("node => getComputedStyle(node, '::placeholder').color")
            == "rgb(169, 177, 196)"
        )
        assert page.locator("option").evaluate("node => getComputedStyle(node).color") == (
            "rgb(246, 248, 252)"
        )
        controls.nth(1).evaluate("node => { node.disabled = true; }")
        assert controls.nth(1).evaluate("node => getComputedStyle(node).backgroundColor") == (
            "rgb(12, 15, 23)"
        )
        assert page.evaluate("getComputedStyle(document.documentElement).colorScheme") == "dark"
        assert page.evaluate("getComputedStyle(document.body).backgroundImage") != "none"
        assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(5, 6, 10)"
        assert page.evaluate("globalThis.readyCalls") == 1
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

        page.goto(mini_app_url)
        page.get_by_role("button", name=malicious).click()
        detail = page.locator("article.detail")
        assert detail.get_by_text("Мария", exact=True).count() == 1
        assert detail.get_by_text("Практическая помощь", exact=True).count() == 1
        assert detail.get_by_text("Групповое", exact=True).count() == 1
        assert detail.get_by_text("3 кредитов", exact=True).count() == 1
        assert detail.get_by_text("4", exact=True).count() == 1
        assert detail.get_by_text("Офлайн", exact=True).count() == 1
        assert detail.get_by_text("Буэнос-Айрес", exact=True).count() == 1
        assert (
            detail.get_by_role("heading", name="Срок")
            .locator("..")
            .locator("time")
            .get_attribute("datetime")
            == deadline
        )
        assert detail.get_by_role("heading", name="Автор").evaluate(
            "node => Boolean(node.compareDocumentPosition("
            "document.querySelector('button.primary')) & Node.DOCUMENT_POSITION_FOLLOWING)"
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
        assert page.locator("img, a, [onerror], [onclick], [href^='javascript:']").count() == 0
        assert page.locator("script").count() == 2
        assert page.evaluate("globalThis.pwned") is None
        assert (
            page.evaluate(
                "getComputedStyle(document.documentElement)"
                ".getPropertyValue('--app-background').trim()"
            )
            == "#05060a"
        )

        page.get_by_role("button", name="Принять задание").click()
        page.get_by_text("Задание сейчас недоступно.").wait_for()
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("button", name=other_assignment_title).click()
        other_detail = page.locator("article.detail")
        assert other_detail.get_by_text("Сообщество", exact=True).count() == 1
        assert other_detail.get_by_text("Онлайн", exact=True).count() == 1
        assert other_detail.get_by_role("heading", name="Категория").count() == 0
        assert other_detail.get_by_role("heading", name="Тип").count() == 0
        assert other_detail.get_by_role("heading", name="Город").count() == 0
        assert "undefined" not in other_detail.inner_text()
        assert "null" not in other_detail.inner_text()
        page.get_by_role("button", name="Принять задание").click()
        page.get_by_role("heading", name=other_assignment_title).wait_for()
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("button", name=malicious).click()
        page.get_by_role("button", name="Принять задание").click()
        page.get_by_role("heading", name=assignment_title).wait_for()
        assert accepted_tasks == [task_id, other_task_id, task_id]
        assert accept_keys[0] == accept_keys[2]
        assert accept_keys[1] != accept_keys[0]
        assert page.get_by_role("button", name="Принять задание").count() == 0
        assert not any(url.startswith("javascript:") for url in requests)

        page.get_by_role("button", name="Назад").click()
        catalog_trigger = page.get_by_role("button", name=malicious)
        catalog_trigger.wait_for()
        assert catalog_trigger.evaluate("node => node === document.activeElement")

        page.get_by_role("button", name="Мои задания").click()
        page.get_by_role("heading", name="Взятые мной").wait_for()
        page.get_by_role("button", name=re.compile(assignment_title)).click()
        page.get_by_text("План отправлен").wait_for()
        assert page.get_by_role("button", name="Принять задание").count() == 0
        page.get_by_role("button", name="Назад").click()
        assignment_trigger = page.get_by_role("button", name=re.compile(assignment_title))
        assignment_trigger.wait_for()
        assert assignment_trigger.evaluate("node => node === document.activeElement")

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
            == "#05060a"
        )
        browser.close()


def test_moderation_queue_detail_confirm_retry_conflict_and_back_focus(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    malicious = "<img src=x onerror=alert(1)><script>bad()</script>"
    mode: dict[str, Any] = {"name": "pending"}
    pending: list[Route] = []
    requests: list[tuple[str, str]] = []
    resolution_keys: list[str] = []
    resolution_mode = {"name": "retry"}

    def moderation_route(route: Route) -> None:
        requests.append((route.request.method, route.request.url))
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

    def resolution_route(route: Route) -> None:
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
        page.route(
            "**/api/v1/me",
            lambda route: route.fulfill(json={"display_name": "Алекс"}),
        )
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route("**/api/v1/moderation/cases?*", moderation_route)
        page.route("**/api/v1/moderation/cases/*/resolution", resolution_route)
        page.route("**/api/v1/moderation/cases/*", detail_route)

        page.goto(mini_app_url + "#moderation")
        moderation_nav = page.get_by_role("button", name="Модерация")
        page.get_by_text("Загружаем открытые кейсы…").wait_for()
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
        page.get_by_text("Спор по заданию").wait_for()
        assert "PRIVATE_REASON" not in page.locator("body").inner_text()
        assert "PRIVATE_EVIDENCE" not in page.locator("body").inner_text()
        assert page.locator("img, [onerror], [onclick]").count() == 0
        assert page.locator("script").count() == 2

        page.get_by_role("button", name="Спор по заданию").click()
        page.get_by_role("heading", name="Решение по спору").wait_for()
        page.get_by_role("combobox", name="Решение").wait_for()
        assert malicious in page.locator("body").inner_text()
        assert page.locator("img, [onerror], [onclick]").count() == 0
        resolution = page.get_by_role("combobox", name="Решение")
        assert resolution.evaluate("node => node === document.activeElement")
        resolution.select_option("partial_payment")
        reason = page.get_by_role("textbox", name="Причина решения")
        reason.fill("Подтверждена половина результата")
        reason.press("Tab")
        review = page.get_by_role("button", name="Проверить решение")
        assert review.evaluate("node => node === document.activeElement")
        review.press("Enter")
        confirm = page.get_by_role("button", name="Подтвердить решение")
        assert confirm.evaluate("node => node === document.activeElement")
        assert resolution_keys == []
        confirm.click()
        page.get_by_text("Не удалось применить решение.").wait_for()  # noqa: RUF001
        confirm.click()
        page.get_by_text("Открытых кейсов нет.").wait_for()
        assert len(resolution_keys) == 2
        assert resolution_keys[0] == resolution_keys[1]

        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Каталог").wait_for()
        assert moderation_nav.evaluate("node => node === document.activeElement")

        mode["name"] = "pending"
        resolution_mode["name"] = "conflict"
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
        page.get_by_role("button", name="Спор по заданию").click()
        page.get_by_role("combobox", name="Решение").select_option("partial_payment")
        page.get_by_role("textbox", name="Причина решения").fill("Подтверждена половина результата")
        page.get_by_role("button", name="Проверить решение").click()
        page.get_by_role("button", name="Подтвердить решение").click()
        page.get_by_text("Кейс уже изменился").wait_for()
        page.get_by_role("button", name="Назад").click()
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
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Каталог").wait_for()

        mode["name"] = "empty"
        moderation_nav.click()
        page.get_by_text("Открытых кейсов нет.").wait_for()
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Каталог").wait_for()

        mode["name"] = "closed"
        moderation_nav.click()
        page.get_by_text("Очередь модерации недоступна для этого аккаунта.").wait_for()
        assert "Moderator" not in page.locator("body").inner_text()
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Каталог").wait_for()

        mode["name"] = "unauthorized"
        moderation_nav.click()
        page.get_by_text("Сессия истекла. Закройте и снова откройте Mini App.").wait_for()
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Каталог").wait_for()

        mode["name"] = "network"
        moderation_nav.click()
        page.get_by_text("Не удалось загрузить очередь модерации.").wait_for()  # noqa: RUF001
        assert page.get_by_role("button", name="Повторить").count() == 1
        assert requests
        assert all(method == "GET" for method, _url in requests)
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
        "private_top_level": private_marker,
    }
    member = {
        "member_id": member_id,
        "telegram_username": private_marker,
        "display_name": malicious,
        "karma": {"score": 3, "count": 4, "comment": private_marker},
        "reliability": {
            "accepted": 4,
            "approved_weight": "3.5",
            "no_show": 1,
            "rate": None,
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
                "experience": 12,
                "unique_recipients": 3,
                "reliability": None,
                "no_show": 1,
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
        page.set_viewport_size({"width": 375, "height": 800})
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
        page.route("**/api/v1/leaderboard?*", leaderboard_route)
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.goto(mini_app_url)
        page.get_by_text("выберите понятное задание").wait_for()

        capture_requests = True
        profile_nav = page.get_by_role("button", name="Профиль")
        profile_nav.click()
        page.get_by_text("Загружаем профиль…").wait_for()
        page.get_by_text("Загружаем таблицу вклада…").wait_for()
        page.wait_for_timeout(50)
        assert len(pending) == 2
        member_pending = next(route for route in pending if "/members/" in route.request.url)
        member_pending.fulfill(json=member)
        pending.remove(member_pending)

        page.locator("h3", has_text=malicious).wait_for()
        for value in (
            "Буэнос-Айрес",
            "America/Argentina/Buenos_Aires",
            "Помогаю собирать ясные планы.",
            "Найти партнёров для пилота.",
            "Стратегия, Текст",
            "Фасилитация, Редактура",
            "По вечерам",
            "7",
            "12",
            "2 · Участник",
            "3 · оценок: 4",
            "3.5",
            "Недостаточно данных",
        ):
            assert page.get_by_text(value, exact=True).count() >= 1
        body = page.locator("body").inner_text()
        assert malicious in body
        assert private_marker not in body
        assert page.locator("img, [onerror], [onclick]").count() == 0
        assert page.locator("script").count() == 2
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

        page.get_by_label("Поле профиля").select_option("city")
        page.get_by_label("Новое значение").fill("Rosario")
        page.get_by_role("button", name="Сохранить поле").click()
        page.get_by_text(
            "Не удалось сохранить. Повторите попытку — запрос останется тем же."  # noqa: RUF001
        ).wait_for()
        leaderboard_pending = next(
            route for route in pending if "/leaderboard" in route.request.url
        )
        leaderboard_pending.fulfill(json=leaderboard)
        pending.remove(leaderboard_pending)
        page.get_by_text("Получатели помощи: 3").wait_for()
        page.get_by_text("Неявки: 1").wait_for()
        assert page.get_by_label("Новое значение").input_value() == "Rosario"
        page.get_by_role("button", name="Сохранить поле").click()
        page.get_by_text(
            "Не удалось сохранить. Повторите попытку — запрос останется тем же."  # noqa: RUF001
        ).wait_for()
        modes["member"] = "error"
        page.get_by_role("button", name="Сохранить поле").click()
        page.get_by_text("Rosario", exact=True).wait_for()
        page.wait_for_timeout(50)
        assert profile_update_keys[0] == profile_update_keys[1] == profile_update_keys[2]
        assert page.get_by_text("Не удалось сохранить.", exact=False).count() == 0  # noqa: RUF001

        modes["member"] = "success"
        page.get_by_label("Поле профиля").select_option("city")
        page.get_by_label("Новое значение").fill("x")
        page.get_by_role("button", name="Сохранить поле").click()
        page.get_by_text("Проверьте значение поля.").wait_for()
        assert profile_update_keys[3] != profile_update_keys[2]

        modes.update(member="success", leaderboard="success")
        me.update(help_categories=[], skill_tags=[])
        profile_nav.click()
        page.locator("h3", has_text=malicious).wait_for()
        assert page.get_by_role("heading", name="Категории помощи").count() == 0
        assert page.get_by_role("heading", name="Навыки").count() == 0

        modes.update(member="error", leaderboard="success")
        profile_nav.click()
        page.get_by_text("Не удалось загрузить профиль.").wait_for()  # noqa: RUF001
        assert page.get_by_text("Таблица вклада").count() == 1
        modes["member"] = "success"
        page.get_by_role("button", name="Повторить профиль").click()
        page.locator("h3", has_text=malicious).wait_for()

        modes.update(member="success", leaderboard="error")
        profile_nav.click()
        page.get_by_text("Не удалось загрузить таблицу вклада.").wait_for()  # noqa: RUF001
        modes["leaderboard"] = "success"
        page.get_by_role("button", name="Повторить таблицу").click()
        page.get_by_text("Получатели помощи: 3").wait_for()

        modes["leaderboard"] = "empty"
        profile_nav.click()
        page.get_by_text("Таблица вклада пока пуста.").wait_for()

        page.get_by_role("button", name="Каталог").click()
        page.get_by_role("heading", name="Каталог").wait_for()
        modes.update(member="pending", leaderboard="pending")
        profile_nav.click()
        page.get_by_text("Загружаем профиль…").wait_for()
        page.wait_for_timeout(50)
        assert len(pending) == 2
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Каталог").wait_for()
        for route in pending[:]:
            route.fulfill(json=member if "/members/" in route.request.url else leaderboard)
            pending.remove(route)
        page.wait_for_timeout(50)
        assert page.get_by_role("heading", name="Профиль").count() == 0
        assert profile_nav.evaluate("node => node === document.activeElement")
        assert requests
        assert {
            ("PUT", "/api/v1/me/profile"),
            ("GET", "/api/v1/me"),
            ("GET", f"/api/v1/members/{member_id}"),
            ("GET", "/api/v1/leaderboard"),
        } == set(requests)
        assert {
            "/api/v1/me",
            f"/api/v1/members/{member_id}",
            "/api/v1/leaderboard",
            "/api/v1/me/profile",
        } == {path for _method, path in requests}
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
            "**/api/v1/leaderboard?*",
            lambda route: route.fulfill(
                json={
                    "items": [
                        {
                            "rank": 1,
                            "member_id": target_id,
                            "display_name": "Мария",
                            "experience": 10,
                            "unique_recipients": 2,
                            "reliability": "1.0",
                            "no_show": 0,
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
        page.get_by_role("button", name="Профиль").click()
        page.get_by_role("button", name=re.compile("1\\. Мария")).click()
        page.get_by_role("heading", name="Оценить взаимодействие").wait_for()
        page.get_by_label(re.compile("^Комментарий")).fill(private_comment)
        page.get_by_role("button", name="Подтвердить оценку").click()
        page.get_by_text("Оценка недоступна", exact=False).wait_for()
        page.get_by_role("button", name="Подтвердить оценку").click()
        page.get_by_text("3 · оценок: 3", exact=True).wait_for()

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
        dispute_keys.append(route.request.headers["idempotency-key"])
        assert route.request.post_data_json == {"comment": "Нужна независимая проверка"}
        detail.update(assignment_status="disputed", case_status="open", can_dispute=False)
        route.fulfill(status=204)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.route("**/api/v1/me", lambda route: route.fulfill(json={"display_name": "Алекс"}))
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.route("**/api/v1/assignments?*", assignments_route)
        page.route(f"**/api/v1/assignments/{assignment_id}", detail_route)
        page.route(f"**/api/v1/assignments/{assignment_id}/disputes", dispute_route)
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(mini_app_url)

        page.get_by_role("button", name="Мои задания").click()
        page.get_by_text("Активных назначений пока нет.").wait_for()

        list_mode["status"] = 503
        page.get_by_role("button", name="Мои задания").click()
        page.get_by_text(
            "Не удалось загрузить активные назначения."  # noqa: RUF001
        ).wait_for()
        assert page.get_by_role("button", name="Повторить").count() == 1

        list_mode["status"] = 401
        page.get_by_role("button", name="Мои задания").click()
        page.get_by_text("Сессия истекла. Закройте и снова откройте Mini App.").wait_for()
        assert page.get_by_role("button", name="Повторить").count() == 0

        list_mode["status"] = 403
        page.get_by_role("button", name="Мои задания").click()
        page.get_by_text("Назначения недоступны для этого аккаунта.").wait_for()
        assert page.get_by_role("button", name="Повторить").count() == 0

        list_mode.update(status=200, items=[assignment])
        page.get_by_role("button", name="Мои задания").click()
        row = page.get_by_role("button", name=re.compile("Собрать план"))
        row.wait_for()
        assert page.get_by_role("list").count() == 1
        assert page.get_by_role("listitem").count() == 1
        assert row.get_by_text("План отправлен").count() == 1
        assert row.locator("time[datetime='2026-08-21T20:00:00Z']").count() == 1

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
        page.get_by_role("heading", name="Взятые мной").wait_for()
        pending_routes.pop().fulfill(status=200, json=detail)
        page.wait_for_timeout(50)
        assert page.get_by_text("Собрать понятный план").count() == 0
        assert page.get_by_role("button", name=re.compile("Собрать план")).count() == 1
        assert page.get_by_role("button", name="Назад").count() == 0

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
        page.get_by_label("Почему результат нужно пересмотреть").fill("Нужна независимая проверка")
        page.get_by_role("button", name="Подать спор").click()
        page.get_by_text("Передан команде модерации").wait_for()
        assert len(dispute_keys) == 1

        page.get_by_role("button", name="Назад").click()
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
        operation_keys.append(route.request.headers["idempotency-key"])
        assert route.request.post_data_json == {"reason": "Cannot finish before deadline"}
        items.clear()
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
        page.goto(mini_app_url)

        page.get_by_role("button", name="Мои задания").click()
        page.get_by_role("button", name=re.compile("Проверить форму")).click()
        page.get_by_label("Причина отказа").fill(" Cannot finish before deadline ")
        page.get_by_role("button", name="Подтвердить отказ").click()
        page.get_by_text("Активных назначений пока нет.").wait_for()
        assert len(operation_keys) == 1
        assert page.url.endswith("/#assignments")
        assert page.evaluate("history.state") == {"screen": "assignments"}
        browser.close()


def test_freeform_submission_uses_preview_confirm_and_detail_refresh(  # noqa: C901, PLR0915
    mini_app_url: str,
) -> None:
    assignment_id, draft_id, assignment, submitted = _freeform_submission_rows()
    detail = submitted | {"assignment_status": "accepted", "result_summary": None}
    current_detail: dict[str, Any] = {"value": detail}
    begin_keys: list[str] = []
    confirm_keys: list[str] = []
    review_keys: list[str] = []
    review_pending = {"value": True}
    pending_confirm: list[Route] = []
    review = {
        "id": assignment_id,
        "task_title": "Проверить форму",
        "performer_display_name": "Участник",
        "review_deadline_at": "2026-08-20T20:30:00Z",
        "result": "<script>globalThis.pwned=true</script>",
        "available_decisions": ["full", "partial", "reject"],
    }

    def confirm_rejection(dialog) -> None:  # noqa: ANN001
        expected = "Отклонить результат? Выплата и резерв останутся заморожены на 24 часа для возможного спора. Повторная отправка результата не откроется."  # noqa: E501
        assert dialog.message == expected
        dialog.accept()

    def save(route: Route) -> None:
        request = route.request
        assert request.headers["idempotency-key"].isdecimal()
        body = request.post_data_json
        assert isinstance(body, dict)
        assert body["expected_revision"] == 0
        assert body["payload"]["result"] == "<script>globalThis.pwned=true</script>"
        route.fulfill(json={"id": draft_id, "revision": 1, "result": body["payload"]["result"]})

    def begin(route: Route) -> None:
        begin_keys.append(route.request.headers["idempotency-key"])
        if len(begin_keys) == 1:
            route.abort()
        else:
            route.fulfill(json={"id": draft_id, "revision": 0, "result": None})

    def confirm(route: Route) -> None:
        confirm_keys.append(route.request.headers["idempotency-key"])
        assert route.request.post_data_json == {"expected_revision": 1}
        if len(confirm_keys) == 1:
            route.fulfill(status=502, body="upstream unavailable", content_type="text/plain")
            return
        current_detail["value"] = submitted
        pending_confirm.append(route)

    def decide(route: Route) -> None:
        review_keys.append(route.request.headers["idempotency-key"])
        assert route.request.post_data_json == {"decision": "reject"}
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
            lambda route: route.fulfill(
                json={
                    "items": [
                        {
                            "id": assignment["task_id"],
                            "title": review["task_title"],
                            "status": "published",
                            "performer_slots": 2,
                            "deadline_at": "2026-08-21T20:00:00Z",
                            "assignees": [{"display_name": "Исполнитель", "status": "submitted"}],
                            "cancellation_status": None,
                        }
                    ]
                }
            ),
        )
        page.route(
            f"**/api/v1/assignment-reviews/{assignment_id}",
            lambda route: route.fulfill(json=review),
        )
        page.route(f"**/api/v1/assignment-reviews/{assignment_id}/decision", decide)
        page.goto(mini_app_url)
        page.get_by_role("button", name="Мои задания").click()
        page.get_by_role("button", name=re.compile("Проверить форму")).click()
        page.get_by_role("button", name="Начать отправку").click()
        page.get_by_text("Сеть недоступна. Повторите запрос — он останется тем же.").wait_for()
        assert not page.get_by_role("button", name="Начать отправку").is_disabled()
        page.get_by_role("button", name="Начать отправку").click()
        result = page.get_by_role("textbox", name="Результат")
        assert result.evaluate("node => node === document.activeElement")
        assert begin_keys[0] == begin_keys[1]
        result.fill("<script>globalThis.pwned=true</script>")
        page.get_by_role("button", name="Предпросмотр").click()
        page.get_by_text("Подтвердите отправку.").wait_for()
        assert page.evaluate("globalThis.pwned") is None
        page.get_by_role("button", name="Подтвердить отправку").click()
        page.get_by_text("Не удалось сохранить результат.").wait_for()  # noqa: RUF001
        page.get_by_role("button", name="Подтвердить отправку").click()
        assert confirm_keys[0] == confirm_keys[1]
        assert len(pending_confirm) == 1
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Взятые мной").wait_for()
        pending_confirm.pop().fulfill(status=204)
        page.wait_for_timeout(50)
        assert page.get_by_role("heading", name="Взятые мной").count() == 1
        page.get_by_role("button", name=re.compile("Проверить форму")).click()
        page.get_by_text("Результат отправлен").first.wait_for()
        assert page.get_by_role("button", name="Начать отправку").count() == 1
        page.get_by_role("button", name="Мои задания").click()
        page.get_by_role("button", name="Созданные мной").click()
        page.get_by_role("heading", name="Мои опубликованные задания").wait_for()
        page.get_by_text("Исполнители: 1/2").wait_for()
        page.get_by_text("Исполнитель · Результат отправлен").wait_for()
        review_button = page.get_by_role("button", name=re.compile("Проверить форму"))
        review_button.click()
        assert page.evaluate("globalThis.pwned") is None
        page.get_by_role("button", name="Назад").click()
        assert review_button.evaluate("node => node === document.activeElement")
        review_button.click()
        for _attempt in range(2):
            page.once("dialog", confirm_rejection)
            page.get_by_role("button", name="Отклонить").click()
            if len(review_keys) == 1:
                page.get_by_text("ключ останется тем же").wait_for()
        assert review_keys[0] == review_keys[1]
        page.get_by_text("Результатов, ожидающих решения, пока нет.").wait_for()
        browser.close()


def test_task_creation_recovers_preview_and_back_never_restarts(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    draft_id = "00000000-0000-0000-0000-000000000070"
    task_id = "00000000-0000-0000-0000-000000000071"
    state: dict[str, Any] = {"stage": "draft", "values": {}}
    actions: list[str] = []
    commands: list[tuple[str, str, dict[str, object]]] = []
    failed_start = False
    rejected_save = False
    saved_count = 0

    def creation(route: Route) -> None:
        nonlocal failed_start, rejected_save, saved_count
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
                    "categories": [{"id": task_id, "name": "Практическая помощь", "icon": "⭐"}],
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
                        "revision": 0 if state["stage"] == "draft" else 1 if needs_edit else 2,
                        "values": values,
                    },
                    "preview": preview,
                    "needs_edit": needs_edit,
                }
            )
            return
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
        if body["action"] == "save" and not rejected_save:
            rejected_save = True
            route.fulfill(status=422, json={"detail": "raw validation payload"})
            return
        if body["action"] == "save":
            saved_count += 1
            state["values"] = body["form"]
            state["stage"] = "expired" if saved_count == 1 else "preview"
        if body["action"] == "publish":
            route.fulfill(json={"task_id": task_id})
        else:
            route.fulfill(status=204)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        page.route("**/api/v1/me", lambda route: route.fulfill(json={"display_name": "Алекс"}))
        page.route(
            "**/api/v1/tasks", lambda route: route.fulfill(json={"items": [], "next_cursor": None})
        )
        page.route("**/api/v1/task-creation", creation)
        page.goto(mini_app_url)
        page.get_by_role("button", name="Создать задание").click()
        page.get_by_text("Не удалось открыть создание задания.").wait_for()  # noqa: RUF001
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("button", name="Создать задание").click()
        page.get_by_label("Тип").select_option("group")
        page.get_by_label("Категория").select_option(task_id)
        page.get_by_label("Размер").select_option("s")
        page.get_by_label("Награда").fill("3")
        page.get_by_label("Название").fill("<script>globalThis.pwned=true</script>")
        page.get_by_label("Описание").fill("Проверить безопасный предпросмотр.")
        page.get_by_label("Критерии выполнения").fill("Есть результат.")
        page.get_by_label("Срок").fill("2026-08-21T20:00")
        page.get_by_label("Число исполнителей").fill("2")
        page.get_by_label("Материалы").fill("Описание материала")
        page.get_by_role("button", name="Предпросмотр").click()
        page.get_by_text("Не удалось сохранить задание").wait_for()  # noqa: RUF001
        assert page.get_by_role("button", name="Опубликовать").count() == 0
        assert page.get_by_text("raw validation payload").count() == 0
        page.get_by_role("button", name="Предпросмотр").click()
        page.get_by_text("Предпросмотр устарел").wait_for()
        page.get_by_role("button", name="Предпросмотр").click()
        page.get_by_role("button", name="Опубликовать").click()
        page.get_by_text("Задание опубликовано").wait_for()
        assert page.evaluate("globalThis.pwned") is None
        page.go_back()
        page.get_by_role("button", name="Создать задание").wait_for()
        assert actions == ["start", "start", "save", "save", "save", "publish"]
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
        assert saved_form["materials"] == {"text": "Описание материала"}
        assert len({key for _action, key, _body in commands[1:]}) == 5
        browser.close()


def test_expired_task_draft_and_secondary_action_keep_ui_ready_truth(
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
        for color_scheme in ("dark", "light"):
            page = _new_page(
                browser,
                bridge=(
                    "globalThis.Telegram={WebApp:{colorScheme:'"
                    + color_scheme
                    + "',ready(){},expand(){}}};"
                ),
            )
            page.set_viewport_size({"width": 375, "height": 812})
            page.route(
                "**/api/v1/me",
                lambda route: route.fulfill(json={"display_name": "Алекс"}),
            )
            page.route(
                "**/api/v1/tasks",
                lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
            )
            page.route(
                "**/api/v1/assignments?*",
                lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
            )
            page.route("**/api/v1/task-creation", creation)
            page.goto(mini_app_url)

            page.get_by_role("button", name="Создать задание").click()
            deadline = page.get_by_label("Срок")
            preview = page.get_by_role("button", name="Предпросмотр")
            assert deadline.get_attribute("min") > "2000-01-01T00:00"
            assert deadline.get_attribute("aria-invalid") == "true"
            page.get_by_text("Выберите будущий срок.").wait_for()
            assert preview.is_disabled()

            deadline.fill("2099-01-01T00:00")
            assert deadline.get_attribute("aria-invalid") == "false"
            assert page.get_by_text("Выберите будущий срок.").is_hidden()
            assert not preview.is_disabled()
            assert page.evaluate("document.documentElement.scrollWidth") <= 375

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
                "radius": "12px",
                "color": "rgb(246, 248, 252)",
                "cursor": "pointer",
            }
            assert styles["height"] >= 44
            page.keyboard.press("Tab")
            page.keyboard.press("Tab")
            assert secondary.evaluate("node => node === document.activeElement")
            assert secondary.evaluate("node => getComputedStyle(node).outlineWidth") == "3px"
            assert page.evaluate("document.documentElement.scrollWidth") <= 375
            page.close()
        browser.close()
