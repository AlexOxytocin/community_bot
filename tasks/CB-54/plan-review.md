# CB-54 — финальный независимый recheck плана

Schema: `community_bot.plan_review.verdict.v1`

Status: approved

## Проверенные источники (`reviewed_sources`)

- Повторно полностью проверены актуальные `tasks/CB-54/plan.md` и
  `tasks/CB-54/plan-source-context.md` после единственного consolidated fix;
  предыдущий `changes_requested` verdict сопоставлен с каждым исправлением.
- Сверены канонические project/product/domain/architecture/process sources:
  `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`, `docs/mvp/README.md`,
  `01_PRODUCT_REQUIREMENTS.md`, `02_DOMAIN_RULES.md`, `TECH_STACK.md`, решения
  D-013, D-014, D-027, D-031, D-032, D-033, ADR-0014/0016/0017,
  `docs/release-2/README.md`, `PARITY_MATRIX.md`,
  `tasks/CB-64/parity-map.json`, `agents/plan-reviewer/instruction.md`,
  `agents/config.yaml` и `agents/workflow.yaml`.
- Повторно трассированы фактические owners:
  `AssignmentService.cards/card/_actor` в
  `src/community_bot/application/assignments.py:367`, `:392`, `:1146`;
  `list_assignment_cards/get_assignment_card/_cards` в
  `src/community_bot/infrastructure/db/assignments.py:130`, `:153`, `:185`;
  strict DB ordering/predicate в `:209-237`; `ActorContext`,
  `TaskService._active_context_actor`, `SqlAlchemyUnitOfWork.get_member` и
  текущий web DTO/error/cache boundary.
- `HEAD` и локальный `origin/main` остаются на
  `ea8550f4255fb69f7e90828d6b38454f6a743d80`; runtime CB-54 отсутствует.
  Live Jira read по-прежнему недоступен из-за
  `403: The app is not installed on this instance`; использованы переданный
  review packet и зафиксированный Jira snapshot, Jira не изменялась.
- Применены `ponytail` full и `ponytail-audit`; runtime, test, Jira, Git remote
  и Telegram не изменялись.

## Замечания по области (`scope_findings`)

Обязательных замечаний нет.

Выбранный read-only slice остаётся последовательным 20/80 результатом:
`CB-53 accept → Мои задания → Взятые мной → Активные → detail`. Он закрывает
первый тупик performer после accept, переиспользует существующие
performer-scoped projections и не притворяется полным UI всего движка.

Исходный широкий scope сохранён в capability map и последовательности later
slices. `withdraw`, submission drafts/results, creator/reviewer lifecycle,
group cancellation/replacement, disputes, admin/moderation, notifications и
deployment не удалены из roadmap. CB-53 `accept` не дублируется.

Предыдущее scope finding закрыто: detail owner после scoped projection явно
проверяет `card.assignment.status in ACTIVE_ASSIGNMENT_STATUSES`; terminal
owner, foreign, missing и test-run-invisible UUID получают одинаковые
`404 not_found`. История остаётся отдельным later slice по D-031.

## Замечания по дизайну (`design_findings`)

Обязательных замечаний нет.

- Actor gap закрывается минимально: existing assignment UoW protocol получает
  уже реализованный `get_member`, а actor-native list/detail следуют precedent
  `TaskService._active_context_actor`. Новая service class, identity adapter,
  repository, table, dependency или domain rule не создаётся.
- Pagination contract теперь однозначен: public `page_limit` равен `1..50`,
  actor-native owner вызывает DB projection с `page_limit+1`, transport выдаёт
  `rows[:page_limit]`, а `next_cursor` при extra row кодирует последнюю
  выданную `(accepted_at, assignment_id)`. Это согласовано со strict predicate
  `(order_at, id) < cursor` в текущем DB owner и не ломает `limit=50` старой
  проверкой application `cards`.
- Codec ограничен двумя локальными stdlib helpers, строго проверяет URL-safe
  encoding, UTC timestamp и UUID; malformed/partial input получает
  `422 invalid_request`. Generic pagination abstraction не вводится.
- Exact error contract закрыт: inactive/stale actor для list/detail получает
  `403 {"code":"assignment_unavailable"}` через существующий public error
  allowlist; невидимый detail остаётся отдельным одинаковым `404 not_found`.
- DTO — whitelist-only. Raw `input_payload`, `materials`, performer/creator/
  admin IDs, command/receipt IDs, private dispute comment/evidence и test-run
  internals закрыты; frontend не вычисляет permissions, settlement или
  `allowed_actions`.
- GET не требует operation identity и не затрагивает state, receipt, ledger,
  audit или outbox. Mutation receipt owner не подменяется транспортным glue.

Новый ADR не нужен: Mini App-only, native HTML/CSS/ES modules, internal actor,
PostgreSQL-authoritative state и feature slices уже приняты ADR-0016/0017.

Ponytail result: ladder останавливается на reuse existing owners. Skipped:
mutation bridge, history UI, endpoint framework, SDK, state manager, frontend
framework и generic cursor layer. `net: -0 lines, -0 deps possible` на
planning-only baseline.

## Замечания по проверке (`verification_findings`)

Обязательных замечаний нет.

Предыдущие verification findings закрыты одним bounded API scenario:

- equal-time assignments собираются через все страницы и сравниваются с exact
  ordered ID set без пропусков/дублей; проверяются terminal `next_cursor=null`
  и public `limit=50` boundary;
- terminal owner, foreign, missing и test-run-invisible direct UUID сравниваются
  по одинаковым status/body `404 not_found`;
- populated raw input/material/private case/evidence fixture проверяется exact
  list/detail key sets, а не поиском отдельных запрещённых строк;
- до и после успешных и denied GET сравниваются assignment/task state и counts
  receipts, account ledger, audit и outbox;
- inactive actor проверяется на exact
  `403 {"code":"assignment_unavailable"}`;
- restart assertion остаётся только если помещается в тот же scenario без
  fixture/abstraction; прямой zero-effect oracle имеет приоритет.

Browser oracle минимален и наблюдаем: list → detail → back плюс bounded
loading/empty/error/accessibility states. Route inventory переиспользуется из
CB-53, дублирующий router/test запрещён.

Baseline evidence предыдущего прохода остаётся валидным: все `7` тестов
`tests/unit/test_web_auth.py` прошли; non-zero был только следствием repo-wide
coverage gate узкого запуска (`28.86% < 80%`), не test failure. Текущий
`git diff --check` проходит.

## Обязательные исправления (`required_actions`)

Нет.

## Остаточные риски (`residual_risks`)

- CB-53 ещё не слита. Static paths, router/back/fetch helper и browser test
  file должны быть повторно сверены после merge; любой конфликт exact routes
  или route inventory остаётся plan-update stop condition.
- Live Jira state не подтверждён независимо из-за недоступного connector.
  Перед runtime обязательна запланированная повторная сверка CB-54/CB-53.
- HTTP mutation receipt owner на baseline отсутствует. Approval не разрешает
  `withdraw`, `submit` или другой POST и не разрешает domain-engine rewrite.
- Approval разрешает передать узкий план владельцу, но не запускает runtime.
  До реализации обязательны явное owner approval scope, merge CB-53 и её
  зелёные tests.
