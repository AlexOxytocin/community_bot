# ruff: noqa: D100, D101, D102, D103, E501, INP001, PLR0915, PT018, RUF001, S101
from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Route, sync_playwright

from community_bot.transport.web import MeDto, MemberDto, TaskDto

ROOT = Path(__file__).parents[2]
STATIC_DIR = ROOT / "src/community_bot/transport/static"
OUTPUT_DIR = Path(__file__).parent / "evidence/authenticated"
TELEGRAM_BRIDGE_URL = "https://telegram.org/js/telegram-web-app.js"
MEMBER_ID = "00000000-0000-0000-0000-000000000097"
TARGET_ID = "00000000-0000-0000-0000-000000000096"
TASK_ID = "00000000-0000-0000-0000-000000000098"
ASSIGNMENT_ID = "00000000-0000-0000-0000-000000000099"
CASE_ID = "00000000-0000-0000-0000-000000000100"
STATE: dict[str, Any] = {}


class AssetsHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ANN401
        del format, args

    def translate_path(self, path: str) -> str:
        request_path = urlsplit(path).path
        relative = (
            "index.html" if request_path == "/" else request_path.removeprefix("/mini-assets/")
        )
        return str(STATIC_DIR / relative)


def fulfill_api(route: Route) -> None:  # noqa: C901, PLR0911, PLR0912
    path = urlsplit(route.request.url).path
    method = route.request.method
    if path == "/api/v1/me":
        me = {
            "member_id": MEMBER_ID,
            "display_name": "Алекс",
            "city": "Buenos Aires",
            "timezone": "America/Argentina/Buenos_Aires",
            "short_bio": "Помогаю запускать полезные проекты.",
            "current_goal": "Собрать сильную команду",
            "help_categories": ["Практическая помощь"],
            "skill_tags": ["Планирование", "Редактура"],
            "availability": "Вечера будней",
            "credit_balance": 12,
            "experience_total": 34,
            "level": {"number": 3, "display_name": "Практик"},
        }
        MeDto.model_validate(me)
        route.fulfill(json=me)
        return
    task = {
        "id": TASK_ID,
        "origin": "member",
        "title": "Подготовить план запуска",
        "author_display_name": "Мария",
        "category_name": "Практическая помощь",
        "category_icon": None,
        "task_kind": "solo",
        "time_size": "s",
        "deadline_at": "2026-09-01T20:00:00Z",
        "credit_reward_per_performer": 3,
        "performer_slots": 1,
        "minimum_level": 1,
        "format": "online",
        "city": None,
        "status": "published",
        "description": "Собрать короткий и понятный план запуска.",
        "completion_criteria": "План содержит владельцев и сроки.",
        "performer_instructions": "Проверьте приоритеты.",
        "public_input": {},
        "materials": {},
        "eligibility": {"can_accept": True, "reason": None},
    }
    TaskDto.model_validate({key: value for key, value in task.items() if key != "eligibility"})
    if path == "/api/v1/tasks":
        route.fulfill(
            json={
                "items": [
                    task,
                    task
                    | {
                        "id": "00000000-0000-0000-0000-000000000101",
                        "title": "Вычитать памятку для участников",
                        "description": "Проверить понятность текста и отметить спорные формулировки.",
                        "credit_reward_per_performer": 4,
                        "performer_slots": 2,
                    },
                    task
                    | {
                        "id": "00000000-0000-0000-0000-000000000102",
                        "title": "Собрать контакты районных волонтёров",
                        "description": "Добавить проверенные контакты трёх организаций.",
                        "credit_reward_per_performer": 2,
                    },
                ],
                "next_cursor": None,
            }
        )
        return
    if path == "/api/v1/task-creation" and method == "POST":
        action = (route.request.post_data_json or {}).get("action")
        if action == "save":
            STATE["creation"] = "preview"
        if action == "publish":
            route.fulfill(json={"task_id": TASK_ID})
            return
        route.fulfill(status=204)
        return
    if path == "/api/v1/task-creation":
        route.fulfill(
            json={
                "categories": [{"id": TASK_ID, "name": "Практическая помощь", "icon": ""}],
                "time_sizes": [
                    {
                        "value": "s",
                        "label": "15–40 минут",
                        "reward_options": [2, 3, 4],
                        "minimum_reward": 2,
                    }
                ],
                "draft": {"id": TASK_ID, "revision": 0, "values": {}},
                "preview": (
                    {
                        "title": "Подготовить план запуска",
                        "description": "Собрать короткий и понятный план запуска.",
                        "completion_criteria": "План содержит владельцев и сроки.",
                        "reward_total": 3,
                    }
                    if STATE.get("creation") == "preview"
                    else None
                ),
                "needs_edit": False,
            }
        )
        return
    member = {
        "member_id": TARGET_ID,
        "display_name": "Мария",
        "telegram_username": "maria",
        "city": None,
        "short_bio": "Помогаю участникам с планированием.",
        "current_goal": "Запустить полезную инициативу",
        "help_categories": ["Практическая помощь"],
        "skill_tags": ["Планирование"],
        "availability": "Вечера будней",
        "experience_total": 34,
        "level_number": 3,
        "karma": {"score": 8, "count": 10},
        "reliability": {
            "accepted": 14,
            "approved_weight": "12.5",
            "no_show": 1,
            "rate": "0.93",
        },
    }
    MemberDto.model_validate(member)
    own_member = member | {
        "member_id": MEMBER_ID,
        "display_name": "Алекс",
        "telegram_username": "alex",
    }
    if path == f"/api/v1/members/{MEMBER_ID}":
        route.fulfill(json=own_member)
        return
    if path == f"/api/v1/members/{TARGET_ID}":
        route.fulfill(json=member)
        return
    if path == "/api/v1/members":
        route.fulfill(json={"items": [member]})
        return
    if path == "/api/v1/leaderboard":
        route.fulfill(
            json={
                "items": [
                    {
                        "rank": 1,
                        "member_id": TARGET_ID,
                        "display_name": "Мария",
                        "experience": 34,
                        "unique_recipients": 8,
                        "reliability": "0.93",
                        "no_show": 1,
                    }
                ]
            }
        )
        return
    if path == f"/api/v1/members/{TARGET_ID}/karma-vote":
        action = (route.request.post_data_json or {}).get("action")
        revisions = {"begin": 0, "save_value": 1, "save_comment": 2, "confirm": 3}
        revision = revisions.get(action)
        if revision is None:
            route.fulfill(status=422, json={"code": "invalid_action"})
            return
        route.fulfill(
            json={
                "action": action,
                "target_id": TARGET_ID,
                "step": "confirmed" if action == "confirm" else action,
                "revision": revision,
                "aggregate": {"score": 9, "count": 11} if action == "confirm" else None,
            }
        )
        return
    if path == "/api/v1/me/profile":
        route.fulfill(json={"member_id": MEMBER_ID, "display_name": "Алекс"})
        return
    assignment = {
        "id": ASSIGNMENT_ID,
        "task_id": TASK_ID,
        "task_title": "Подготовить план запуска",
        "task_origin": "member",
        "assignment_status": "submitted",
        "accepted_at": "2026-08-18T15:00:00Z",
        "submitted_at": "2026-08-18T17:00:00Z",
        "review_deadline_at": "2026-08-21T17:00:00Z",
        "reject_dispute_deadline_at": None,
        "reviewed_at": None,
        "task_deadline_at": "2026-09-01T20:00:00Z",
        "result_summary": "Черновик плана готов",
        "case_status": None,
    }
    if path == "/api/v1/assignments":
        route.fulfill(json={"items": [assignment], "next_cursor": None})
        return
    if path == f"/api/v1/assignments/{ASSIGNMENT_ID}" and method == "GET":
        mode = STATE.get("assignment_mode", "submitted")
        route.fulfill(
            json=assignment
            | {
                "assignment_status": "rejected_pending_dispute" if mode == "dispute" else mode,
                "category_name": "Практическая помощь",
                "task_kind": "solo",
                "time_size": "s",
                "description": task["description"],
                "performer_instructions": "Проверьте приоритеты.",
                "completion_criteria": task["completion_criteria"],
                "reward_per_performer": 3,
                "format": "online",
                "city": None,
                "minimum_level": 1,
                "performer_slots": 1,
                "submission_contract": None,
                "reject_dispute_deadline_at": "2026-08-22T17:00:00Z" if mode == "dispute" else None,
                "case_status": "open" if mode == "disputed" else None,
                "can_submit": mode == "accepted",
                "can_cancel": mode == "accepted",
                "can_dispute": mode == "dispute",
            }
        )
        return
    if path == f"/api/v1/assignments/{ASSIGNMENT_ID}/submission-drafts":
        route.fulfill(json={"id": TASK_ID, "revision": 0, "result": None})
        return
    if path == f"/api/v1/submission-drafts/{TASK_ID}" and method == "PUT":
        result = (route.request.post_data_json or {})["payload"]["result"]
        route.fulfill(json={"id": TASK_ID, "revision": 1, "result": result})
        return
    if path == f"/api/v1/submission-drafts/{TASK_ID}/confirm":
        route.fulfill(status=204)
        return
    if path == f"/api/v1/assignments/{ASSIGNMENT_ID}/cancellation":
        route.fulfill(status=204)
        return
    if path == f"/api/v1/assignments/{ASSIGNMENT_ID}/disputes":
        STATE["assignment_mode"] = "disputed"
        route.fulfill(status=204)
        return
    if path == "/api/v1/owned-tasks":
        route.fulfill(
            json={
                "items": [
                    {
                        "id": TASK_ID,
                        "title": task["title"],
                        "status": "published",
                        "performer_slots": 1,
                        "deadline_at": task["deadline_at"],
                        "assignees": [{"display_name": "Алекс", "status": "submitted"}],
                        "cancellation_status": None,
                    }
                ]
            }
        )
        return
    review = {
        "id": ASSIGNMENT_ID,
        "task_title": task["title"],
        "performer_display_name": "Алекс",
        "review_deadline_at": "2026-08-21T17:00:00Z",
        "result": "Черновик плана готов",
        "available_decisions": ["full", "partial", "reject"],
    }
    if path == "/api/v1/assignment-reviews":
        route.fulfill(json={"items": [review]})
        return
    if path == f"/api/v1/assignment-reviews/{ASSIGNMENT_ID}":
        route.fulfill(json=review)
        return
    if path == f"/api/v1/assignment-reviews/{ASSIGNMENT_ID}/decision":
        route.fulfill(status=204)
        return
    if path == "/api/v1/moderation/cases":
        route.fulfill(
            json={
                "items": [
                    {
                        "id": CASE_ID,
                        "case_type": "dispute",
                        "task_title": task["title"],
                        "status": "open",
                        "opened_at": "2026-08-18T19:00:00Z",
                        "dispute_reason": "Нужна независимая проверка",
                    }
                ]
            }
        )
        return
    if path == f"/api/v1/moderation/cases/{CASE_ID}" and method == "GET":
        route.fulfill(
            json={
                "id": CASE_ID,
                "revision": 1,
                "task_title": task["title"],
                "task_origin": "member",
                "credit_reward_per_performer": 3,
                "dispute_reason": "Нужна независимая проверка",
                "result_summary": "Черновик плана готов",
                "allowed_resolution_codes": ["approve_full", "reject"],
            }
        )
        return
    if path == f"/api/v1/moderation/cases/{CASE_ID}/resolution":
        route.fulfill(status=204)
        return
    route.fulfill(status=404, json={"code": "not_found", "path": path})


