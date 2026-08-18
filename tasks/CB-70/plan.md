# CB-70 — 20/80 план создания задания в Mini App

**Status: owner accepted; implementation verified locally, delivery pending**

## Один проверяемый результат

Активный участник открывает Mini App, нажимает «Создать задание», заполняет
одну fixed free-form форму, получает server preview, явно публикует задание и
видит подтверждение с immutable `task_id`.

Переиспользуются existing `TaskService`, `TaskCreationDraftModel`, доменные
validators, `publish_command_id`, receipt, reserve/ledger/audit/outbox и native
static shell. Новый engine, owner, table, migration, dependency или framework
не добавляется.

## Осознанное 20/80 сужение

Draft становится durable на двух server-owned границах:

1. `start` создаёт или возобновляет current free-form draft;
2. явное действие «Предпросмотр» атомарно сохраняет всю fixed форму и переводит
   draft в `preview`.

Промежуточный ввод отдельных полей до «Предпросмотра» не сохраняется. После
успешного preview restart возвращает exact values/revision. Если preview стал
невалидным, например deadline истёк, GET возвращает сохранённые значения в ту
же форму для полного повторного сохранения. Отдельные `advance` и
`edit_draft_step` web-команды не нужны.

Это изменение гранулярности durability относительно первого approved plan
требует явного принятия владельцем до implementation.

## API: один resource path, две HTTP operations

### `GET /api/v1/task-creation`

Возвращает один allowlisted resource:

- visible categories из existing owner;
- `TASK_TIME_SIZE_SPECS` с labels/reward choices/minimum;
- `draft=null` либо current member free-form draft;
- saved form values, exact revision;
- nullable server `preview` и `needs_edit`.

GET не мутирует состояние. Mismatched test-run, template и community draft
невидимы.

### `POST /api/v1/task-creation`

Один closed discriminator `action`:

- `start` — пустая команда, создаёт или возобновляет current draft;
- `save` — `draft_id`, exact `expected_revision` и вся fixed free-form форма;
- `publish` — `draft_id` и exact preview revision, возвращает только
  `{task_id}`.

`Origin`, session, bounded JSON и один positive numeric `Idempotency-Key`
обязательны. Operation identity включает action, actor, resource и key.
Existing receipt хранит compact fingerprint exact command. Same key+same command
replay exact; same key+different command — `409` без effect.

Resource identity фиксирован:

- `start`: `actor.member_id` одновременно actor и resource;
- `save`/`publish`: actor — `actor.member_id`, resource — canonical `draft_id`.

Fingerprint строится только после strict parse из canonical closed payload:
`action`, exact revision и normalized form для `save`; `action` и exact revision
для `publish`; только `action=start` для start. `start` и `save` возвращают
`204`, затем клиент читает authoritative GET. Same-key publish replay всегда
возвращает тот же immutable `{task_id}`, включая последующее изменение status
задачи. Любой same-key иной fingerprint возвращает `409` до effect.

Это не generic command/form framework: допустимы ровно три literals и один
закрытый free-form payload текущего домена.

## Fixed form

Поддерживаются существующие member free-form значения:

- `task_kind=solo|group`, slots `1` для solo и `>=2` для group;
- visible `category_id`;
- `time_size`, server-projected reward;
- title, description, completion criteria;
- closed materials `{text?, url?}`;
- aware deadline;
- `online|offline` и city.

Transport только типизирует bounded payload. Application под draft lock строит
один candidate snapshot, а existing domain validators остаются владельцами
всех limits, reward, materials, deadline, format/city и publishability.

## Identity, isolation и legacy

- Web передаёт только `ActorContext.member_id`; Telegram ID не принимается из
  request.
- Узкий actor-native seam добавляется только для start/save/current/publish.
  Legacy Telegram `start/advance/edit/preview/publish` и permissive edit
  semantics не меняются.
- Web path не вызывает `claim_text_flow`/`clear_text_flow` и не меняет
  `conversation_states`.
- GET/save/publish требуют exact active test scope. Valid start под shared
  identity lock resume-ит same-scope draft либо supersede-ит mismatched current
  и создаёт новый scoped draft без чтения/copy старого payload.
- Publish сохраняет existing reserve/ledger/audit/outbox atomicity и
  different-key business retry semantics.

## UI: четыре состояния

1. каталог с одной кнопкой «Создать задание»;
2. одна native форма;
3. server preview либо та же prefilled форма с `needs_edit`;
4. success card с immutable `task_id` и `history.replaceState` в каталог.

Back/popstate только навигирует и никогда не вызывает `start`. `start` вызывается
только прямым нажатием «Создать задание». Browser storage не используется.

## DELETE / REVERT из эксперимента

Перед implementation полностью удалить незакоммиченный экспериментальный diff
runtime/tests и строить заново от rebased plan baseline. Не переносить:

