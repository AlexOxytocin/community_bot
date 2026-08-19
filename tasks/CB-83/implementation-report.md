# Отчёт о реализации CB-83

## Результат

В текущем экране «Созданные мной» создатель видит собственные опубликованные задания до появления первого результата: lifecycle status, заполнение слотов и состояния исполнителей. Ниже сохраняется существующая секция результатов на проверку и её decision flow.

## Матрица приёмки

| Критерий | Реализация | Доказательство |
|---|---|---|
| Existing owner без новых правил | `TaskService.list_owned_cards` принимает ровно одну из legacy identity или server-issued `ActorContext`; Web вызывает existing `list_owned_task_cards(... creator_only=True)` | `test_owned_tasks_api_is_creator_scoped_and_actor_native` |
| Один read-only Web exposure и текущий экран | `GET /api/v1/owned-tasks`; `loadCreatedReviews` загружает owned cards и прежние reviews в одном экране | browser happy path и закрытый route allowlist |
| Server-owned actor и creator-only privacy | Endpoint не объявляет identity input; неизвестный `member_id` не меняет actor scope; чужое member task и community reviewer-only task исключены | integration API oracle |
| Existing review path сохранён | `/api/v1/assignment-reviews` и переход к решению остаются в том же browser scenario | `test_freeform_submission_uses_preview_confirm_and_detail_refresh` |
| Нет engine/domain/data expansion | Нет новых domain rules, query semantics, schema, model, repository, service/class, dependency, framework, CSS или screen | diff: 3 production-файла, только thin seam/adapter/UI |
| Delivery gate | Требуется после merge | Пока не выполнен; блокирует Jira `Done` |

## Проверки

- `uv run pytest tests/integration/test_web_api.py --no-cov -q` — `14 passed`;
- `uv run pytest tests/unit/test_web_auth.py tests/browser --no-cov -q` — `27 passed`;
- targeted API oracle — `1 passed`;
- targeted browser path — `1 passed`;
- `ruff format --check`, `ruff check`, `ty check` для изменённой области — green;
- `git diff --check` — green;
- secret scan новых строк: единственное совпадение — ссылка на существующую символическую test-константу `BOT_TOKEN`; нового значения, credential или session data нет.

## Размер и Ponytail

- 3 production-файла, 3 test-файла;
- production/test diff: `+213/-24`, net `+189`;
- независимый ceiling review: `Status: approved`; шестой файл является обязательным fail-closed allowlist маршрутов;
- `ponytail-review`: `Lean already. Ship.` — нечего удалять без потери actor boundary, API contract, UI journey или обязательных oracle.

## Остаточный риск

Локальные проверки не доказывают immutable release, production activation и public smoke. Эти gates выполняются только после merge проверенного PR.
