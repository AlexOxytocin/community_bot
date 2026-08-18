# CB-53 — план первого проверяемого Mini App path

## Результат и gate

Реализовать один vertical slice:

`Mini App → существующая CB-52 session → каталог → карточка из catalog item → принять → подтверждённое accepted-состояние`.

Уровень процесса — `3`: первая web mutation с authorization, replay,
concurrency, privacy и browser security boundary. `CB-52` merged в
`main@ea8550f4255fb69f7e90828d6b38454f6a743d80` (PR `#65`, CI green,
Jira `Done`). Runtime разрешён только после одного независимого
post-escalation recheck этого полного пакета с последней строкой
`Status: approved`.

Решения владельца от 2026-08-17:

- разрешено расширить существующие `TaskDto`/`_task_dto` пятью полями;
- разрешён один `POST /api/v1/tasks/{task_id}/assignments` как adapter к
  существующему `AssignmentService.accept_with_task`;
- все ожидаемые owner rejections после transport/auth gates → один
  privacy-safe `409 assignment_unavailable`;
- materials всегда literal text, внешние ссылки отсутствуют;
- `Idempotency-Key` имеет canonical positive int64 grammar;
- global legacy receipt требует command/actor/task-bound 63-bit derivation и
  replay identity verification: raw client key owner не получает;
- unique assignment `(task_id, performer_id)` является natural idempotency
  resource: active row возвращается без новых effects, terminal/cancelled не
  реанимируется.

## Hard gate: zero domain-engine rewrite

Каждый production diff классифицируется:

1. `web/auth/session/DTO glue`: transport validation, DTO/static UI,
   operation-id derivation и response mapping;
2. `mechanical existing-owner adaptation`: передача `ActorContext`,
   сохранение receipt-first порядка, existing audit primitive;
3. `business/domain logic`: новые правила, состояния, разрешения, visibility,
   лимиты, формулы или domain outcomes.

Категория 3 — hard **`0 files / 0 LOC`**. `src/community_bot/domain/**` не
меняется. Transport/JS не повторяют правила tasks, profiles, karma, levels,
leaderboard, reliability, templates, disputes, appeals, sanctions, alerts или
config. Новый backend service/repository/framework/command bus/UoW запрещён.
Отсутствующая owner capability означает gap и остановку.

## Закрытый scope

In scope:

1. Native HTML/CSS/ES modules shell: bootstrap, catalog, in-memory detail,
   back/history, pending/error/confirmed states.
2. Existing `GET /api/v1/tasks`: добавить в существующие DTO mapper только
   `description`, `completion_criteria`, `performer_instructions`,
   `materials`, `public_input`.
3. `public_input` — только пересечение корректного persisted allowlist и
   `task.input_payload`. Mapper принимает лишь `list`/`tuple` только из
   strings; missing/malformed/non-string allowlist даёт empty projection. Raw
   payload/key list и unknown/private keys не выходят.
4. Ровно один новый POST accept и existing authoritative owner.
5. CB-58 tokens/assets, local Manrope, focus, safe areas, reduced motion,
   contrast и atomic Telegram palette fallback.

Out of scope:

- `GET /api/v1/tasks/{task_id}`, deep-link/reload detail и новый detail owner;
- registration/profile writes, karma/reputation/history, member directory,
  moderation/admin, completion/review/disputes/appeals/sanctions/alerts;
- search/filter/saved catalog и optimistic accept;
- external clickable materials и catalog-driven navigation;
- React/Vite/Node, router/store/API/component frameworks, generated SDK;
- новые table/migration/repository/service.

Карточка использует только selected allowlisted catalog item в памяти. Detail
endpoint возможен позже лишь при отдельной UX-потребности и owner decision.

## Exact API delta

### Catalog DTO

`GET /api/v1/tasks` сохраняет CB-52 envelope/pagination. `materials` —
closed object с optional string `text`/`url`; оба значения UI показывает как
обычный текст. DTO не сериализует raw `input_payload`,
`public_input_keys` или лишние material keys.

### Accept gates и precedence

`POST /api/v1/tasks/{task_id}/assignments` не принимает business JSON.
Route/dependencies обеспечивают порядок, который framework validation не может
обогнать:

1. **Origin:** raw list header values должен содержать ровно одно значение,
   byte-for-byte равное configured HTTPS `mini_app_origin`. Missing/wrong/
   duplicate → `403 {"code":"invalid_origin"}`; session/owner/UoW не вызываются.
2. **Session/auth:** только merged CB-52 cookie resolver и server-side
   `ActorContext`. Invalid/missing/revoked/expired → CB-52 `401`; его
   фактический pre-owner auth `403`, если есть, сохраняется. Mutable task
   authority здесь не precheck: она остаётся receipt-first owner.
3. **Idempotency-Key:** raw case-insensitive list должен содержать один header и
   одно value. Grammar `[1-9][0-9]{0,18}`, numeric range
   `1..9223372036854775807`. Sign, leading zero, whitespace, empty, non-ASCII
   digits, overflow, comma-joined и duplicate запрещены. Любой отказ →
   `422 {"code":"invalid_idempotency_key"}`, owner/UoW zero effects.