- пять раздельных routes и per-step `PUT` contract;
- actor-native изменения legacy `advance` и `edit_draft_step`;
- `CurrentTaskDraft`/per-step DTO hierarchy и большой `_task_step_value` parser;
- 12-step client renderer, edit-button grid и связанные UI states;
- экспериментальные широкие tests, которые закрепляют удалённый per-step API;
- известный `pushState → Back → POST start` path.

`tasks/CB-70/final-review.md` сохраняется как evidence неудачного цикла.

## REUSE map

- `TaskService.start` и `publish` — минимальный actor-native branch. Только web
  command условно пропускает existing `claim_text_flow` в `start` и
  `clear_text_flow` внутри publish helper; Telegram branch продолжает выполнять
  оба вызова без изменения ordering и permissive semantics;
- один `save_web` под existing `TaskService` lock строит complete candidate и
  вызывает existing validators/save; он намеренно не вызывает и не меняет
  `advance`/`edit_draft_step`;
- `_replace_draft`, `_validate_freeform_publishable`, category lookup и
  `TASK_TIME_SIZE_SPECS` — один atomic save candidate;
- existing receipt/update gate и CB-69 compact fingerprint pattern;
- `TaskCreationDraftModel.test_run_id`, `active_scope`, current-draft query и
  publish command identity;
- existing web session/Origin/body/idempotency helpers;
- existing `element`, `section`, navigation, status, native input and button
  primitives в `app.js`/`styles.css`.

## Hard LOC ceiling

Считается `git diff --numstat origin/main -- src/community_bot` после полного
revert эксперимента:

| Causal line и добавляемые symbol-границы | Max net runtime LOC |
|---|---:|
| `application/tasks.py`: typed full-form command/view; actor-native start/current/save/publish branches; compact web outcome parsing | 170 |
| DB adapter: только `ensure_task_draft_test_access` + Database delegation | 15 |
| `transport/web.py`: closed action DTOs, GET/POST handlers, canonical update identity/fingerprint, allowlisted projection | 140 |
| `app.js` + `styles.css`: catalog CTA, one native form, preview/recovery/success, navigation without mutation | 125 |
| **Итого hard ceiling** | **450 net** |

Первый deletion/reuse audit достиг ровно `450 net`. Затем independent final
review потребовал canonical normalization до fingerprint и хранения. Владелец
заранее разрешил amendment stop `500`, а reviewer подтвердил его условия:
добавка нужна actor-native replay/isolation/closed transport, не содержит
speculative abstraction или скопированного domain rule и остаётся в тех же
шести runtime-файлах. Итог после replay-safe correction — `467 net`; `500` остаётся stop,
не целью. Косметическая минификация и перенос обязанностей в tests/docs
запрещены.

## Acceptance oracles

1. Active session: start/resume ровно один current member free-form draft;
   template/community/inactive/foreign fail closed без receipt/audit/draft
   effect.
2. Full save exact revision создаёт один durable preview; malformed, oversized,
   stale, hidden category и invalid domain values имеют zero effects.
3. Restart после preview возвращает exact saved values/revision; expired preview
   возвращает `needs_edit=true`, затем full resave восстанавливает preview.
4. Web path не создаёт и не меняет `ConversationStateModel`; accepted Telegram
   creation scenarios остаются зелёными.
5. Matrix `public → active run → stale/public`: GET/save/publish невидимы и
   zero-effect при mismatch; valid start supersede-ит old current без payload
   copy; same-scope restart resume-ит draft.
6. Same key+same start/save/publish replay exact; conflicting fingerprint —
   deterministic `409`.
7. Publish exact revision создаёт один task/reserve/audit/outbox; concurrent и
   different-key retry не повторяют effects и возвращают тот же `task_id`.
8. DTO/DOM не содержат creator/test-run/publish-command/receipt/private schema;
   malicious text остаётся literal.
9. Browser one journey: group form → preview → simulated expired recovery →
   corrected preview → publish → Back/catalog без нового POST start.
10. Нет новых routes сверх одного resource path, schema/model/dependency/service,
    browser storage или generic renderer.

## Targeted gates

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check src tests ops
uv run pytest --no-cov -q tests/integration/test_task_creation.py tests/integration/test_web_api.py tests/unit/test_web_auth.py
uv run pytest --no-cov -q tests/browser/test_mini_app.py
git diff --check origin/main
```

Targeted coverage запускается отдельно с `--cov-fail-under=0`, потому что
repository-wide `fail-under=80` делает модульную coverage-команду ложно красной
при passing target tests. CI остаётся владельцем полного repository gate.

## Delivery

Только после independent plan approval и owner acceptance сужения:

1. revert всего экспериментального runtime/test diff;
2. реализовать новый plan с LOC check;
3. targeted gates → independent final review;
4. commit → force-with-lease push после rebase → PR → green CI → merge;
5. отдельный immutable release CB-70 → production activation → public smoke;
6. Jira evidence и `Готово` только после smoke.
