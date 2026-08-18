# CB-69 — Mini App: durable отправка результата по своему заданию

**Статус:** одобрен независимым level 3 plan review; реализация разрешена
владельцем в рамках делегированного ведения задач

**Jira / эпик:** `CB-69` / `CB-48`

**Базовая версия:** `49e8a7a360f1f8f8d5e5c5a5d827c17511ba6a05` (`origin/main`)

## Решение и граница

Реализовать единственный performer-сценарий:

```text
active assignment
  -> durable draft (begin/resume)
  -> save validated preview
  -> explicit confirm
  -> immutable result version + authoritative assignment detail refresh
```

Используются существующие `AssignmentService.begin_submission`,
`save_submission_draft` и `confirm_submission_draft`. Прямой web-вызов
`AssignmentService.submit` не добавляется: он обходит принятый durable-draft
инвариант ADR-0017.

Первый UI поддерживает только существующий free-form result contract:

```json
{"result":"…"}
```

Server-authoritative discriminator уже существует: у free-form task
`template_id is None`. Любой template assignment получает
`submission_contract: null`; begin/save/confirm для него fail closed до
создания или изменения draft. Это не копирует historical schema, не меняет
config/history и не обещает arbitrary JSON Schema parity. Template result UI
добавляется отдельным slice только вместе с явным versioned UI contract.

## Почему это минимально

- `AssignmentSubmissionDraftModel` уже хранит owner, revision, payload,
  stable `submit_command_id` и confirmed result.
- Existing service уже сериализует task/assignment, применяет ownership,
  deadline и reviewer checks, вызывает historical validator, пишет
  outbox/receipt и подтверждает ровно один immutable result. Actor-native seam
  добавляет отсутствующий web test-run guard до draft mutation.
- Нужен только narrow actor-native seam, HTTP DTO/identity glue, проверка
  existing `template_id is None` и native UI поверх merged CB-68 static shell.
- Не добавляются table, migration, dependency, service, repository, UoW,
  generic operation framework или JSON Schema renderer.

## API и operation identity

Три resource operations под `/api/v1`:

1. `POST /assignments/{assignment_id}/submission-drafts` — begin либо resume;
   body пустой.
2. `PUT /submission-drafts/{draft_id}` — save canonical free-form
   `{"result":"…"}` preview с `expected_revision`.
3. `POST /submission-drafts/{draft_id}/confirm` — explicit confirm с
   bounded body `{"expected_revision": <int>}`; success отвечает `204`, после
   чего клиент перечитывает existing assignment detail.

Все mutation routes применяют existing exact single `Origin`, web session,
canonical single numeric `Idempotency-Key`, canonical UUID, bounded body и
`Cache-Control: no-store`. Сначала проверяются Origin/session/key, затем
request shape и business owner; payload, cookie и Telegram proof не пишутся в
error или log. Dedicated `SubmissionDraftDto` возвращает только владельцу его
normalized draft payload, id и authoritative revision — это необходимо для
restart/resume и не раскрывается другим actors.

HTTP identity — domain-separated SHA-256 int63 preimage из `v1`, operation
name, `member_id`, resource UUID и idempotency key. Body/revision не входят в
`update_id`: повтор того же key обязан найти тот же receipt, а не стать новой
операцией.

Для web save/confirm existing receipt `outcome_code` получает compact command
fingerprint (expected revision + canonical payload hash для save, revision для
confirm) вместе с result/draft identity. Replay сначала сравнивает fingerprint:
тот же key с другим command даёт deterministic conflict без effect; exact key
не повторяет mutation. Legacy Telegram outcome format продолжает читаться без
миграции. Новый table/column/store не добавляется.

`Save` отвечает allowlisted `SubmissionDraftDto` с фактическими payload и
revision из existing service. Клиент не вычисляет revision и использует
server-returned value для confirm. После restart/resume тот же authoritative
draft возвращается из begin route; новый operation/presentation store не нужен.

## Server-authoritative free-form discriminator

Existing assignment owner возвращает literal `"freeform_result_v1"` только
когда authoritative task имеет `template_id is None`; любой template получает
`None`. Никакой frozen schema, hash allowlist или копия validator не нужны.
Save по-прежнему вызывает existing `_validate_result_payload`, включая
`validate_freeform_result_payload`.

