# CB-53 — независимый owner-authorized recheck полного плана

Schema: `community_bot.plan_review.verdict.v1`

## Статус (`status`)

План одобрен для реализации от зафиксированного baseline
`origin/main@ea8550f4255fb69f7e90828d6b38454f6a743d80`. Обязательных исправлений,
непрочитанных источников или незакрытых architecture/security gates не осталось.

## Проверенные источники (`reviewed_sources`)

- Полностью прочитаны `agents/plan-reviewer/instruction.md`, глобальная
  `codex.agent-budget.v1`, канонические project/Jira workflow rules,
  product/domain/technology/decision/release документы, ADR-0006/0007 и
  ADR-0014/0016/0017.
- Прочитаны CB-58 `DESIGN.md`, `design-tokens.json` и релевантные свойства
  preview; применён независимый `ponytail-review` complexity gate.
- Через Atlassian Rovo/JQL прочитана фактическая `CB-53`: status
  `К выполнению`, parent `CB-48`, исходное описание, links и все комментарии
  `10239`—`10243`. `CB-52` и `CB-58` фактически `Готово`; Jira не менялась.
- Полностью прочитаны актуальные `tasks/CB-53/plan.md`,
  `plan-source-context.md`, `problem-escalation.md` и предыдущая terminal
  review history.
- Baseline проверен через `git show`/`git grep` именно на `origin/main@ea8550f`:
  `transport/web.py`, `application/identity.py`,
  `application/assignments.py`, `application/member_foundation.py`,
  `application/tasks.py`, assignment/task/receipt DB adapters, models и
  соответствующие integration/web tests. Рабочий `HEAD@4b05030` не принимался
  за runtime baseline.
- Секретов, tokens, cookies, session values или приватных Telegram-данных в
  plan package не обнаружено.

## Замечания по области (`scope_findings`)

Область замкнута и соответствует последнему owner decision:

- один путь `catalog → in-memory detail → accept → confirmed`;
- существующий catalog GET расширяется только пятью allowlisted полями;
- добавляется ровно один POST accept; GET detail, deep-link/reload detail,
  новый owner/repository/table/migration/framework отсутствуют;
- profiles, registration writes, reputation/karma/history, member directory,
  moderation/admin и CB-54/CB-55 behavior исключены;
- native HTML/CSS/ES modules и существующие CB-58 tokens/assets используются
  без React/Vite/Node и без runtime dependency;
- hard gate `business/domain logic = 0 files / 0 LOC` проверяем; files/LOC/test
  counts остаются soft trigger одного короткого аудита, а не acceptance ceiling.

Ponytail verdict: `Lean already. Ship.` Length-prefix encoding, stdlib SHA-256,
existing locks/unique row и native DOM являются минимальными primitives; новая
абстракция для них не планируется.

## Замечания по дизайну (`design_findings`)

### Operation identity и replay — approved

Baseline подтверждает исходную опасность: `processed_telegram_updates.update_id`
является global primary key, а `AssignmentService._begin()` читает receipt до
actor authority. Исправленный контракт в `plan.md:113-167` закрывает её:

- raw browser key не передаётся owner;
- tuple `accept + internal member UUID bytes + task UUID bytes + canonical key`
  имеет отдельный unsigned two-byte length prefix для каждого поля;
- SHA-256 truncation даёт только positive signed 63-bit `update_id`, без
  secret/config/table/codec class;
- после `_begin/_assignment_replay` возврат разрешён только при exact
  `assignment.performer_id == ActorContext.member_id` и
  `assignment.task_id == command.task_id`.

Безопасность не зависит от предположения об отсутствии hash collision:
forced collision с другим actor/task/outcome заканчивается единым 409 до DTO и
без write effects. Collision с тем же actor/task указывает на тот же natural
resource, для которого owner отдельно разрешил существующий success. Namespace
и task включены в digest, поэтому прежний детерминированный same-key/different-
task replay устранён.

Receipt-first порядок сохранён: identity-matched committed replay происходит до
mutable member/task eligibility и потому не превращается в новый отказ после
смены actor status. При этом session proof всё равно проверяется transport-слоем
до key/owner call.

### Natural idempotency и concurrency — approved

Baseline содержит `uq_assignments_task_performer`, member active-limit gate,
task assignment gate и `list_task_assignments(..., for_update=True)`. План не
перехватывает broad `IntegrityError` и не разбирает constraint text. Вместо
этого он использует существующий natural resource под теми же authoritative
actor/moderation/test/task gates:

