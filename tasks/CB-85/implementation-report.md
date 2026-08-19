# CB-85 — отчёт о реализации

## Результат

- `AssignmentCard` проецирует `can_submit` через существующую `require_submit_allowed` и `can_cancel` через ту же проверку, которую вызывает `AssignmentService.cancel`.
- `AssignmentDetailDto` передаёт только эти bounded capabilities; privacy, ownership, test-run scope и lifecycle остаются в application/domain owners.
- Mini App показывает submission/cancel только по server projection и больше не использует status allowlist для eligibility.
- Task creation удерживает один и тот же key и exact body после network/`5xx`/неопределённого ответа; accept удерживает отдельный key, привязанный к `task.id`, по тем же правилам. Success и definite nonretryable response очищают соответствующую operation identity.
- После успешного accept клиент заново читает authoritative assignment detail.

## Границы diff

Production изменён только в:

1. `src/community_bot/application/assignments.py`;
2. `src/community_bot/transport/web.py`;
3. `src/community_bot/transport/static/app.js`.

Новых domain rules, service/repository/persistence/schema/migration/model/dependency/framework/CSS нет. Moderation, terminal history, templates и community flow не расширялись.

## Оракулы

| Оракул | Доказательство |
| --- | --- |
| `accepted` после deadline не получает submit capability | Integration test создаёт accepted assignment с истёкшим deadline и получает `can_submit=false` |
| Eligible freeform card получает server actions | Integration test получает `can_submit=true`, `can_cancel=true` |
| Клиент не вычисляет eligibility по status | Static browser oracle запрещает accepted status allowlist и требует `can_submit`/`can_cancel` |
| Task creation повторяет exact command | Browser test: `503` повторяет тот же key/body; `409` очищает key и следующий вызов получает новый |
| Accept повторяет exact key | Browser test: после `503` accept другой карточки получает другой key, а возврат к первой повторяет исходный key; success делает authoritative reread detail |
| Existing flows сохранены | Полный browser suite и unit/non-integration suite зелёные; существующие server replay/conflict проверки остаются в suite |

## Проверки

- `uv run ruff format --check .` — green, `334 files already formatted`.
- `uv run ruff check .` — green.
- `uv run ty check src tests ops` — green.
- `uv run pytest --no-cov -q tests/browser` — `10 passed`.
- `uv run pytest --no-cov -q tests/integration/test_web_api.py -k 'catalog_detail_projection_accept_and_cancel_path or web_submission_draft_is_bounded_exact_and_template_closed' --maxfail=1` — `2 passed, 12 deselected`.
- `uv run pytest -m "not integration and not browser" --no-cov -q` — `421 passed, 169 deselected`.
- `git diff --check` — green.
- Diff secret-pattern scan — совпадений нет.

## Ponytail

`Lean already. Ship.` Существующие validation owner, DTO и submission response parser переиспользованы; accept keys удерживаются нативным `Map` по `task.id`, новый общий state manager или abstraction не нужен.

## Остаточный риск

Низкий: capability зависит от серверного времени на момент чтения карточки, а окончательная mutation всё равно повторно проходит authoritative validation. Exact retry ограничен жизнью открытой страницы, как и существующий client operation state.