`GET /api/v1/assignments/{assignment_id}` получает allowlisted
`submission_contract: "freeform_result_v1" | null`. UI использует только этот
projection; begin повторяет guard под transaction до
`create_or_get_submission_draft`, save — до изменения payload/revision,
confirm — до создания result version. Поэтому прямой URL/draft ID не обходит
fail-closed boundary и неизвестная historical schema не получает mutation.

## Изменения по владельцам

| Файл | Владелец и минимальная правка |
|---|---|
| `src/community_bot/application/assignments.py` | Добавить optional `actor_member_id` к трём existing submission commands и shared actor resolver, сохранив Telegram callers; добавить free-form guard/projection, test-run access и exact actor/draft/revision/command-fingerprint replay binding. При actor-native web path не вызывать Telegram `claim_text_flow`/`clear_text_flow`; legacy callers сохраняют их. Не менять domain states, validator, settlement или receipt table. |
| `src/community_bot/transport/web.py` | DTO allowlists (`SubmissionDraftDto`, `SubmissionContract` field, save/confirm request DTO), bounded request parser, operation-ID derivations и три routes. Confirm отвечает `204`; transport не публикует result/internal ID. Только translate wire/auth/errors в existing owner. |
| `src/community_bot/transport/static/app.js` | Native form, local preview, same-key retry, save/confirm и authoritative detail reload. Не создавать state framework или dynamic schema renderer. |
| `src/community_bot/transport/static/styles.css` | Только необходимые styles existing form/status primitives. |
| `tests/integration/test_assignments.py` | Existing owner: actor-native begin/save/confirm, owner/revision/restart/concurrent-confirm and zero-partial-effects oracles. |
| `tests/integration/test_web_api.py` | Real HTTP/PostgreSQL matrix: contract projection, Origin/session/body/key order, receipt/outbox/result counts, schema fail-close and stale/race cases. |
| `tests/unit/test_web_auth.py` | Closed route/API/error/identity vectors and DTO allowlist. |
| `tests/browser/test_mini_app.py` | One native journey: detail → begin/resume → form → preview → confirm → refreshed submitted state; keyboard/focus/loading/error and literal text rendering. |
| `tasks/CB-69/*` | Этот plan, затем implementation report/final review по level 3 process. |

CB-68 merged в baseline `49e8a7a`, deployed и передал владение общими static
assets. CB-69 может менять `app.js`/`styles.css` только в описанной выше области.

## Acceptance и точные oracles

1. **Ownership / state.** Active performer начинает или возобновляет только
   свой active assignment; foreign, terminal, paused, reviewer-conflict,
   expired и test-run-invisible contexts дают closed error и создают ноль
   drafts/results/receipts/outbox/conversation-state effects. Web path вызывает
   existing `ensure_task_test_access` до draft mutation.
2. **Contract.** Только authoritative free-form task (`template_id is None`)
   exposes literal `freeform_result_v1`. Любой template/future historical
   schema и direct begin дают fail-closed response без draft mutation; raw
   schema не сериализуется.
3. **Draft durability.** Restart returns same draft id, owner, payload and
   revision. Foreign draft ID, stale revision and malformed payload have zero
   effects. Save advances revision once.
4. **Exact confirm.** Concurrent identical confirm produces one immutable result
   version, one receipt and one `assignment_submitted` outbox event. Same exact
   confirm replays it; stale/different revision cannot confirm a second result.
5. **HTTP idempotency.** Same full operation identity replays without a second
   effect. Concurrent different save payloads for one revision serialize and
   leave exactly one saved payload/revision; loser gets stale/conflict and has
   zero added effects.
6. **Security/privacy.** Exact Origin/session precede mutation; bounded
   content-type/body and DTO `extra=forbid` are enforced; собственный normalized
   draft payload доступен только owner в dedicated DTO, а private task fields,
   чужой payload, cookies и proof не попадают в DTO/error/log.
7. **Browser.** Free-form assignment presents accessible native controls and
   explicit confirmation; user-visible state comes from reloaded detail, not
   optimistic transition. Malicious strings render as text, with no generated
   URL/script/HTML execution.

## Проверки

