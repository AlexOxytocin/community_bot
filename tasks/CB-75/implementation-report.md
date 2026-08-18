# CB-75 — отчёт о реализации

## Результат

Реализован узкий Mini App lifecycle initial dispute resolution:

```text
active moderator/administrator → scoped queue → safe dispute detail
→ server-owned codes → preview → explicit confirm → existing resolution engine
```

Новых domain outcomes, schema, migration, dependency, service, repository,
framework или frontend layer нет. Web остаётся allowlisted проекцией и вызывает
существующий `ModerationService.resolve` / `ResolveCaseCommand`.

## Фактические изменения

- Existing moderation application contract получил actor-native detail и web
  receipt replay. Internal actor проверяется до receipt lookup; identity gate,
  case-scoped update ID и canonical payload fingerprint обеспечивают exact
  replay и same-case payload conflict.
- Existing PostgreSQL moderation owner применяет active test-run scope и тот же
  conflict-of-interest owner к queue/detail/replay/mutation. Detail доступна
  только для `case_type=dispute`, `status=open`; web-команда дополнительно
  fail-closed запрещает fraud review и appeal.
- `allowed_resolution_codes` строятся server-side из текущего `ResolutionCode`,
  `resolution_effect`, task origin и роли. Moderator не получает `fraud`;
  member/community applicability не перенесена в transport или JavaScript.
- Safe `result_summary` переиспользует существующую CB-73 assignment-card
  projection. Raw result payload, evidence, IDs участников, receipt, ledger,
  audit и outbox internals в DTO не попадают.
- Добавлены ровно два route:
  `GET /api/v1/moderation/cases/{case_id}` и
  `POST /api/v1/moderation/cases/{case_id}/resolution`.
- Existing native `app.js` queue стала интерактивной только для initial dispute:
  detail, reason, preview, explicit confirm, stable retry key, 409 state,
  keyboard/focus/back. Fraud/appeal cards остаются неактивными.
- Existing `moderation_case` outbox recipient branch пересекает test-run
  получателей с текущими active `participant_ids`.

## Доказательства критериев

| Критерий | Доказательство |
|---|---|
| active moderator/admin authority | queue/detail заново загружают internal member и требуют active staff; integration negative checks member/paused/restricted/out-of-scope |
| conflict-of-interest и privacy | один storage owner `_reject_conflict` используется list/detail/replay/mutation; direct detail fail-closed `404`; allowlist и malicious/private payload assertions green |
| member/community resolution codes | существующая domain matrix остаётся единственным owner; detail фильтрует её по origin/role, domain matrix tests green |
| один initial dispute action | detail и mutation принимают только `dispute/open`; fraud web mutation negative oracle green; appeal/fraud UI не добавлены |
| receipt exact replay/conflict | same key + same payload дважды даёт `204` и один receipt/effect; same key + другой payload и новый key + stale revision дают `409` |
| test-run isolation | same active run detail/resolve green; staff вне run получает `404`; normal queue отделена от active run |
| ledger/reliability/audit/outbox | existing engine применяет partial outcome; counts для resolution, reliability, outbox и receipt остаются по одному; existing rollback/concurrency/economy suite green |
| outbox privacy | active performer получает notification, active member с inactive run participation исключён; payload остаётся existing privacy-minimal |
| UI gate | browser проверяет loading/detail, XSS-safe text, keyboard submit, explicit confirm focus, 502 retry с тем же key, 409, back и focus restore |
| closed route set | exact inventory test содержит только два новых route |

## Проверки

- `uv run ruff format --check .` — green, 306 files formatted.
- `uv run ruff check .` — green.
- `uv run ty check src tests ops` — green.
- `node --check src/community_bot/transport/static/app.js` — green.
- Targeted PostgreSQL moderation/web/notifications suite — 30 passed.
- Targeted CB-75 web API — 2 passed.
- Targeted CB-75 browser — 1 passed.
- Full non-browser suite with PostgreSQL and coverage — 574 passed,
  7 deselected, coverage 82.64% (required 80%).
- Full browser suite — 7 passed.
- `git diff --check` — green.

## Ponytail full и residual risk

Source ceiling соблюдён: пять existing production owners и три existing test
owners; дополнительное изменение test helper только передаёт уже существующий
`test_run_id`. Структурных изменений и ADR нет.

Локальная реализация и проверки завершены. До terminal delivery остаются
independent `final-review.md`, commit/push/PR/CI/merge, новый immutable release,
production activation, public smoke и только затем Jira `Готово`.