4. **Route/body:** вручную после key проверить canonical UUID `task_id` и
   empty body. Ошибка → `422 {"code":"invalid_request"}`, owner not called.
5. **Owner:** построить server-side command и один раз вызвать
   `AssignmentService.accept_with_task`.

Precedence:
`invalid Origin 403 → invalid session/auth 401/CB-52 403 → invalid key/request 422 → expected owner 409 → success 201 | unexpected 500`.

### Security-required operation-id glue

Baseline evidence: `processed_telegram_updates.update_id` — global primary key,
receipt lookup использует только `update_id`, не actor. Raw browser int64
создал бы cross-actor replay/privacy collision и запрещён.

После valid session, parsed task UUID и canonical key helper без
secret/config/table/class сериализует однозначный tuple. Каждое поле имеет
unsigned 2-byte big-endian length prefix:

`len("accept") || b"accept" || len(member_uuid.bytes) || member_uuid.bytes || len(task_uuid.bytes) || task_uuid.bytes || len(key_ascii) || key_ascii`.

Затем `hashlib.sha256(encoded).digest()`; первые 8 bytes читаются big-endian,
маскируются `& 0x7fffffffffffffff`; zero заменяется на one. Positive signed
63-bit value передаётся owner как `update_id`.

Это Category 1 stdlib security glue: без codec class, UUID, keyed hash, schema
или business predicate. `member_id`, raw key, derived id и digest не попадают
в response/log. Same command+actor+task+key стабилен; изменение actor/task/key
меняет derived ID в exact deterministic tests.

### Receipt-first owner и atomic effects

Owner остаётся `AssignmentService.accept_with_task`; порядок не переставляется:

`existing update gate → existing receipt lookup → replay actor/task check → exact replay | actor/current authority → existing member/task gates and task access → existing assignment lookup → safe existing resource | existing acceptance checks/create → assignment + reliability + allowlisted audit + outbox + receipt → one commit`.

После `_begin/_assignment_replay` owner сверяет
`assignment.performer_id == ActorContext.member_id` и
`assignment.task_id == command.task_id` до возврата DTO/task. Mismatch,
legacy/cross-operation/hash collision → generic `409 assignment_unavailable`,
zero disclosure/effects. Identity-matched committed replay возвращается до
mutable status/eligibility checks: same actor/task/key после pause/restriction
получает прежний canonical `201`.

Если receipt отсутствует, existing actor/current-authority, moderation,
member/task gates, locked task и test-access boundary выполняются как сейчас.
Под этими gates `list_task_assignments(task_id, for_update=True)` ищет exact
`performer_id`. Status из existing `ACTIVE_ASSIGNMENT_STATUSES` возвращает
существующий safe assignment/task DTO без нового receipt/audit/outbox/
reliability/ledger effect. Terminal или `CANCELLED` row → generic `409`;
reanimation/new assignment запрещены. Только при отсутствии natural resource
owner продолжает прежние acceptance checks и create semantics.

Task gate сериализует same-task concurrent different keys, member gate —
active limit across tasks. Same/different keys создают максимум одну assignment
и один accepted effect; следующий request после gate получает existing active
success либо generic `409` по recorded state, но не `IntegrityError/500`.
DB uniqueness остаётся backstop, не normal control flow.

Один allowlisted `assignment_accepted` audit marker добавляется через existing
`append_audit_event` в ту же UoW: actor, action, task/assignment IDs, без
session/Telegram/private payload. Это mechanical completion принятого
transaction invariant, не новое domain decision. Replay не добавляет второй
audit/outbox/reliability/receipt.

### Response/error contract

Success/replay: `201` allowlisted DTO:
`id`, `task_id`, `slot_number`, `status:"accepted"`, `accepted_at`.

После successful Origin/session/wire gates любые **expected** owner rejections
(`LookupError`, `PermissionError`, `AssignmentError` и already existing
transport-neutral equivalents) → один
`409 {"code":"assignment_unavailable"}`. Route не различает unknown/hidden,
own/level/reviewer/deadline/capacity/duplicate/limit/restriction; не парсит
exception text и не повторяет predicates. Unexpected infrastructure errors →
generic `500`, `Cache-Control: no-store`, no internal text/IDs, full rollback.

## UI/XSS/accessibility contract

Catalog и in-memory detail — две surfaces. Success только после authoritative
`201`; pending блокирует double submit; network retry сохраняет тот же key.

Все DTO strings untrusted. Dynamic DOM только через `createElement`,
`textContent` и constant structural attributes (`class`, `type`, `role`,
нужные `aria-*`). Запрещены `innerHTML`, `outerHTML`,
`insertAdjacentHTML`, string-to-DOM parsers, inline handlers, dynamic `href`,
`src`, `srcdoc`, `style`, `target`. `materials.text` и
`materials.url` — literal `textContent`; no links/navigation/network effect.
Detail открывается button + in-memory state/History API.

