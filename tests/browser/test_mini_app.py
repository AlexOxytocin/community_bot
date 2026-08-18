from __future__ import annotations

import functools
import http.server
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Route

pytestmark = pytest.mark.browser

STATIC_DIR = Path(__file__).parents[2] / "src/community_bot/transport/static"


class _AssetsHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ANN401
        del format, args

    def translate_path(self, path: str) -> str:
        relative = "index.html" if path == "/" else path.removeprefix("/mini-assets/")
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


def test_catalog_detail_accept_is_literal_and_confirmed(mini_app_url: str) -> None:
    malicious = "<img src=x onerror=alert(1)><script>bad()</script>"
    javascript_url = "javascript:globalThis.pwned=true"
    task_id = "00000000-0000-0000-0000-000000000053"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
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

        page.goto(mini_app_url)
        page.get_by_role("button", name=malicious).click()
        assert page.locator("body").inner_text().count(malicious) >= 4
        assert javascript_url in page.locator("body").inner_text()
        assert page.locator("img, a, [onerror], [onclick], [href^='javascript:']").count() == 0
        assert page.locator("script").count() == 1
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
