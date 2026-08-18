# CB-70 — Mini App: создание собственного задания через durable draft

**Статус:** одобрен независимым level 3 plan review; runtime ожидает ownership
handoff после merge CB-69

**Jira / эпик:** `CB-70` / `CB-48`

**Baseline:** `49e8a7a360f1f8f8d5e5c5a5d827c17511ba6a05` (`origin/main`)

## Результат и граница

Добавить один основной путь:

```text
Каталог → Создать задание → durable free-form draft
        → authoritative preview → Опубликовать → success card → Каталог
```

Backend уже владеет всем бизнес-поведением. Переиспользуются
`TaskService.start → advance → preview → publish`, `task_creation_drafts`,
receipt/ledger/audit/outbox и доменная валидация. Web добавляет только
actor-native seam, пять тонких resource operations и fixed UI-map текущих
free-form шагов.

Разрешены `origin=member`, `template_id=None`, `task_kind=solo|group`.
Template и `origin=community` в этом slice fail closed до draft mutation.
Templates, community tasks и versioned config из backend не удаляются и не
меняются; для них позже нужен отдельный явный UI contract.

Новый ADR и migration не требуются: durable draft/exact-confirm уже принят
ADR-0017, post-merge delivery — ADR-0019. Автоматические integration/browser
oracles достаточны, отдельный manual `test-plan.md` не нужен.

## API: пять операций, без нового engine

1. `GET /api/v1/task-creation-options` — safe visible categories
   (`id/name/description/icon`) из existing owner и server projection
   `TASK_TIME_SIZE_SPECS` (`code/label/reward_options/minimum_reward`).
2. `GET /api/v1/task-drafts/current` — текущий safe draft либо `204`, без
   mutation. На step `preview` ответ включает server `TaskPreviewDto`; если
   после restart authoritative preview больше не проходит domain validation
   (например, deadline уже истёк), ответ сохраняет safe creator values,
   возвращает `preview=null` и `needs_edit=true` без raw error, чтобы UI мог
   выбрать step для исправления. Static route объявляется до `{draft_id}`,
   чтобы `current` не попадал в UUID parser.
3. `POST /api/v1/task-drafts` — begin либо resume current free-form member
   draft в active scope; пустой bounded body, `Origin`, session и canonical
   single positive numeric `Idempotency-Key`; ответ всегда `204`, после него
   клиент читает current resource. Если единственный current draft относится к
   public/другому/stale test-run scope, start под existing identity transaction
   атомарно снимает с него `is_current` и создаёт новый scoped draft через уже
   существующий `create_task_draft`, не читая и не возвращая старый payload.
4. `PUT /api/v1/task-drafts/{draft_id}` — ровно одна команда
   `{expected_step, expected_revision, value}`. Для обычного step это existing
   `advance`; когда `expected_step=preview`, `value` — один разрешённый
   free-form step и команда делегирует existing `edit_draft_step`, чтобы вернуть
   preview в редактирование. Actor-native application path под draft lock
   требует `expected_revision == draft.revision`; permissive legacy Telegram
   edit semantics не ужесточается. Transport pre-read не используется из-за
   TOCTOU. Transport преобразует bounded JSON только в
   существующие типы `UUID`/enum/int/text/mapping/aware datetime/
   `(format, city)`; editable-step allowlist остаётся у application owner,
   domain остаётся единственным validator. Ответ `204`, затем клиент читает
   current resource.
5. `POST /api/v1/task-drafts/{draft_id}/publish` — exact preview revision,
   explicit confirmation, затем response содержит только immutable
   `{task_id}`; клиент строит generic success card без перечитывания изменяемого
   `TaskDto.status`. Собственное задание намеренно отсутствует в
   performer catalog, поэтому клиент не делает бессмысленный catalog refresh;
   Back возвращает в существующий каталог. Баланс остаётся server-owned и
   обновится существующим `/me` при следующем открытии профиля.

Current response — `TaskDraftDto` с `id`, `current_step`, `revision`, nullable
`preview`, `needs_edit` и только необходимыми creator-owned values. Новый узкий
application query читает draft и при step `preview` строит existing
`TaskPreview` из той же transaction/revision; validation failure становится
только safe `needs_edit=true`, а не потерей доступа к draft. Transport не
склеивает два race-prone чтения. Отдельный preview endpoint и optimistic
calculation не нужны. `204` mutation responses делают exact replay стабильным
без сохранения mutable DTO snapshot.
DTO не содержит creator/test-run/publish-command/reviewer/internal IDs,
private schema, ledger, audit или receipt. Resource/category IDs используются
клиентом, но не выводятся текстом в DOM.

Fixed step-map поддерживает только существующие free-form steps:

