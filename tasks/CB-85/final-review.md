# CB-85 — независимое финальное ревью

Schema: `community_bot.final_review.verdict.v1`

Status: approved

## Проверенная область

- Уровень процесса: 2 — изменение Mini App operation identity при неопределённом результате и server-projected действий назначения.
- Ветка `task/CB-85` находится на base `1207463d45d0b640a4233a823e02893d9b42e9bd`, совпадающей с `origin/main`; проверен полный незакоммиченный diff production и tests.
- Production diff удержан в утверждённом ceiling: `src/community_bot/application/assignments.py`, `src/community_bot/transport/web.py`, `src/community_bot/transport/static/app.js`. Новых domain/repository/persistence/service/framework, schema/migration/dependency нет.

## Findings

### P1

Findings нет. Единственный P1 предыдущего review закрыт.

## Перепроверка предыдущего P1

`src/community_bot/transport/static/app.js:15, 717-740` хранит pending accept keys в нативном `Map` по `task.id`. Неопределённый результат A сохраняет ключ только A; accept B создаёт отдельный ключ, а success или definite failure удаляет только ключ соответствующего задания. Возврат к A повторяет исходную identity, поэтому другой command больше не может перезаписать или очистить pending retry A.

Browser oracle `tests/browser/test_mini_app.py:196-375` исполняет точную последовательность A → `503` → B → success → A → success, доказывает разные keys A/B, повтор исходного key A и authoritative reread обеих assignment detail.

## Матрица приёмки

| Критерий | Результат | Доказательство |
|---|---|---|
| `accepted` после deadline получает `can_submit=false` | пройден | `AssignmentCard.can_submit` повторно использует `require_submit_allowed`; PostgreSQL oracle в `tests/integration/test_web_api.py:1582-1620`. |
| Eligible freeform card получает `can_submit=true`, `can_cancel=true` | пройден | `src/community_bot/application/assignments.py:156-179`, DTO mapping `src/community_bot/transport/web.py:1678-1682`, integration oracle. |
| Клиент не вычисляет submit/cancel eligibility по статусу | пройден | Рендер использует только `assignment.can_submit`/`assignment.can_cancel` в `app.js:1262-1266`; статический browser oracle запрещает прежний allowlist. |
| Task creation сохраняет exact key/body после unknown и очищает после definite outcome | пройден | `pendingTaskCreation` хранит сериализованный body и key; browser oracle покрывает `503`, `409`, exact body/key и ротацию. |
| Accept сохраняет exact command после unknown и очищает только после definite outcome | пройден | `pendingAcceptKeys` scoped по `task.id`; browser oracle доказывает A→`503`, отдельный key B и exact retry key A после navigation. |
| После успешного accept выполняется authoritative reread | пройден | `app.js:731-733` вызывает `showAssignmentDetail(payload.id, false)` после успешного ответа. |
| Ownership, privacy, active visibility и test-run scope остаются server-owned | пройден | `AssignmentService.active_card` перечитывает actor и использует owner-scoped `get_assignment_card`; mutation validators остаются в application/domain. Client получает только bounded booleans. |
| Existing server replay/conflict и happy paths сохраняются | пройден по представленному evidence | В `implementation-report.md` зафиксированы targeted PostgreSQL `2 passed`, browser `10 passed`, non-integration/non-browser `421 passed`; P1 находится вне покрытого same-task retry сценария. |

## Validation evidence

- Фактически прочитаны полный diff, owner/validator paths `AssignmentService.accept_with_task`, `active_card`, `cancel`, `require_submit_allowed`, transport DTO и browser oracles.
- Представленный post-implementation evidence: Ruff format/check и `ty` — green; browser — `10 passed`; targeted PostgreSQL — `2 passed`; non-integration/non-browser — `421 passed`; `git diff --check` и secret-pattern scan — green.
- Независимый recheck: `uv run pytest --no-cov -q -p no:cacheprovider tests/browser/test_mini_app.py::test_catalog_detail_accept_is_literal_and_confirmed` → `1 passed in 2.33s`.

## Security, scope и workflow

- Обхода ownership/test-run/privacy проверки и переноса eligibility на клиент в проверенном diff не найдено.
- Секретов, credential literals, новых внешних эффектов, migration/schema/dependency изменений в diff не найдено.
- Ветка и обязательные артефакты уровня 2 присутствуют; несвязанных production paths не найдено.
- Обязательных исправлений по final review нет.

## Ponytail verdict

По сложности diff остаётся в заданном ceiling: task-bound state использует нативный `Map`, новых абстракций или зависимостей для удаления нет. `Lean already. Ship.`

## Обязательные действия

Обязательных исправлений нет. Локальный gate уровня 2 пройден; далее применяются штатные branch/PR/CI/merge и post-merge delivery gates.

## Остаточный риск и неопределённость

- После исправления остаётся обычное временное расхождение capability с серверным временем; mutation повторно проходит authoritative validation, поэтому это не блокер.
- CI, merge, immutable release, production activation и public smoke ADR-0019 не выполнялись и не входят в локальный verdict.
