# Отчёт о реализации CB-84

## Результат

Исполнитель на текущей карточке `accepted` assignment может указать причину и
отказаться. Mini App вызывает существующий `AssignmentService.cancel`, после
успеха возвращается к актуальному списку «Взятые мной», а освобождение слота,
reliability/outbox/receipt и возможное закрытие task остаются у прежнего owner.

## Матрица приёмки

| Критерий | Реализация | Доказательство |
|---|---|---|
| Existing owner без новых правил | `AssignmentService.cancel` получил только actor-native identity и exact Web receipt; прежние status/ownership/effects не перенесены в transport | `test_catalog_detail_projection_accept_and_cancel_path` и existing `test_assignments.py` |
| Session-owned actor и privacy | Endpoint не принимает actor/performer/status; current session даёт `member_id`, service перечитывает active member и закрывает чужой assignment | integration oracle: foreign actor получает `409`, persistent owner row остаётся единственной |
| Active test-run scope | Fresh mutation и exact replay повторно применяют существующий `ensure_task_test_access` до эффекта/возврата | direct UUID вне scope получает `409` без receipt/outbox/cancellation; replay после деактивации participant также получает `409` |
| Exact replay/conflict | update ID namespaced actor+assignment+operation key; receipt outcome хранит actor+assignment+fingerprint нормализованной причины | exact replay `204`, тот же key с другой причиной `409`, один cancellation reliability/outbox/receipt effect |
| Bounded trust boundary | canonical UUID, same-origin, обязательный decimal idempotency key, bounded JSON, stripped reason `1..1000`, allowlisted errors | route unit, Pydantic request и integration oracle |
| Одна форма текущего UI | `renderCancellation` добавляется только для `accepted`; retryable failure сохраняет key; success заменяет terminal history entry и вызывает существующий `loadAssignments(false)` | browser oracle проверяет пустой active list, `#assignments` и `{screen: "assignments"}` |
| Нет engine/data expansion | Нет новых domain rules, schema, migration, model, repository, service, dependency, framework, navigation или второго экрана | diff: 3 production-файла, production net `+161` |
| Templates/community исключены | Runtime diff не затрагивает catalog/community owners; multi-actor publication stop gate сохранён | source mapping в `plan-source-context.md` и фактический diff |
| Delivery gate | Требуется после merge | Пока не выполнен; блокирует Jira `Done` |

## Проверки

- targeted route/API/browser: `3 passed`;
- полные релевантные `test_web_auth.py`, `test_web_api.py`, `test_mini_app.py`: `42 passed`;
- application/API combined без неприменимого project-wide coverage threshold: `49 passed`;
- тот же selected-files прогон с coverage выполнил все `49` тестов; общий coverage выбранного поднабора `54.13%` ожидаемо ниже project-wide `80%`, owner coverage: `assignments.py 71%`, `web.py 91%`;
- `ruff format --check`, `ruff check`, `ty check`, `node --check`, `git diff --check` — green;
- secret-pattern scan tracked diff — `PASS`.

## Размер и Ponytail

- 3 production-файла и 3 test-файла;
- production diff: `+166/-5`, net `+161`;
- тестовый diff расширен только доказательствами authorization/history findings финального ревью; heuristic ceiling production-пути сохранён;
- `ponytail-review`: `Lean already. Ship.` — отдельные command/service/UI abstractions увеличили бы diff без нового владельца поведения.

## Остаточный риск

Локальные проверки не доказывают immutable release, production activation и
public smoke. Эти gates выполняются после merge и до Jira `Done`.
