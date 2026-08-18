# CB-73 — независимое финальное ревью

Schema: `community_bot.final_review.verdict.v1`

Status: approved

## Проверенная область и уровень

Уровень процесса: `2` с усиленными privacy и idempotency gates. Проверены live
Jira CB-73, owner resolution второго ceiling gate, ветка `task/CB-73`, exact
baseline и `origin/main` `d1733cb49ff59a74e893320c19c15d58102b2045`,
актуальные plan/problem-escalation/amendment/implementation artifacts и полный
implementation/test diff.

Критических, существенных и обязательных незначительных замечаний нет. Оба
findings предыдущего final review закрыты.

## Focused amendment после CI route-contract blocker

Предыдущее approval остаётся валидным для того же runtime hash. Git blob hashes
пяти runtime файлов и двух ранее reviewed integration/browser файлов в текущем
worktree точно совпадают одновременно с `a5b986c` и `327ab27`; сравнение
текущего `src` с `a5b986c` не содержит изменений.

Единственный новый implementation/test delta после `a5b986c` — три строки в
`tests/unit/test_web_auth.py`: exact tuples для GET list, GET detail и POST
decision. Они добавлены в существующий literal route set. Wildcard, helper,
новая abstraction, новый test file и ослабление `assert routes == {...}` не
появились.

Exact ранее failing node независимо проходит: `1 passed`. Полный эквивалент
job `Quality` также зелёный: format/lint/type, `421 passed` non-integration/
browser и `7 passed` browser. Поэтому amendment закрывает только authoritative
route oracle и не меняет прежний runtime/privacy/replay verdict.

## Закрытие предыдущих findings

### Pre-limit ownership и exact detail

Existing `list_review_cards` получил только два явных параметра текущего seam:
`member_owned` и `assignment_id`. Для Mini App query теперь применяет до
`ORDER/LIMIT`:

- `TaskModel.creator_id == actor_id`;
- `TaskModel.template_id IS NULL`;
- assignment status `submitted`;
- существующий active test-run predicate `_cards`.

Detail передаёт exact `assignment_id` в тот же query и больше не ищет assignment
в ограниченной broad community page. Integration oracle создаёт 51
дополнительную более новую community task, но member-owned list и exact detail
остаются доступны; community и чужой test-run по-прежнему дают `404`.

Изменение прошло через существующие `AssignmentUnitOfWork`,
`SqlAlchemyUnitOfWork` и assignment store. Нового repository/service/layer или
transport-side ownership rule нет.

### Negative HTTP и browser contract

Integration test теперь отдельно доказывает foreign list, foreign detail,
inactive list/detail, community-review isolation и test-run isolation. Browser
journey выполняет `Назад`, проверяет возврат фокуса на исходную review-card и
сверяет exact native REJECT dialog: 24 часа, frozen payout/reserve и отсутствие
resubmission. Literal render, `aria-live`, disabled mutation, network retry с
тем же key и authoritative refresh сохранены.

## Матрица приёмки

- Creator list/detail: strict member-owned, free-form, submitted и active
  test-scope boundary подтверждён кодом и displacement oracle.
- Privacy: foreign, inactive, community creator/reviewer и чужой test-run не
  получают result/private fields через list или direct detail.
- Projection: DTO содержит только безопасные display/time/result fields; raw
  payload и внутренние provenance/dispute поля не публикуются; result выводится
  literal text.
- Decisions: `FULL / PARTIAL / REJECT` проходят через существующий
  `AssignmentService.decide`; reward `1` исключает `PARTIAL`, reward `>=2`
  включает его через canonical `partial_reward`.
- REJECT: `rejected_pending_dispute`, exact 24h deadline и отсутствие payout до
  финализации подтверждены; UI не обещает доработку или повторную submission.
- Exact replay: same-key/same-decision, different-decision conflict,
  post-finalization replay и paused-actor fail-closed подтверждены; duplicate
  ledger/reliability/outbox effects не возникают.
- UI: error/retry/loading/accessibility, Back→focus, exact confirm и
  authoritative post-mutation refresh подтверждены browser test.

## Актуальные owner amendments и Ponytail

Фактический implementation/test diff относительно exact baseline содержит
ровно 8 файлов, `+553/-32`:

- `application/assignments.py`: `+73/-15`;
- DB `assignments.py`: `+24/-8`;
- existing UoW forwarder `database.py`: `+13/-2`;
- `static/app.js`: `+119/-2`;
- `web.py`: `+95/-3`;
- browser test: `+51/-1`;
- integration test: `+175/-1`;
- exact route-contract unit test: `+3/-0`.

Текущий owner absolute ceiling `560` соблюдён при фактических 553 additions.
Превышение прежнего 500-line stop ограничено исправлением
pre-limit/exact-detail contract и недостающими
displacement/foreign/inactive/Back-focus/dialog oracles. Седьмой файл — только
существующий UoW forwarder, необходимый для передачи strict query parameters
текущему DB owner. Восьмой файл содержит только три exact route tuples,
потребованные закрытым CI assertion.

Новых table, schema, migration, model, repository abstraction, service,
framework, dependency или domain rule нет. Дублирующего ownership, payout,
status, test-run либо receipt owner не добавлено.

Ponytail review: `Lean already. Ship.` Reuse/delete-first исчерпан; дальнейшее
сокращение затронуло бы query correctness, обязательные privacy/UI oracles или
читаемость тестов.

## Независимо повторённые проверки

- `uv run ruff format --check .` — green, 297 files;
- `uv run ruff check .` — green;
- `uv run ty check src tests ops` — green;
- targeted PostgreSQL/API + coverage — `24 passed`;
  `assignments.py` 73%, DB `assignments.py` 69%, `web.py` 82%;
- `uv run pytest --no-cov -q tests/browser/test_mini_app.py` — `7 passed`;
- exact node `test_web_config_and_route_set_are_closed` — `1 passed`;
- Quality-equivalent non-integration/browser suite — `421 passed`, 158
  deselected; полный browser suite — `7 passed`;
- `git diff --check d1733cb49ff59a74e893320c19c15d58102b2045` — green;
- high-confidence secret-like scan добавленных runtime/test строк — `0`
  совпадений;
- branch/baseline/diff ceiling — green.

## Security, workflow и остаточные риски

Секретов, Telegram session data, неразрешённых внешних действий и несвязанных
runtime changes не обнаружено. Смысловые task-артефакты на русском; branch и
baseline корректны.

Этот focused verdict подтверждает локальную готовность amendment к повторному
CI PR #81; remote rerun/merge ещё не проверялись. После merge runtime-задача
обязана пройти новый exact immutable release, production activation и public
smoke по ADR-0019; Jira `Done` до green public smoke запрещён.
