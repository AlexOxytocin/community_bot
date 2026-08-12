# Финальная проверка CB-31

Status: approved

## Проверенная область

- Свежая Jira `CB-31`, её пять критериев приёмки и связь с регрессией `CB-29` прочитаны напрямую через Atlassian Rovo API.
- Повторно проверены обязательные process docs, ADR-0004, актуальные `plan.md`, `test-plan.md`, `implementation-report.md` и полный staged diff.
- Проверен новый frozen staged tree `730896f4a59a7ce65056ab9dfcd8bffb6d356d22` в ветке `task/CB-31`.
- Особо перепроверено закрытие M-001: repair entrypoint не принимает приватные options, а Telegram ID и display name читает двумя строками из stdin; runbook передаёт stdin через `docker compose run --rm -T`.

## Критические замечания

Нет.

## Существенные замечания

Нет. M-001 первого review закрыт.

## Незначительные замечания

Нет.

## Матрица критериев приёмки

| Критерий Jira | Результат | Доказательство |
|---|---|---|
| UTF-8-safe ввод и хранение имени | пройден | Stdin принимает русское имя, domain normalizer приводит пробелы к каноническому виду, PostgreSQL сохраняет Unicode без искажения. |
| Детерминированный first-admin onboarding | пройден | Bootstrap сохраняет `Administrator`, `UTC`, пустые optional fields, фиксированные permissions и нулевые ledger/cache значения. |
| Idempotent repair существующего bootstrap administrator | пройден | Gate требует ровно одного active administrator, совпадающий Telegram ID и bootstrap provenance; повтор того же имени — no-op без второго audit. |
| Production-composed card/members/leaderboard | пройден | Реальный Dispatcher и fake Bot показывают исправленное имя во всех трёх представлениях. |
| Приватные данные не попадают в Jira/логи | пройден | Значения отсутствуют в process argv/Sentry `ArgvIntegration`, runtime log и audit payload; rejected CLI не отражает stdin. |

Итог: `5/5`.

## Матрица проверок

- Consolidated targeted gate: `16 passed` — `11` PostgreSQL initial-admin/Dispatcher сценариев и `5` observability/privacy тестов; без skip/deselect.
- Подтверждены conflicts для другого ID, отсутствующего provenance и нескольких active administrators.
- Подтверждены fault rollback после flush audit и успешный retry.
- Подтверждено, что repair изменяет только `display_name`; роль, статус, permissions, timezone, optional profile fields и ledger/cache не перезаписываются.
- Фактический rejected entrypoint со stdin private values: exit code `2`, `PRIVATE_VISIBLE=False`.
- `uv build`, bootstrap/repair entrypoint help: успешно.
- `ruff format --check .`: успешно, `362 files already formatted`.
- `ruff check .`: успешно.
- `ty check`: успешно.
- `git diff --cached --check`: успешно.
- Полная регрессия намеренно не запускалась; она остаётся в области `CB-29`.

## Безопасность и секреты

- В staged diff не найдено статических секретов, токенов или приватных ключей.
- Audit repair хранит только внутренний member UUID, boolean marker и allowlisted reason.
- Private values поступают через stdin, не становятся process arguments и не включаются default `ArgvIntegration`.
- Runtime success/reject/failure logs содержат только allowlisted event/outcome без пользовательского ввода.

## Процесс и область

- Уровень процесса: 2 по ADR-0004; отдельный repair entrypoint не меняет архитектурную форму и не требует ADR.
- Ветка соответствует `task/CB-31`; staged tree перед verdict не изменялся.
- Несвязанных изменений, ослабления проверок и runtime-идентификаторов с ключом Jira не найдено.
- Jira, Git remote, index, production и Telegram не изменялись.

## Обязательные действия

Нет.

## Остаточные риски

- Значения stdin остаются чувствительными операторскими данными: их нельзя помещать в shell tracing или внешние wrapper-логи. Канонический runbook использует pipe и не включает значения в command argv.
- Общая регрессия пакета CB-30…CB-33 остаётся отдельным gate `CB-29` и не входит в этот review.
