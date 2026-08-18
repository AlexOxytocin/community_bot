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


def test_catalog_detail_accept_is_literal_and_confirmed(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    malicious = "<img src=x onerror=alert(1)><script>bad()</script>"
    javascript_url = "javascript:globalThis.pwned=true"
    task_id = "00000000-0000-0000-0000-000000000053"
    assignment_id = "00000000-0000-0000-0000-000000000054"
    assignment_title = "Помочь с планом"  # noqa: RUF001
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = _new_page(browser)
        requests: list[str] = []
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
                            "title": malicious,
                            "description": malicious,
                            "completion_criteria": malicious,
                            "performer_instructions": malicious,
                            "materials": {"url": javascript_url, "text": malicious},
                            "public_input": {malicious: javascript_url},
                            "credit_reward_per_performer": 3,
                            "minimum_level": 1,
                        }
                    ],
                    "next_cursor": None,
                }
            ),
        )

        def accept(route: Route) -> None:
            operation_key = route.request.headers.get("idempotency-key", "")
            assert re.fullmatch(r"[1-9][0-9]{0,18}", operation_key)
            assert int(operation_key) <= 2**63 - 1
            route.fulfill(
                status=201,
                json={
                    "id": "00000000-0000-0000-0000-000000000054",
                    "task_id": task_id,
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
        page.route(
            f"**/api/v1/assignments/{assignment_id}",
            lambda route: route.fulfill(
                json=assignment
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
                }
            ),
        )

        page.goto(mini_app_url)
        page.get_by_role("button", name=malicious).click()
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
            == "#f6f8fc"
        )

        page.get_by_role("button", name="Принять задание").click()
        page.get_by_text("Задание принято. Можно переходить к выполнению.").wait_for()
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
            == "#f6f8fc"
        )
        browser.close()


def test_moderation_queue_loading_empty_closed_and_back_focus(  # noqa: PLR0915
    mini_app_url: str,
) -> None:
    malicious = "<img src=x onerror=alert(1)><script>bad()</script>"
    mode: dict[str, Any] = {"name": "pending"}
    pending: list[Route] = []
    requests: list[tuple[str, str]] = []

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
                        "status": "appealed",
                        "revision": 1,
                        "current_code": malicious,
                        "opened_at": "2026-08-17T20:00:00Z",
                        "resolved_at": None,
                        "reason": "PRIVATE_REASON",
                        "evidence": "PRIVATE_EVIDENCE",
                    }
                ]
            }
        )
        page.get_by_text("Спор по заданию").wait_for()
        assert malicious in page.locator("body").inner_text()
        assert "PRIVATE_REASON" not in page.locator("body").inner_text()
        assert "PRIVATE_EVIDENCE" not in page.locator("body").inner_text()
        assert page.locator("article button, article a, img, [onerror], [onclick]").count() == 0
        assert page.locator("script").count() == 2

        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Каталог").wait_for()
        assert moderation_nav.evaluate("node => node === document.activeElement")

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
    }
    list_mode: dict[str, Any] = {"status": 200, "items": []}
    detail_mode: dict[str, Any] = {"status": 200, "pending": False}
    pending_routes: list[Route] = []

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
        browser.close()
