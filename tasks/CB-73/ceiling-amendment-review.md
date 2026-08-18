# CB-73 — независимая проверка изменения diff ceiling

Schema: `community_bot.ceiling_amendment_review.verdict.v1`

Status: approved

## Итог recheck

Оба обязательных замечания первого amendment review закрыты. Existing receipt
outcome теперь неизменно связывает web actor, assignment и decision строкой
`web_assignment:<actor_id>:<assignment_id>:<decision>`. Update identity
по-прежнему включает actor, assignment, operation и внешний
`Idempotency-Key`; новый persistence owner или schema change не появились.

Replay path сначала повторно разрешает active actor через `_command_actor`,
сверяет immutable receipt outcome, затем проверяет member ownership и active
test-run scope через `_ensure_web_decision_access`. Поэтому paused/banned actor
с ещё действующей web session fail-closed, foreign actor и чужой test-run не
получают replay outcome.

PostgreSQL/API oracle теперь доказывает полный жизненный цикл:

- первый `REJECT` возвращает `204` и создаёт
  `rejected_pending_dispute` с exact 24-hour deadline;
- same-key/same-decision replay сразу возвращает `204`, а same-key/different-
  decision — `409`;
- после штатного `finalize_rejection`, который меняет mutable assignment
  terminal state, исходный same-key `REJECT` всё равно возвращает exact `204`
  по immutable receipt;
- после перевода creator в `paused` тот же replay возвращает `409` без эффекта;
- member/community/test-run privacy, PARTIAL eligibility и отсутствие
  duplicate ledger/reliability/outbox effects сохраняются.

## Утверждённый amended ceiling

Относительно `origin/main` =
`d1733cb49ff59a74e893320c19c15d58102b2045` фактический implementation/test
diff содержит ровно 6 файлов, 499 добавлений и 22 удаления:

- `src/community_bot/application/assignments.py`: `+67/-14`;
- `src/community_bot/infrastructure/db/assignments.py`: `+4/-2`;
- `src/community_bot/transport/static/app.js`: `+119/-2`;
- `src/community_bot/transport/web.py`: `+96/-3`;
- `tests/browser/test_mini_app.py`: `+42/-0`;
- `tests/integration/test_web_api.py`: `+171/-1`.

Amended ceiling CB-73 утверждён как фактические `<=499` добавлений,
`<=22` удалений и `<=6` implementation/test файлов. Абсолютный owner stop
остаётся `500` добавлений; любая 500-я строка требует сохранения тех же условий,
а превышение 500 или седьмой файл немедленно останавливает реализацию.

Новых layer, table, migration, schema, model, repository, service, framework,
dependency или domain rule нет. 49 строк сверх исходных 450 ограничены
required UI/accessibility/error/focus states, полезным DTO contract, читаемыми
privacy/replay/PARTIAL/REJECT oracles и correction immutable replay.

Ponytail verdict: `Lean already. Ship.` Reuse/delete-first исчерпан; дальнейшее
сокращение ухудшает acceptance coverage, accessibility либо читаемость
критических privacy/replay доказательств.

## Валидация и остаточная неопределённость

Проверены live Jira CB-73, актуальные plan/review, amendment ledger и полный
uncommitted diff. `git diff --check origin/main` проходит. В рамках этого
read-only amendment review runtime/tests/Jira/Git/remotes не изменялись и тесты
не запускались.

Approval относится к изменению ceiling и закрытию двух предыдущих findings.
Фактические результаты planned checks, coverage, CI и отсутствие иных runtime
дефектов должны быть подтверждены implementation report и независимым final
review до commit/push/PR/merge/delivery.