- `task_kind`: `solo|group`;
- `category`: выбор из GET projection;
- `time_size`: `xs|s|m|l|xl` с server-owned labels/options;
- `slots`: integer, показывается только для group;
- `reward`: integer из server-projected allowed options/minimum;
- `title`, `description`, `completion_criteria`: bounded text;
- `materials`: обязательный closed existing mapping минимум с одним непустым
  полем `text` либо HTTP(S) `url` без credentials; каждое поле по отдельности
  optional, пустой object fail closed;
- `deadline`: aware ISO-8601 datetime;
- `format`: `online|offline`, city только для offline;
- `preview`: literal-text summary и reserved total из backend.

Клиент не копирует domain limits/reward formulas: labels и reward
choices/minimum возвращает server contract, bounded body ограничивает transport,
а field limits и окончательную валидацию выполняет domain. Unknown
step/value/schema fail closed.

## Identity, replay и transaction boundary

- Web caller передаёт только server `ActorContext.member_id`; Telegram ID из
  body/path не принимается.
- Existing Telegram callers сохраняют `actor_telegram_user_id` и
  `claim_text_flow`/`clear_text_flow`. Actor-native web path использует shared
  member resolver/identity gate и никогда не меняет `conversation_states`, в
  том числе при `edit_draft_step`.
- Для GET/direct advance/preview/publish transaction-local guard сравнивает
  draft `test_run_id` с active scope actor; mismatched/stale draft невидим и
  имеет zero effects. Valid POST start является единственным намеренным
  переходом: под existing identity transaction он resume-ит same-scope draft
  либо атомарно supersede-ит mismatched current и создаёт новый scoped draft,
  не раскрывая старый payload. Это сохраняет liveness без новой schema.
- Derived numeric update identity включает operation kind, actor, resource и
  canonical single positive numeric `Idempotency-Key`, но не body/revision.
  Поэтому same key всегда находит тот же receipt; hash collision/legacy receipt
  другого operation kind fail closed.
- Existing receipt `outcome_code` хранит backward-compatible compact command
  fingerprint и result identity/revision для web start/advance/publish. Same key
  + exact command возвращает тот же `204` либо тот же immutable `task_id`;
  current draft всегда перечитывается GET. Same key + другой
  step/revision/value даёт conflict до нового effect. Новая таблица/колонка не
  нужна.
- Publish сохраняет существующий `publish_command_id`, catalog gate,
  reserve/ledger/audit/outbox и concurrent single-task semantics. Повтор с тем
  же key использует один receipt; business retry с другим key после успешной
  публикации возвращает тот же `task_id`, не повторяет reserve/audit/outbox, но
  по принятому existing contract завершает свой отдельный receipt.

## Файлы и ownership

| Файл | Минимальная правка |
|---|---|
| `src/community_bot/application/tasks.py` | Optional actor-native identity для start/categories/advance/edit/publish; transaction-consistent current-draft+preview query с safe recoverable invalid-preview state; exact revision equality только для actor-native edit; web receipt fingerprint parsing; test-run guard; skip Telegram text-flow only для web. Existing permissive Telegram edit и domain/publish/economy behavior не менять. |
| `src/community_bot/infrastructure/db/tasks.py`, `database.py` | Один draft test-run access query/gate и UUID-capable existing identity gate; no new table/model. |
| `src/community_bot/transport/web.py` | DTO allowlists, bounded step-value parsing, operation derivation и пять routes. |
| `src/community_bot/transport/static/app.js` | Одна кнопка из каталога, fixed step controls, preview/publish и authoritative refresh. |
| `src/community_bot/transport/static/styles.css` | Только native input/select/textarea/form styles, если existing primitives недостаточны. |
| `tests/integration/test_task_creation.py` | Actor-native owner/revision/restart/test-run/text-flow/replay/concurrent-publish oracles поверх existing owner. |
| `tests/integration/test_web_api.py`, `tests/unit/test_web_auth.py` | HTTP/session/Origin/body/key/DTO/privacy/zero-effect matrix. |
| `tests/browser/test_mini_app.py` | Один end-to-end free-form journey; solo/group branch объединить в один scenario, не создавать новый test layer. |
| `tasks/CB-70/*` | Plan package, затем implementation/final review evidence. |

CB-69 владеет `web.py` и static assets до merge. До ownership handoff CB-70 не
начинает runtime edits; планирование/review выполняются параллельно.

## Acceptance и exact oracles

1. Active web actor начинает или возобновляет один current free-form member
   draft; inactive/foreign/template/community paths дают closed error и ноль
   draft/audit/receipt effects. Matrix отдельно доказывает переходы
   public → active run → stale/public: GET/direct advance/publish не видят
   mismatched draft и имеют zero effects, а valid POST start атомарно делает
   старый draft non-current и создаёт новый draft в active scope. Старые payload
   никогда не возвращаются и не копируются между scopes; same-scope restart
   resume-ит прежний draft.
