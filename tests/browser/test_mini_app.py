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


def _connected_control(page: Any, edge_id: str, trigger: str) -> Any:  # noqa: ANN401
    control = page.locator(f'[data-transition-id="{edge_id}"][data-transition-trigger="{trigger}"]')
    control.first.wait_for()
    assert control.count() >= 1
    return control


def _open_blank_task_creation(page: Any, *, group: bool = False) -> None:  # noqa: ANN401
    page.get_by_role("button", name="+ Создать", exact=True).click()
    page.locator('[data-screen-id="T04B"], [data-screen-id="T05"]').wait_for()
    recovery = page.locator('[data-screen-id="T04B"]')
    if recovery.count():
        recovery.get_by_role("button", name=re.compile("Продолжить|Редактировать")).click()
    if group:
        page.get_by_role("button", name="Групповое", exact=True).click()


def _cache_profile(member_id: str = "member-cache") -> tuple[dict[str, Any], dict[str, Any]]:
    me = {
        "member_id": member_id,
        "display_name": "Алекс",
        "city": "Rosario",
        "timezone": "UTC",
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
        page.route("**/api/v1/me/profile", lambda route: route.fulfill(json=me))
        page.goto(mini_app_url)
        page.get_by_text("Сохранённый каталог", exact=True).wait_for()
        page.get_by_role("button", name="Профиль", exact=True).click()
        page.locator("h2", has_text="Алекс").wait_for()
        page.get_by_role("button", name="Задания", exact=True).click()
        assert page.get_by_text("Сохранённый каталог", exact=True).is_visible()
        assert page.get_by_text("Загружаем задания…").count() == 0
        assert task_requests == 1
        page.get_by_role("button", name="Профиль", exact=True).click()
        assert page.locator("h2", has_text="Алекс").is_visible()
        assert page.get_by_text("Загружаем профиль…").count() == 0
        page.evaluate("advanceCacheClock(60001)")
        page.get_by_role("button", name="Задания", exact=True).click()
        assert page.get_by_text("Сохранённый каталог", exact=True).is_visible()
        assert page.get_by_text("Загружаем задания…").count() == 0
        assert task_requests == 2
        pending.pop(0).fulfill(json={"items": [refreshed_task], "next_cursor": None})
        page.get_by_text("Обновлённый каталог", exact=True).wait_for()

        page.get_by_role("button", name="Профиль", exact=True).click()
        page.get_by_role("button", name="Редактировать город").click()
        page.get_by_role("textbox", name="Город", exact=True).fill("Córdoba")
        page.get_by_role("button", name="Сохранить").click()
        page.get_by_role("button", name="Редактировать город").wait_for()
        page.locator("h2", has_text="Алекс").wait_for()
        catalog = page.get_by_role("button", name="Задания", exact=True)
        catalog.click()
        catalog.click()
        assert task_requests == 3
        pending.pop(0).fulfill(json={"items": [refreshed_task], "next_cursor": None})
        page.get_by_text("Обновлённый каталог", exact=True).wait_for()

        page.get_by_role("button", name="Профиль", exact=True).click()
        page.evaluate("advanceCacheClock(60001)")
        page.get_by_role("button", name="Задания", exact=True).click()
        assert page.get_by_text("Обновлённый каталог", exact=True).is_visible()
        assert task_requests == 4
        page.wait_for_timeout(50)
        page.get_by_role("button", name="Профиль", exact=True).click()
        page.locator("h2", has_text="Алекс").wait_for()
        page.get_by_role("button", name="Задания", exact=True).click()
        page.get_by_text("Обновлённый каталог", exact=True).wait_for()
        assert task_requests == 5
        browser.close()


def test_assignment_action_eligibility_is_server_projected() -> None:
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'assignment.assignment_status === "accepted"' not in source
    assert "if (assignment.can_submit)" in source
    assert "if (assignment.can_cancel)" in source


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
        assert page.locator(".profile-pencil").count() == 5
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
        page.get_by_role("button", name="Добавить описание").wait_for()
        for label in ("Добавить описание", "Добавить навыки", "Добавить ссылки"):
            assert page.get_by_role("button", name=label).is_visible()
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
        page.get_by_role("heading", name="Мои ссылки").wait_for()
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
        page.get_by_role("heading", name="Мои ссылки").wait_for()
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
        page.get_by_role("heading", name="Мои ссылки").wait_for()
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
        page.get_by_role("heading", name="Мои ссылки").wait_for()
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
        page.get_by_role("heading", name="Мои ссылки").wait_for()
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
        page.get_by_role("heading", name="Участники").wait_for()
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
            page.goto(mini_app_url)
            page.locator('[data-screen-id="T01"][data-ui-engine="concept-05"]').wait_for()
            page.get_by_role("button", name="Модерация").wait_for()
            assert page.get_by_role("navigation", name="Основное меню").get_by_role(
                "button"
            ).all_inner_texts() == [
                "Задания",
                "Мои",
                "Участники",
                "Профиль",
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
                    icons: nav.querySelectorAll('svg.nav-icon path').length,
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
                "icons": 5,
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
            page.goto(mini_app_url)

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
            create = page.get_by_role("button", name="+ Создать", exact=True)
            assert filters.is_visible()
            assert create.is_visible()
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
            page.get_by_role("heading", name="Фильтры заданий").wait_for()
            page.get_by_role("button", name="Назад").click()
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
        page.route("**/api/v1/assignments/*", detail_route)

        page.goto(mini_app_url)
        page.get_by_role("button", name="Восстановить экран").click()
        page.reload()
        page.get_by_role("heading", name="Восстановить экран").wait_for()
        assert len(task_fetches) == 2
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Задания").wait_for()

        page.get_by_role("button", name="Мои задания").click()
        page.reload()
        page.get_by_role("heading", name="Мои задания").wait_for()
        page.get_by_role("button", name="Задания", exact=True).click()
        page.goto(mini_app_url + "?case=detail#/work/" + assignment_id + "?view_state=m03")
        page.get_by_text("SERVER-PROJECTION").wait_for()
        assert detail_fetches == [assignment_id]
        page.get_by_role("button", name="Назад").click()
        page.get_by_role("heading", name="Задания").wait_for()

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
        page.get_by_role("heading", name="Задания").wait_for()
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
        expected_deadline = page.evaluate(
            """value => new Intl.DateTimeFormat("ru", {
              dateStyle: "medium", timeStyle: "short"
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
        assert page.url.endswith(f"#/tasks/{task_id}?view_state=t03a")
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
        page.locator('[data-screen-id="T03"]').wait_for()
        page.get_by_role("button", name="Назад").click()
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
        page.locator('[data-screen-id="T03"]').wait_for()
        page.get_by_role("button", name="Назад").click()
        catalog_trigger = page.get_by_role("button", name=malicious)
        catalog_trigger.wait_for()
        assert catalog_trigger.evaluate("node => node === document.activeElement")

        page.get_by_role("button", name="Мои задания").click()
        page.get_by_role("heading", name="Мои задания").wait_for()
        page.get_by_role("button", name=re.compile("В работе · ")).click()  # noqa: RUF001
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


def test_moderation_queue_detail_confirm_retry_conflict_and_back_focus(  # noqa: C901, PLR0915
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
        page.route("**/api/v1/moderation/cases/*/resolution", resolution_route)
        page.route("**/api/v1/moderation/cases/*", detail_route)

        page.goto(mini_app_url + "#/moderation?view_state=s01")
        moderation_nav = page.get_by_role("button", name="Модерация")
        page.get_by_text("Загружаем очередь…").wait_for()
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
        assert page.url.endswith("#/moderation/00000000-0000-0000-0000-000000000061?view_state=s03")
        page.get_by_role("button", name="Назад").click()
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
        page.get_by_role("button", name="К очереди").click()  # noqa: RUF001
        page.get_by_text("Открытых обращений нет.").wait_for()
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
        page.get_by_role("button", name="Спор по заданию").click()
        page.get_by_role("combobox", name="Решение").select_option("partial_payment")
        page.get_by_role("textbox", name="Причина решения").fill("Подтверждена половина результата")
        page.get_by_role("button", name="Проверить решение").click()
        assert page.url.endswith("#/moderation/00000000-0000-0000-0000-000000000061?view_state=s03")
        page.get_by_role("button", name="Применить решение").click()
        page.get_by_text("Кейс уже изменился").wait_for()
        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="S02"]').wait_for()
        assert page.url.endswith("#/moderation/00000000-0000-0000-0000-000000000061?view_state=s02")
        page.evaluate("advanceCacheClock(60001)")
        with page.expect_request("**/api/v1/moderation/cases?*"):
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
        page.get_by_role("button", name="Задания", exact=True).click()
        page.get_by_role("heading", name="Задания").wait_for()

        mode["name"] = "empty"
        page.evaluate("advanceCacheClock(60001)")
        moderation_nav.click()
        page.get_by_text("Открытых обращений нет.").wait_for()
        page.get_by_role("button", name="Задания", exact=True).click()
        page.get_by_role("heading", name="Задания").wait_for()

        mode["name"] = "closed"
        page.evaluate("advanceCacheClock(60001)")
        with page.expect_response(lambda response: response.status == 403):
            moderation_nav.click()
        page.get_by_text("Открытых обращений нет.").wait_for()
        assert page.get_by_text("Очередь модерации недоступна").count() == 0
        assert "Moderator" not in page.locator("body").inner_text()
        page.get_by_role("button", name="Задания", exact=True).click()
        page.get_by_role("heading", name="Задания").wait_for()

        mode["name"] = "unauthorized"
        page.evaluate("advanceCacheClock(60001)")
        with page.expect_response(lambda response: response.status == 401):
            moderation_nav.click()
        page.get_by_text("Открытых обращений нет.").wait_for()
        moderation_nav.click()
        page.get_by_text("Сессия истекла. Закройте и снова откройте Mini App.").wait_for()
        page.get_by_role("button", name="Задания", exact=True).click()
        page.get_by_role("heading", name="Задания").wait_for()

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
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    removed_profile_surface = (
        "help_categories",
        "current_goal",
        "member.availability",
        "Часовой пояс",
        "Категории помощи",
        "Текущая цель",
        "Доступность",
    )
    assert {token: source.count(token) for token in removed_profile_surface} == dict.fromkeys(
        removed_profile_surface, 0
    )
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
        page.route("**/api/v1/leaderboard?*", leaderboard_route)
        page.route(
            "**/api/v1/tasks",
            lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
        )
        page.goto(mini_app_url)
        page.get_by_role("heading", name="Задания").wait_for()

        capture_requests = True
        profile_nav = page.get_by_role("button", name="Профиль", exact=True)
        profile_nav.click()
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
        assert page.locator("img, [onerror], [onclick]").count() == 0
        assert page.locator("script").count() == 2
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

        page.get_by_role("button", name="Редактировать город").click()
        page.get_by_role("textbox", name="Город", exact=True).fill("Rosario")
        page.get_by_role("button", name="Сохранить").click()
        page.get_by_text(
            "Не удалось сохранить. Повторите попытку."  # noqa: RUF001
        ).wait_for()
        assert page.get_by_role("textbox", name="Город", exact=True).input_value() == "Rosario"
        page.get_by_role("button", name="Сохранить").click()
        page.get_by_text(
            "Не удалось сохранить. Повторите попытку."  # noqa: RUF001
        ).wait_for()
        profile_updates_before = len(profile_update_keys)
        page.get_by_role("button", name="Сохранить").click()
        page.get_by_role("button", name="Редактировать город").click()
        assert page.get_by_role("textbox", name="Город", exact=True).input_value() == "Rosario"
        assert len(profile_update_keys) == profile_updates_before + 1
        assert profile_update_keys[0] == profile_update_keys[1] == profile_update_keys[2]
        assert page.get_by_text("Не удалось сохранить.", exact=False).count() == 0  # noqa: RUF001

        invalid_city = page.get_by_role("textbox", name="Город", exact=True)
        invalid_city.fill("x")
        profile_updates_before_invalid = len(profile_update_keys)
        page.get_by_role("button", name="Сохранить").click()
        assert invalid_city.evaluate("node => !node.checkValidity()")
        assert len(profile_update_keys) == profile_updates_before_invalid
        page.get_by_role("button", name="Назад").click()
        updates_before_cancel = len(profile_update_keys)
        page.get_by_role("button", name="Редактировать обо мне").click()  # noqa: RUF001
        page.get_by_label("Описание").fill("Несохранённое значение профиля")
        page.get_by_role("button", name="Назад").click()
        assert len(profile_update_keys) == updates_before_cancel
        assert page.get_by_text("Помогаю собирать ясные планы.", exact=True).count() == 1

        modes.update(member="success", leaderboard="success")
        me["skill_tags"] = []
        profile_nav.click()
        page.locator("h2", has_text=malicious).wait_for()
        assert page.get_by_role("heading", name="Навыки").count() == 0
        assert page.locator(".leaderboard-row, .leaderboard-list").count() == 0
        assert private_marker not in page.locator("body").inner_text()

        modes.update(member="error", leaderboard="success")
        requests_before_cached_profile = len(requests)
        profile_nav.click()
        page.locator("h2", has_text=malicious).wait_for()
        assert page.get_by_text("Не удалось загрузить профиль.").count() == 0  # noqa: RUF001
        assert len(requests) == requests_before_cached_profile
        assert page.get_by_text("Лидерборд").count() == 0
        modes["member"] = "success"

        modes["leaderboard"] = "error"
        page.get_by_role("button", name="Участники", exact=True).click()
        page.locator('[data-screen-id="P01"][data-state="content"]').wait_for()
        page.get_by_role("button", name="Лидерборд").click()
        page.get_by_text("Не удалось загрузить данные.").wait_for()  # noqa: RUF001
        modes["leaderboard"] = "success"
        page.get_by_role("button", name="Повторить").click()
        page.get_by_text("12 XP").wait_for()
        assert page.get_by_text("Получатели помощи: 3").count() == 0
        assert page.get_by_text("Неявки: 1").count() == 0

        page.evaluate("Date.now = () => Number.MAX_SAFE_INTEGER")
        modes["leaderboard"] = "empty"
        assert page.locator("#primary-navigation").is_visible()
        page.locator("#participants-nav").click()
        page.locator('[data-screen-id="P01"][data-state="content"]').wait_for()
        page.get_by_role("button", name="Лидерборд").click()
        page.get_by_text("В лидерборде пока никого нет.").wait_for()  # noqa: RUF001

        page.locator("#participants-nav").click()
        page.locator('[data-screen-id="P01"][data-state="content"]').wait_for()
        page.get_by_role("button", name="Задания", exact=True).click()
        page.get_by_role("heading", name="Задания").wait_for()
        modes.update(member="pending", leaderboard="pending")
        profile_nav.click()
        page.locator("h2", has_text=malicious).wait_for()
        assert page.get_by_text("Загружаем профиль…").count() == 0
        page.wait_for_timeout(50)
        assert {urlsplit(route.request.url).path for route in pending} == {
            f"/api/v1/members/{member_id}"
        }
        catalog_nav = page.get_by_role("button", name="Задания", exact=True)
        assert page.get_by_role("button", name="Назад").is_hidden()
        catalog_nav.click()
        page.get_by_role("heading", name="Задания").wait_for()
        late_member = next(route for route in pending if "/members/" in route.request.url)
        late_member.fulfill(json=member)
        pending.remove(late_member)
        page.wait_for_timeout(50)
        assert page.get_by_role("heading", name="Профиль").count() == 0
        assert profile_nav.evaluate("node => node === document.activeElement")
        assert requests
        assert {
            ("PUT", "/api/v1/me/profile"),
            ("GET", "/api/v1/me"),
            ("GET", "/api/v1/members"),
            ("GET", f"/api/v1/members/{member_id}"),
            ("GET", "/api/v1/leaderboard"),
            ("GET", "/api/v1/tasks"),
        } == set(requests)
        assert {
            "/api/v1/me",
            "/api/v1/members",
            f"/api/v1/members/{member_id}",
            "/api/v1/leaderboard",
            "/api/v1/tasks",
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
        for width, height, minimum_visible in ((375, 812, 4), (430, 932, 5)):
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
                offset = {"week": 10, "month": 20, "all": 30}[period]
                route.fulfill(
                    json={
                        "items": [
                            {
                                "rank": index,
                                "member_id": member_id,
                                "display_name": names[index - 1],
                                "experience": offset - index + 1,
                                "unique_recipients": 1,
                                "reliability": "0.98",
                                "no_show": 0,
                            }
                            for index, member_id in enumerate(member_ids, start=1)
                        ]
                    }
                )

            page.route("**/api/v1/leaderboard?*", leaderboard_route)
            page.goto(mini_app_url)
            page.get_by_role("button", name="Участники", exact=True).click()
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

            page.get_by_role("button", name="Лидерборд").click()
            page.get_by_role("button", name="Месяц").click()
            page.get_by_text("20 XP").wait_for()
            pending_week[0].fulfill(
                json={
                    "items": [
                        {
                            "rank": 1,
                            "member_id": member_ids[0],
                            "display_name": names[0],
                            "experience": 10,
                            "unique_recipients": 1,
                            "reliability": "0.98",
                            "no_show": 0,
                        }
                    ]
                }
            )
            page.wait_for_timeout(50)
            assert page.get_by_text("20 XP").count() == 1
            assert page.get_by_text("10 XP").count() == 0
            page.get_by_role("button", name="Всё время").click()
            page.get_by_role("button", name="Неделя").click()
            page.get_by_text("10 XP").wait_for()
            assert page.get_by_text("Загружаем данные…", exact=True).count() == 0
            pending_all[0].fulfill(
                json={
                    "items": [
                        {
                            "rank": 1,
                            "member_id": member_ids[0],
                            "display_name": names[0],
                            "experience": 30,
                            "unique_recipients": 1,
                            "reliability": "0.98",
                            "no_show": 0,
                        }
                    ]
                }
            )
            page.wait_for_timeout(50)
            assert page.get_by_text("10 XP").count() == 1
            assert page.get_by_text("30 XP").count() == 0
            page.get_by_role("button", name="Всё время").click()
            page.get_by_text("30 XP").wait_for()
            assert set(period_requests) == {"week", "month", "all"}
            assert page.locator(".leaderboard-row").count() == 1
            page.get_by_role("button", name="Месяц").click()
            page.get_by_text("20 XP").wait_for()
            assert page.locator(".leaderboard-row").count() == len(member_ids)
            assert page.locator(".leaderboard-row.is-current").count() == 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

            page.get_by_role("button", name="Профиль", exact=True).click()
            page.locator(".profile-overview").wait_for()
            assert page.url.endswith("#/profile")
            heading_box = page.locator(".screen-heading").bounding_box()
            assert heading_box is not None
            assert 0 < heading_box["width"] <= width
            assert heading_box["height"] > 0
            assert page.locator("#screen-title").text_content() == "Профиль"
            assert page.get_by_text("Карма", exact=True).count() == 1
            assert page.get_by_text("Надёжность", exact=True).count() == 0
            assert page.get_by_text("—", exact=True).count() >= 2
            assert page.locator("[data-profile-action]").count() == 5
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
        page.get_by_role("button", name="Профиль", exact=True).click()
        page.get_by_role("button", name="Участники", exact=True).click()
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
        page.get_by_text("Активных заданий пока нет.").wait_for()

        list_mode["status"] = 503
        page.evaluate("advanceCacheClock(60001)")
        with page.expect_response(lambda response: response.status == 503):
            page.get_by_role("button", name="Мои задания").click()
        page.get_by_text("Активных заданий пока нет.").wait_for()
        assert page.get_by_text("Не удалось загрузить активные назначения.").count() == 0  # noqa: RUF001

        list_mode["status"] = 401
        with page.expect_response(lambda response: response.status == 401):
            page.get_by_role("button", name="Мои задания").click()
        page.get_by_text("Активных заданий пока нет.").wait_for()
        page.get_by_role("button", name="Мои задания").click()
        page.get_by_text("Сессия истекла. Закройте и снова откройте Mini App.").wait_for()
        assert page.get_by_role("button", name="Повторить").count() == 0

        list_mode["status"] = 403
        page.get_by_role("button", name="Мои задания").click()
        page.get_by_text("Назначения недоступны для этого аккаунта.").wait_for()
        assert page.get_by_role("button", name="Повторить").count() == 0

        list_mode.update(status=200, items=[assignment])
        page.get_by_role("button", name="Мои задания").click()
        page.get_by_role("button", name="В работе · 1").click()  # noqa: RUF001
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
        page.get_by_role("heading", name="Мои задания").wait_for()
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
        assert page.get_by_label("Почему результат нужно пересмотреть").count() == 0
        page.get_by_role("button", name="Подать спор").click()
        page.get_by_label("Почему результат нужно пересмотреть").fill("Нужна независимая проверка")
        disputes_before = len(dispute_keys)
        _connected_control(page, "PE-044", "open_dispute_materials").click()
        _connected_control(page, "PE-044", "open_dispute_materials").click()
        page.get_by_text("Передан команде модерации").wait_for()
        assert len(dispute_keys) == disputes_before + 1

        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="M03"]').wait_for()
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
        assert route.request.method == "POST"
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
        page.get_by_role("button", name="В работе · 1").click()  # noqa: RUF001
        page.get_by_role("button", name=re.compile("Проверить форму")).click()
        page.locator('[data-screen-id="M03"]').wait_for()
        assert page.get_by_label("Причина отказа").count() == 0
        page.get_by_role("button", name="Отказаться от задания").click()
        page.get_by_label("Причина отказа").fill(" Cannot finish before deadline ")
        cancellations_before = len(operation_keys)
        _connected_control(page, "PE-036", "withdrawal_outcome").click()
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
                [{"display_name": "Исполнитель", "status": "submitted"}] if index == 1 else []
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
        page.goto(mini_app_url)
        page.get_by_role("button", name="Мои задания").click()
        page.get_by_role("button", name="В работе · 1").click()  # noqa: RUF001
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
            assert_top_left(page)
            page.get_by_role("button", name="Отправить результат").click()
            page.get_by_role("button", name="Начать отправку").click()
            page.get_by_role("textbox", name="Результат").fill("Результат " * 100)
            page.locator(".screen").evaluate(
                "node => { node.scrollTop = node.scrollHeight; "
                "node.scrollLeft = node.scrollWidth; }"
            )
            page.get_by_role("button", name="Предпросмотр").click()
            page.locator('[data-screen-id="M05"]').wait_for()
            page.locator(".screen").evaluate(
                "node => { node.scrollTop = node.scrollHeight; "
                "node.scrollLeft = node.scrollWidth; }"
            )
            page.get_by_role("button", name="Продолжить").click()
            page.locator('[data-screen-id="M06"]').wait_for()
            assert_top_left(page)
            page.get_by_role("button", name="Назад").click()
            page.locator('[data-screen-id="M03"]').wait_for()
            assert_top_left(page)

            page.goto(mini_app_url + f"#/members/{member_id}?view_state=p02")
            page.reload()
            page.locator('[data-screen-id="P02"]').wait_for()
            assert_top_left(page)
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
                    "categories": [{"id": task_id, "name": "Практическая помощь", "icon": "⭐"}],
                    "time_sizes": [
                        {
                            "value": "s",
                            "label": "15-40 минут",
                            "reward_options": [2, 3, 4],
                            "minimum_reward": 2,
                        }
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
        page.route("**/api/v1/me", lambda route: route.fulfill(json={"display_name": "Алекс"}))
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
        assert page.get_by_text("Ссылка", exact=True).count() == 0
        assert page.locator('[name="material_url"]').count() == 0
        page.get_by_role("button", name="Предварительный просмотр", exact=True).click()
        assert actions == []
        assert page.get_by_label("Название *", exact=True).evaluate(
            "node => node.matches(':invalid')"
        )
        slots = page.get_by_label("Число исполнителей *", exact=True)
        assert slots.input_value() == "1"
        assert slots.is_disabled()
        assert page.get_by_label("Город").count() == 0
        page.get_by_role("button", name="Групповое", exact=True).click()
        assert slots.is_enabled()
        assert slots.get_attribute("min") == "2"
        slots.fill("3")
        page.get_by_role("button", name="Личное", exact=True).click()
        assert slots.input_value() == "1"
        assert slots.is_disabled()
        page.get_by_role("button", name="Групповое", exact=True).click()
        assert slots.input_value() == "3"
        page.get_by_label("Категория *", exact=True).select_option(task_id)
        page.get_by_label("Размер *", exact=True).select_option("s")
        page.get_by_label("Награда за исполнителя *", exact=True).fill("3")
        page.get_by_label("Название *", exact=True).fill("<script>globalThis.pwned=true</script>")
        page.get_by_label("Что нужно сделать *", exact=True).fill(
            "Проверить безопасный предпросмотр."
        )
        page.get_by_label("Критерии приёмки *", exact=True).fill("Есть результат.")
        page.get_by_label("Срок *", exact=True).fill("2099-08-21T20:00")
        page.get_by_label("Число исполнителей *", exact=True).fill("2")
        page.get_by_label("Формат *", exact=True).select_option("offline")
        city = page.get_by_label("Город")
        assert city.evaluate("node => node.required")
        city.fill("Buenos Aires")
        page.get_by_role("option", name="Buenos Aires — Argentina").click()
        page.get_by_label("Формат *", exact=True).select_option("online")
        assert page.get_by_label("Город").count() == 0
        page.get_by_label("Формат *", exact=True).select_option("offline")
        city = page.get_by_label("Город")
        city.fill("Buenos Aires")
        page.get_by_role("option", name="Buenos Aires — Argentina").click()
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
        page.get_by_role("button", name="Редактировать черновик").click()
        page.get_by_label("Срок *", exact=True).fill("2099-08-22T20:00")
        page.get_by_role("button", name="Предварительный просмотр", exact=True).click()
        commands_before = len(commands)
        page.locator('[data-screen-id="T06"]').wait_for()
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
        page.route("**/api/v1/task-creation", creation)
        page.goto(mini_app_url)
        page.get_by_role("button", name="+ Создать", exact=True).click()
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
        assert page.get_by_label("Название").input_value() == ""
        assert page.url.endswith(f"#/compose/tasks/{new_id}?view_state=t05")
        page.get_by_role("button", name="Назад").click()
        page.locator('[data-screen-id="T04B"]').wait_for()
        assert page.get_by_text("Предпросмотр устарел", exact=False).count() == 0
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
                "**/api/v1/assignments?*",
                lambda route: route.fulfill(json={"items": [], "next_cursor": None}),
            )
            page.route("**/api/v1/task-creation", creation)
            page.goto(mini_app_url)

            _open_blank_task_creation(page)
            deadline = page.get_by_label("Срок")
            preview = page.get_by_role("button", name="Предварительный просмотр", exact=True)
            assert deadline.get_attribute("min") > "2000-01-01T00:00"
            assert deadline.get_attribute("aria-invalid") == "true"
            page.get_by_text("Выберите будущий срок.").wait_for()
            assert preview.is_disabled()

            deadline.fill("2099-01-01T00:00")
            assert deadline.get_attribute("aria-invalid") == "false"
            assert page.get_by_text("Выберите будущий срок.").is_hidden()
            assert not preview.is_disabled()
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