def capture(page: Any, screen_id: str, width: int, height: int) -> None:  # noqa: ANN401
    page.locator(f'[data-screen-id="{screen_id}"]').wait_for()
    page.wait_for_function(
        "screenId => { const node = document.querySelector(`[data-screen-id=\"${screenId}\"]`); return node && node.dataset.state !== 'loading'; }",
        arg=screen_id,
    )
    shell_box = page.locator("#app").bounding_box()
    nav_box = page.locator("#primary-navigation").bounding_box()
    heading_box = page.locator("#screen-title").bounding_box()
    assert shell_box is not None and shell_box["y"] >= 0
    assert shell_box["y"] + shell_box["height"] <= height
    if screen_id != "T05":
        assert heading_box is not None and heading_box["y"] >= shell_box["y"]
        assert page.locator(".screen").evaluate("node => node.scrollTop") == 0
    if screen_id in {"T01", "P01", "P05", "P06", "M01", "M02", "S01"}:
        assert nav_box is not None
    if nav_box is not None:
        assert nav_box["y"] + nav_box["height"] <= height
    page.screenshot(path=OUTPUT_DIR / f"{screen_id}-{width}x{height}.png", full_page=False)


def run() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(AssetsHandler, directory=STATIC_DIR)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for width, height in ((375, 812), (430, 932)):
                STATE.clear()
                STATE.update(creation="draft", assignment_mode="submitted")
                page = browser.new_page(viewport={"width": width, "height": height})
                page.route(
                    TELEGRAM_BRIDGE_URL,
                    lambda route: route.fulfill(
                        body="globalThis.Telegram={WebApp:{ready(){},expand(){}}};",
                        content_type="application/javascript",
                    ),
                )
                page.route("**/api/v1/**", fulfill_api)
                page.goto(url)
                capture(page, "T01", width, height)
                page.get_by_role("button", name="3 задания доступны сейчас").click()
                capture(page, "T02", width, height)
                page.get_by_role("button", name="Назад").click()
                page.get_by_role("button", name="Подготовить план запуска").click()
                capture(page, "T03", width, height)
                page.get_by_role("button", name="Принять задание").click()
                capture(page, "T03A", width, height)
                page.get_by_role("button", name="Изменить").click()
                page.get_by_role("button", name="Назад").click()
                page.get_by_role("button", name="+ Создать", exact=True).click()
                capture(page, "T04", width, height)
                page.get_by_role("button", name="Один участник").click()
                capture(page, "T04A", width, height)
                page.get_by_role("button", name="Без шаблона").click()
                page.get_by_label("Тип").select_option("solo")
                page.get_by_label("Число исполнителей").fill("3")
                page.get_by_label("Формат").select_option("offline")
                page.get_by_label("Город").fill("Buenos Aires")
                page.get_by_label("Категория").select_option(TASK_ID)
                page.get_by_label("Размер").select_option("s")
                page.get_by_label("Награда").fill("3")
                page.get_by_label("Название").fill("Подготовить план запуска")
                page.get_by_label("Описание").fill("Собрать короткий и понятный план запуска.")
                page.get_by_label("Критерии выполнения").fill("План содержит владельцев и сроки.")
                page.get_by_label("Срок").fill("2026-09-01T20:00")
                page.get_by_label("Материалы").fill("Памятка по запуску")
                page.get_by_label("Ссылка", exact=True).fill("https://example.org/launch")
                capture(page, "T05", width, height)
                page.get_by_role("button", name="Предпросмотр").click()
                capture(page, "T06", width, height)
                page.get_by_role("button", name="Продолжить").click()
                capture(page, "T07", width, height)
                page.get_by_role("button", name="Опубликовать").click()
                capture(page, "T08", width, height)
                page.get_by_role("button", name="В каталог").click()
                page.locator("#participants-nav").click()
                capture(page, "P01", width, height)
                page.get_by_role("button", name="Лидерборд").click()
                capture(page, "P05", width, height)
                page.get_by_role("button", name="1. Мария").click()
                capture(page, "P02", width, height)
                page.get_by_role("button", name="Оценить карму").click()
                capture(page, "P03", width, height)
                page.get_by_label("Комментарий (10–300 символов)").fill(
                    "Спасибо за совместную работу"
                )
                page.get_by_role("button", name="Подтвердить оценку").click()
                page.get_by_role("button", name="Сохранить оценку").click()
                capture(page, "P04", width, height)
                page.get_by_role("button", name="К профилю").click()
                page.get_by_role("button", name="Назад").click()
                page.get_by_role("button", name="Профиль", exact=True).click()
                capture(page, "P06", width, height)
                page.get_by_role("button", name="Настройки профиля").click()
                capture(page, "P07", width, height)
                page.get_by_role("button", name="Назад").click()
                page.get_by_role("button", name="Мои задания").click()
                capture(page, "M01", width, height)
                page.get_by_role("button", name="В работе · 1").click()
                capture(page, "M02", width, height)
                page.get_by_role("button", name="Подготовить план запуска").click()
                capture(page, "M03", width, height)
                page.get_by_role("button", name="Назад").click()
                STATE["assignment_mode"] = "accepted"
                page.get_by_role("button", name="Подготовить план запуска").click()
                page.get_by_role("button", name="Отправить результат").click()
                page.get_by_role("button", name="Начать отправку").click()
                capture(page, "M04", width, height)
                page.get_by_role("textbox", name="Результат").fill("Черновик плана готов")
                page.get_by_role("button", name="Предпросмотр").click()
                capture(page, "M05", width, height)
                page.get_by_role("button", name="Продолжить").click()
                capture(page, "M06", width, height)
                page.get_by_role("button", name="Отправить результат").click()
                capture(page, "M07", width, height)
                page.get_by_role("button", name="К заданию").click()
                page.get_by_role("button", name="Отказаться от задания").click()
                page.get_by_label("Причина отказа").fill("Не успеваю завершить до срока")
                page.get_by_role("button", name="Подтвердить отказ").click()
                capture(page, "M08", width, height)
                page.get_by_role("button", name="Изменить").click()
                page.get_by_role("button", name="Назад").click()
                page.locator('[data-screen-id="M03"]').wait_for()
                page.get_by_role("button", name="Назад").click()
                page.get_by_role("button", name="Созданные мной").click()
                capture(page, "M09", width, height)
                page.get_by_role("button", name="Подготовить план запуска Опубликовано").click()
                capture(page, "M10", width, height)
                page.get_by_role("button", name="Назад").click()
                page.get_by_role(
                    "button", name="Подготовить план запуска Исполнитель: Алекс"
                ).click()
                capture(page, "M11", width, height)
                page.get_by_role("button", name="Принять полностью").click()
                capture(page, "M12", width, height)
                page.get_by_role("button", name="Принять полностью").click()
                capture(page, "M13", width, height)
                page.get_by_role("button", name="К созданным заданиям").click()
                page.goto(url)
                page.locator('[data-screen-id="T01"]').wait_for()
                page.get_by_role("button", name="Мои задания").click()
                page.locator('[data-screen-id="M01"]').wait_for()
                page.get_by_role("button", name="В работе · 1").click()
                STATE["assignment_mode"] = "dispute"
                page.get_by_role("button", name="Подготовить план запуска").click()
                page.get_by_role("button", name="Подать спор").click()
                page.get_by_label("Почему результат нужно пересмотреть").fill(
                    "Нужна независимая проверка результата"
                )
                page.get_by_role("button", name="Подать спор").click()
                capture(page, "M14", width, height)
                page.get_by_role("button", name="Подать спор").click()
                capture(page, "M15", width, height)
                page.goto(url)
                page.locator('[data-screen-id="T01"]').wait_for()
                page.get_by_role("button", name="Модерация").click()
                capture(page, "S01", width, height)
                page.locator("button.moderation-card").click()
                capture(page, "S02", width, height)
                page.get_by_label("Причина решения").fill("Проверка подтверждает результат")
                page.get_by_role("button", name="Проверить решение").click()
                capture(page, "S03", width, height)
                page.get_by_role("button", name="Применить решение").click()
                capture(page, "S04", width, height)
                page.close()
            browser.close()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


if __name__ == "__main__":
    run()