2. Restarted app возвращает exact current step, revision и safe saved values;
   web actor не создаёт/меняет `ConversationStateModel`.
3. Advance проверяет exact owner/step/revision и category visibility;
   malformed/oversized/naive deadline/invalid enum/value/unknown step имеет
   zero effects и не отражает raw body в error/log/DTO.
4. Same key+same start/advance возвращает exact `204` без нового effect даже
   после последующих шагов; current GET остаётся authoritative. Same key с
   другим command — deterministic `409`; exact publish replay возвращает тот же
   immutable `task_id` даже после последующего изменения task status.
5. Solo автоматически остаётся с одним slot; group требует минимум два.
   Reward, deadline, format/city, text и materials принимает только existing
   domain validator; UI ничего не пересчитывает.
6. Preview показывает exact public fields и `reserved_credit_total`, но не
   меняет balance/ledger/task/outbox. Malicious text остаётся literal text.
   Любой preview, включая ставший просроченным после restart, возвращается GET
   как safe `needs_edit=true` без optimistic preview и может перейти в
   разрешённый free-form step через тот же PUT/edit owner; stale web revision и
   недопустимый target step имеют zero effects, при этом accepted permissive
   Telegram edit scenario остаётся зелёным. После исправления deadline
   authoritative preview снова строится и publish становится доступен.
7. Publish exact revision создаёт ровно один task/reserve/audit/outbox. Same-key
   replay сохраняет один receipt; concurrent/delayed business retry с другим
   key возвращает тот же task, не повторяет domain effects и завершает отдельный
   receipt согласно existing engine. Insufficient credit/stale/foreign запросы
   не создают partial effect.
8. Template/community requests fail closed до draft mutation; private/internal
   IDs, publish command, test-run и receipt data отсутствуют в DOM.
9. Browser: loading/error/retry, keyboard/focus/Back, restart/resume, один
   solo/group path, preview → edit → corrected preview, exact confirmation,
   success card после server-returned `task_id` и возврат к каталогу без
   optimistic domain state.
10. Existing Telegram task-creation scenarios и весь engine остаются зелёными;
    schema/migration/dependency/model count не меняются.

## Проверки

До final review, в порядке стоимости:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check src tests ops
uv run pytest -q tests/integration/test_task_creation.py tests/integration/test_web_api.py tests/unit/test_web_auth.py --cov=community_bot.application.tasks --cov=community_bot.infrastructure.db.tasks --cov=community_bot.infrastructure.db.database --cov=community_bot.transport.web --cov-report=term-missing
uv run pytest --no-cov -q tests/browser/test_mini_app.py
git diff --check origin/main
git diff --cached -U0 origin/main | uv run python -c "import re,sys; text=''.join(line[1:] for line in sys.stdin if line.startswith('+') and not line.startswith('+++')); patterns=(r'AKIA[0-9A-Z]{16}', r'gh[pousr]_[A-Za-z0-9]{36,}', r'-{5}BEGIN .* PRIVATE KEY-{5}', r'(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*\S{8,}'); hits=[pattern for pattern in patterns if re.search(pattern,text)]; print('secret_scan=pass' if not hits else 'secret_scan=fail:' + ','.join(hits)); raise SystemExit(bool(hits))"
```

Targeted coverage сначала закрывает изменённые runtime lines/branches. Full
repository suite выполняет PR CI и локально повторяется только при конкретном
риске. Перед cached scan весь planned diff явно staged; commit — только после
approved final review.

## Ponytail и размер

- **KEEP:** существующий draft state machine, validators, receipts,
  publish-command identity, ledger/audit/outbox, native static shell.
- **REMOVE:** ничего из engine; только очевидное дублирование helpers после
  implementation.
- **DO NOT ADD:** table/migration/model/dependency/service/repository/UoW,
  generic operation/form/schema framework, React/Vite/browser storage.

LOC — диагностический сигнал, не искусственный acceptance limit. Если реализация
потребует больше пяти routes, нового persistence owner либо примерно 450
runtime LOC сверх тестов, остановиться и разделить scope по причинной границе,
а не ужимать код ценой скрытой сложности.

## Stop, rollback и delivery

Остановиться, если:

- CB-69 не merged и продолжает владеть `web.py`/static files;
- exact replay/conflict требует новой таблицы/колонки;
- test-run GET/direct-mutation guard и start supersede нельзя выполнить внутри
  existing identity transaction до видимого draft effect;
- transport начинает копировать domain validation/reward logic или строить
  template/schema renderer;
- community/template/admin flow становится необходим для member free-form path.

До merge rollback удаляет только CB-70 diff. После deployment — предыдущий
compatible image tuple; schema/data downgrade не нужен. После approved
`final-review.md`: commit → PR → green CI → merge → exact ADR-0019 release →
pilot activation → public `/mini-app`/assets/API smoke → Jira evidence/Done.