Platform adapter применяет valid Telegram theme allowlisted property-by-property;
любое invalid value даёт atomic fallback всей base palette на CB-58 tokens.
Semantic landmarks/headings/buttons, 44×44 CSS px, keyboard focus/restore,
`aria-live`, safe areas, dark/light и reduced motion обязательны.

## Changes и budgets

| Область | Разрешённое изменение | Категория |
|---|---|---|
| existing web transport/DTO | DTO, gates, SHA-256 derivation, owner call, response mapping | 1 |
| existing assignment application/UoW glue | ActorContext mechanical input, receipt-first unchanged, existing audit primitive | 2 |
| existing DB receipt delegate | только mechanical replay plumbing; schema unchanged | 2 |
| static assets | native UI + CB-58 reuse | 1 |
| domain engine | никаких изменений | 3 = `0 files / 0 LOC` |

Hard: одна новая POST route; zero GET detail; zero tables/migrations; zero
runtime dependencies/new abstractions; zero domain rewrite.

Soft targets: до 8 production text files, 800 новых непустых production LOC и
один browser scenario плюс сгруппированные risk oracles. Превышение запускает
ровно один ~10-minute audit очевидного duplicate/dependency/file. Line-golf и
refactor ради числа запрещены; rationale важнее ceiling.

## Verification plan

DTO/privacy:

- JSON содержит existing fields + пять approved fields;
- `public_input` только allowlist intersection; raw/private values отсутствуют;
- missing/non-list/list с любым non-string `public_input_keys` fail closed в
  empty tuple/projection; unknown string keys игнорируются;
- materials closed, лишние keys отсутствуют.

Precedence/zero effects:

- missing/wrong/`null`/case/port/slash mismatch/duplicate Origin вместе с bad
  key/UUID/body всегда → exact `403 invalid_origin`; session/owner not called,
  assignment/reliability/audit/outbox/receipt counts unchanged;
- valid Origin + invalid/expired/revoked session + bad key → CB-52 `401`
  (или actual auth `403`) до key/owner; zero writes;
- valid Origin/session + missing/empty/`0`/`00`/`+1`/`-1`/whitespace/
  non-ASCII/overflow/comma/duplicate key → exact
  `422 invalid_idempotency_key`; owner not called, zero writes;
- valid Origin/session/key + invalid UUID/non-empty body →
  `422 invalid_request`; owner not called.

Idempotency/transaction/security:

- fixed encoding/derivation vectors: same command/member/task/key stable;
  actor/task/key changes different; tuple boundaries unambiguous; positive
  signed-63-bit; zero branch isolated; no identity/key/id in response/log;
- first accept → exactly one assignment, reliability event, audit, outbox,
  existing receipt и `201`;
- same actor/task/key concurrent → same canonical `201`, one effect set;
- same actor/task/key after status change → prior `201`;
- replayed assignment actor/task mismatch (forced collision and legacy/
  cross-operation fixtures) → common `409`, no DTO/leak/effect;
- same actor/task/new key with active assignment → same safe assignment `201`,
  no new receipt/audit/outbox/reliability; terminal/cancelled → common `409`;
- different keys concurrently on same actor/task → maximum one assignment/
  accepted effect; remaining existing success or `409`, never unique
  `IntegrityError/500`;
- different actors/same browser key and same actor/key/different task derive
  different IDs and never replay/leak each other;
- all expected owner cases → indistinguishable `409 assignment_unavailable`,
  zero new effects;
- unexpected infra fault → generic 500/no-store/full rollback; retry succeeds;
- existing last-slot and active-limit concurrency tests stay green.

Browser/XSS:

Один test-scoped Playwright scenario (no runtime Node dependency): mocked
bootstrap/catalog → in-memory detail → pending accept → authoritative 201 →
confirmed → back/focus. Это frontend mock; real Secure HttpOnly session и
PostgreSQL owner path доказываются HTTP integration.

Malicious fixture включает `<script>`, `<img onerror>`, `javascript:`,
quotes/markup в title/description/instructions/public_input/material URL/text.
Все видны literal text; нет created `script/img/a`, handlers, dynamic
`href/src/srcdoc/style/target`, navigation/network/execution. Invalid Telegram
palette доказывает atomic fallback production adapter.

Machine gates:

- каждый production file классифицирован; category 3 count zero;
  `git diff -- src/community_bot/domain` empty;
- ровно один new POST/no GET detail; migration head/table inventory unchanged;
- no forbidden dependency/framework; static scan no HTML sinks/dynamic URLs;
- targeted PostgreSQL/browser/full suite green;
- один soft-budget audit записан с fact/rationale.

## Execution after approval

1. Только при exact `Status: approved`: fresh refs, branch `task/CB-53` от
   `origin/main@ea8550f`, Jira точным transition → `В работе`.
2. DTO/privacy + transport/idempotency tests, затем adapter, затем static UI.
3. Targeted/PostgreSQL/browser/full suite, gates и один budget audit.
4. `implementation-report.md`, independent `final-review.md`.
5. При approved final gate: commit, push, PR, CI/review, merge; Jira `Готово`
   только после merge и verification.

При post-escalation `changes_requested`/`blocked` runtime не начинается;
возвращается точный terminal blocker, self-certification запрещена.