- active status из существующего `ACTIVE_ASSIGNMENT_STATUSES` возвращает ту же
  safe assignment без нового receipt/audit/outbox/reliability/ledger effect;
- terminal/cancelled row даёт общий 409 и никогда не реанимируется;
- member gate остаётся раньше task gate, поэтому same actor across tasks и
  same task across actors сохраняют текущий lock order;
- same/different key races после сериализации видят максимум одну assignment и
  один initial accepted effect; unique constraint остаётся backstop, а не
  normal-flow exception.

Это делает явным уже существующее DB identity и не меняет slot/status/economy
правила. Первый accept сохраняет existing create/reliability/outbox/receipt
семантику и добавляет только принятый allowlisted audit marker в ту же UoW.

### Privacy/error/DTO — approved

- Expected owner visibility/business/permission rejections после wire gates
  схлопываются в один `409 assignment_unavailable`; route не копирует predicates,
  не парсит exception text и не раскрывает 403/404 distinctions.
- Unexpected infrastructure faults остаются generic 500/no-store с rollback.
- Persisted `public_input_keys` принимается только как целый корректный
  list/tuple строк; отсутствующий, неверного типа или содержащий non-string
  allowlist даёт empty projection. Для корректного allowlist наружу выходит
  только intersection с `input_payload`; historical raw-payload fallback из
  baseline должен исчезнуть в mechanical persistence/DTO projection.
- `materials.text` и `materials.url` остаются domain-validated literal text;
  catalog data не становится `href`, `src`, event attribute или HTML.

### Transport precedence — approved

`plan.md:87-111` задаёт исполнимый порядок без опережающей FastAPI validation:

1. raw single exact Origin;
2. merged CB-52 session resolver/`ActorContext`;
3. raw single canonical `Idempotency-Key`;
4. manual UUID и empty-body validation;
5. единственный `accept_with_task` call.

Отдельные отрицательные cross-cases фиксируют exact status/code и отсутствие
owner/UoW effects. Canonical key grammar полностью закрыта: decimal ASCII
`1..9223372036854775807`, без sign, leading zero, whitespace, comma joining,
overflow или duplicate header.

## Замечания по проверке (`verification_findings`)

План содержит достаточные отдельные risk oracles:

- DTO HTTP privacy cases для missing/non-list/non-string allowlist и private
  payload;
- fixed operation-ID vectors, forced collision, cross-actor, cross-task и
  отсутствие member/key/derived ID в response/log;
- exact replay после actor status change;
- same-key и different-key PostgreSQL concurrency, one assignment/one effect,
  existing active success, terminal 409 и отсутствие normal-flow
  `IntegrityError/500`;
- full rollback для expected и unexpected faults;
- Origin/session/key/UUID/body precedence с zero-effect counters;
- один browser path с malicious catalog data, literal rendering, отсутствием
  `script/img/a`, event handlers, dynamic URL attributes, navigation/network и
  execution;
- machine gates: empty domain diff, unchanged migration/table inventory, one
  new POST/no detail GET, no forbidden dependency/framework, targeted
  PostgreSQL/browser/full suite и один soft-budget audit.

Browser mock не подменяет backend proof: Secure HttpOnly session, authorization,
receipt and transaction semantics отдельно проверяются real HTTP/PostgreSQL
integration tests.

## Обязательные действия (`required_actions`)

Обязательных исправлений плана нет. Реализация должна буквально сохранить
указанные hard gates и tests; отклонение от operation tuple, replay actor/task
check, fail-closed persisted allowlist или existing lock order делает этот
verdict неприменимым и требует новой проверки фактического diff.

## Остаточные риски (`residual_risks`)

- Реализация ещё не проверена: особенно важны real PostgreSQL race tests и
  forced receipt-collision fixture.
- Soft target может быть превышен только с одним коротким audit/rationale;
  превышение само по себе не является defect при зелёных hard invariants.
- Jira description сохраняет исторически широкий scope, но более поздние
  owner comments `10239` и `10243` однозначно сужают этот slice. Runtime не
  должен возвращать исключённый profiles/reputation/CB-54 behavior.
- Одобрение плана открывает только branch/runtime phase; merge и Jira `Готово`
  требуют targeted/browser/PostgreSQL checks, implementation report,
  independent final review, CI и PR route.

Status: approved
