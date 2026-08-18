# CB-73 — отчёт о реализации

## Итог

На ветке `task/CB-73` поверх exact baseline
`d1733cb49ff59a74e893320c19c15d58102b2045` реализован минимальный Mini App
slice проверки free-form результата создателем задания:

- список и detail только для submitted assignment собственных member-task;
- authoritative `FULL / PARTIAL / REJECT`, где `PARTIAL` выдаётся существующим
  `partial_reward`, а `REJECT` честно подтверждает 24h dispute window, frozen
  payout/reserve и отсутствие resubmission;
- одна decision mutation через существующий `AssignmentService.decide` без
  transport-side payout/status/permission rules;
- exact replay связывает immutable receipt с actor, assignment и decision,
  повторно проверяет active actor, ownership и test-run scope;
- после mutation UI перечитывает authoritative список; сетевой retry сохраняет
  тот же idempotency key.

## Критерии и доказательства

1. Privacy/ownership: API-test исключает foreign performer, community admin
   creator при отдельном reviewer и member-task вне test-run scope из list и
   прямого detail. Strict member-owned/freeform/submitted/test-scope predicate
   применяется существующим DB owner до `ORDER/LIMIT`; exact detail использует
   тот же query и не зависит от первых 50 broad community rows.
2. Safe projection: `_cards` отдаёт только строковый `result`/legacy `summary`;
   DTO не публикует raw payload, внутренние actor/provenance IDs или dispute.
   Browser-test доказывает literal render строки с `<script>`.
3. Decision eligibility: reward `>=2` даёт `full/partial/reject`, reward `1` —
   только `full/reject`; существующие assignment integration tests покрывают
   canonical FULL/PARTIAL effects.
4. REJECT/exactness: новый API-test доказывает `rejected_pending_dispute`, exact
   24h deadline, нулевой payout до финализации, same-key replay, conflict при
   другой decision, replay после `finalize_rejection`, fail-closed paused actor
   и отсутствие duplicate ledger/reliability/outbox effects.
5. UI: browser journey покрывает путь «Созданные мной», literal result, native
   confirm с честным текстом, network retry с тем же ключом, authoritative empty
   refresh, loading/error, disabled mutation, Back→focus и exact dialog text.

## Diff и архитектурные gates

- implementation/test: 8 файлов, `+553/-32`;
- approved amendment: `tasks/CB-73/ceiling-amendment-review.md`;
- 0 schema, migrations, models, repositories, services, frameworks,
  dependencies и domain-rule changes;
- существующие владельцы: `AssignmentService`, UoW, receipt, ledger,
  reliability, outbox, test-run scope, vanilla JS shell;
- dispute UI, history, resubmission и generic workflow renderer не добавлены.
- Ponytail-review: `Lean already. Ship.`; удаляемых speculative abstractions,
  dependencies или дублирующих владельцев не найдено.

## Проверки

- `uv run ruff format --check .` — 297 files formatted;
- `uv run ruff check .` — green;
- `uv run ty check src tests ops` — green;
- targeted integration + coverage — 24 passed; `assignments.py` 73%,
  `infrastructure/db/assignments.py` 69%, `web.py` 82%;
- `uv run pytest --no-cov -q tests/browser/test_mini_app.py` — 7 passed;
- `git diff --check origin/main` — green;
- high-confidence secret-like scan exact added runtime/test diff — clean;
- exact diff ceiling — `+553/-32`, 8 implementation/test файлов;
- exact CI node `test_web_config_and_route_set_are_closed` — 1 passed;
- Quality-equivalent: ruff format/check, ty, 421 non-integration/browser tests
  и 7 browser tests — green.

PR #81 открыт; повторный CI/merge/release/deploy выполняются после focused
independent re-review exact route-contract amendment.
