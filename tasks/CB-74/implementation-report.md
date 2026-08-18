# CB-74 — отчёт о реализации

## Итог

На ветке `task/CB-74` поверх exact baseline
`95b0da6917c0ba41770be700e12195d50f21a34b` реализован минимальный performer
path подачи спора после `REJECT`:

- detail назначения сообщает только server-owned `can_dispute`, текущий status,
  deadline и safe case state;
- один `POST /api/v1/assignments/{assignment_id}/disputes` передаёт
  нормализованный private comment существующему `AssignmentService.dispute()`;
- web actor сериализуется existing identity gate до первого receipt read;
  exact replay связывает actor, assignment и fingerprint комментария;
- перед replay и mutation повторно проверяются active actor, performer ownership
  и текущий test-run scope;
- UI показывает условия и deadline, требует один явный confirm и после mutation
  перечитывает authoritative detail.

## Критерии и доказательства

1. Ownership/privacy: foreign и test-run-hidden mutations дают единый
   `409 assignment_unavailable`; чужой detail сохраняет существующий `404`.
   Private comment отсутствует в response, detail и outbox payload.
2. Eligibility: `can_dispute` вызывает существующий
   `require_dispute_allowed()`; web/JS не сравнивают 24h deadline. Boundary
   `now == reject_dispute_deadline_at`, уже открытый спор и terminal state
   закрыты без эффектов.
3. Exactness: два одновременных одинаковых POST дают `204/204`; одинаковый key
   с разными comments даёт `204/409`. Итоговые дельты: два успешных opening —
   ровно два dispute, два case, два outbox и два receipt; ledger, reliability и
   audit при opening не меняются.
4. Scope replay: после смены active test-run scope stored replay возвращает
   `409` и не создаёт новых эффектов.
5. Input/UI: missing, empty и whitespace-only comment дают `422` без receipt;
   browser journey покрывает eligible → confirm → `DISPUTED`, expired,
   already-open и существующий terminal `404/not active`.
6. Downstream lifecycle: existing dispute → moderation resolution test теперь
   проверяет ровно один audit `moderation_case_resolved` с точными entity type,
   entity id и actor; replay не дублирует его.

## Diff и архитектурные gates

- runtime + tests: 7 файлов, `+360/-12` при ceiling `+400/-40`;
- покомпонентные ceilings соблюдены;
- 0 новых dependencies, migrations, tables, models, repositories, services,
  frameworks, domain rules и ADR;
- переиспользованы dispute owner, UoW locks, receipt/outbox, test-run scope,
  performer detail, bounded JSON/idempotency helpers и vanilla JS form styles;
- Ponytail-review: `Lean already. Ship.`

## Проверки

- `uv run ruff format --check .` — green, 300 files;
- `uv run ruff check .` — green;
- `uv run ty check src tests ops` — green;
- targeted contract matrix — `24 passed`;
- полные затронутые integration/core/browser файлы — `21 passed`;
- полная локальная матрица `uv run pytest` — `580 passed`, coverage `82.79%`;
- `git diff --check origin/main` — green;
- high-confidence secret-like scan added `src/tests/tasks` lines — `0` matches;
- task branch и exact baseline — green.

Автоматические API/PostgreSQL/browser проверки полностью покрывают обязательный
ручной сценарий до deployment, поэтому отдельный `test-plan.md` не требуется.
PR, CI, merge, immutable release, production activation и public smoke ещё не
выполнены и остаются delivery gates этой задачи.