До implementation final review выполнить в порядке стоимости:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check src tests ops
uv run pytest -q tests/unit/test_web_auth.py tests/integration/test_assignments.py tests/integration/test_web_api.py --cov=community_bot.application.assignments --cov=community_bot.transport.web --cov-report=term-missing --cov-fail-under=0
uv run pytest --no-cov -q tests/browser/test_mini_app.py
git diff --check origin/main
git diff --cached -U0 origin/main | uv run python -c "import re,sys; text=''.join(line[1:] for line in sys.stdin if line.startswith('+') and not line.startswith('+++')); patterns=(r'AKIA[0-9A-Z]{16}', r'gh[pousr]_[A-Za-z0-9]{36,}', r'-{5}BEGIN .* PRIVATE KEY-{5}', r'(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*[\x22\x27][^\x22\x27]{8,}'); hits=[pattern for pattern in patterns if re.search(pattern,text)]; print('secret_scan=pass' if not hits else 'secret_scan=fail:' + ','.join(hits)); raise SystemExit(bool(hits))"
```

Первая pytest-команда является локальным targeted coverage gate для обоих
изменяемых runtime-модулей. `--cov-fail-under=0` отключает только устаревший
глобальный package percentage; module report и machine intersection
`coverage json` с added runtime lines/branches фиксируются в implementation
report и закрывают реальные пробелы diff. Targeted PostgreSQL cases и browser
oracle являются локальным control gate.
Полный repository suite не дублируется локально без найденного риска; полный
набор выполняет обязательный PR CI. После code/test changes final reviewer
повторяет affected checks и назначает дополнительный control только по
конкретному evidence.

Перед `git diff --cached` весь planned diff явно staged; commit выполняется
только после approved final review, поэтому scan не читает пустой index.

## Stop gates

Остановить реализацию и вернуть plan owner, если:

- branch больше не основан на CB-68 merge `49e8a7a` либо static ownership снова
  занят другой незавершённой задачей;
- free-form discrimination требует raw schema delivery, generic renderer,
  copied JSON Schema validation, новый table/migration/dependency или отдельный
  service/repository/UoW;
- begin guard нельзя выполнить до draft mutation либо same-template history не
  разрешается authoritative PostgreSQL owner;
- exact save/confirm replay требует состояние вне existing draft/result/receipt
  owners;
- обнаруживается изменение domain lifecycle, ledger, audit, outbox semantics
  или product config/history;
- live deployment, real Telegram interaction или public URL требуется как
  доказательство этого локального implementation slice.

## Rollback и deployment

До merge rollback — удалить только CB-69 routes/DTO/actor seam/native form/tests
из task branch; schema/data downgrade не требуется. После merge rollback —
предыдущий совместимый web image/static bundle; existing drafts/results и
receipts не переписываются и не удаляются.

CB-69 не меняет deployment infrastructure. Но поскольку меняется deployable
runtime/frontend, после merge обязателен существующий ADR-0019 путь: green
`main` CI → exact immutable artifact → manual-first pilot activation → public
URL smoke → Jira evidence. Новые TLS/release/migration abstractions не
добавляются; до green production evidence нельзя заявлять delivery готовым.

## Process evidence

- Уровень риска: 3 — authenticated mutation с durable state, idempotency,
  ownership, result history и outbox.
- До runtime нужны approved level-3 plan review и owner approval этого plan;
  затем branch-local implementation, `implementation-report.md` и approved
  `final-review.md`.
- Jira уже является `CB-69`; этот файл не меняет Jira status. Перед любым
  transition получить actual available transitions.
- В plan нет секретов, raw Telegram proof, session cookie или private result.

## Ponytail audit

**KEEP:** existing draft/result tables, `AssignmentService`, UoW, receipt,
free-form validator, FastAPI/static shell и stdlib SHA-256 для operation IDs и
command fingerprints.

**REMOVE:** ничего: planned scope не создаёт повторяемый код для удаления.

**DO NOT ADD:** direct-submit web path, new operation table/framework, migration,
generic schema renderer, React/Vite, repository/service wrapper, client-side
authorization/validation or arbitrary-schema promise.

**Net LOC trigger:** expected production diff до ~280 nonblank lines и targeted
tests до ~300 nonblank lines. Превышение — review trigger: сначала удалить
duplicate DTO/helper/test; если после Ponytail audit нужен новый abstraction,
schema transport или persistence, остановиться и обновить owner-approved plan.
