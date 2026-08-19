# CB-81 — план one-shot редактирования собственного профиля

## Статус и owner decision

Предыдущий staged `begin → save` план отклонён независимым review: существующий
profile conversation не имеет Web revision contract и может перезаписать другой
active text flow. Runtime diff по нему не начинался.

Owner decision разрешает продолжить CB-81 без отдельной Jira-задачи ровно через
one-shot actor-native command в существующем `RegistrationService`. Новый путь
не вызывает Telegram `begin_profile_field_edit`/`save_profile_field` и никогда
не создаёт, не читает, не меняет и не удаляет `conversation_states`.

Уровень процесса: **3** из-за authenticated mutation и exact replay. Новый ADR
не нужен: локальный Web seam использует существующие application/UoW/receipt
границы без schema, integration или cross-cutting change.

## Решение

Добавить один application method `update_own_profile_field`:

1. принять `update_id`, server-issued `actor_member_id`, один `ProfileField`,
   raw string и canonical replay fingerprint;
2. взять existing update gate и прочитать existing receipt outcome;
3. для найденного receipt разобрать exact Web marker с actor, field и
   fingerprint: полное совпадение — replay без mutation, любое отличие или
   Telegram/чужой marker — conflict;
4. при новой операции получить member через existing `get_member`, взять
   existing registration identity gate по persisted Telegram identity, затем
   existing `lock_members` и применить `require_profile_owner`;
5. вызвать `normalize_profile_value` и existing DB field setter через один
   тонкий UoW method, который меняет только выбранную ORM column;
6. записать existing audit event и receipt, затем один commit.

One-shot update не использует profile revision: field update не читает и не
перезаписывает остальные profile fields. Identity/member locks сериализуют
операции одного actor; два concurrent commands для разных fields применяются
последовательно и оба сохраняются.

После command route выполняет новый `registration.own_profile(actor)` transaction
и возвращает существующий `MeDto`. Это authoritative reread, а не client merge.

## Exact replay contract

Transport детерминированно получает `update_id` existing namespaced hash helper
из namespace `profile-update-v1`, actor member ID, actor member ID как resource,
operation `update`, client `Idempotency-Key`.

Fingerprint — SHA-256 existing canonical JSON helper над exact command:

```json
{"field":"city","value":"Rosario"}
```

Receipt outcome grammar:

```text
web_profile_update:<actor-uuid>:<field>:<64-lowercase-hex-fingerprint>
```

- same derived update ID + exact marker/actor/field/fingerprint: success replay,
  no second profile update/audit/receipt;
- same derived update ID + any different field/value/actor or non-Web marker:
  `StaleRegistrationStepError` before mutation → HTTP `409 profile_unavailable`;
- first invalid value: existing `normalize_profile_value` error → `422`, receipt
  не создаётся.

Fingerprint проверяется до validation только при существующем receipt, поэтому
reuse уже завершённого key с любым другим command всегда conflict. Для новой
операции validation остаётся единственным owner правил значения.

## Conversation isolation oracle

Новый application/UoW path не импортирует и не вызывает conversation helpers.
Targeted integration test до вызова создаёт active `task` conversation state с
non-zero revision и payload, затем проверяет byte-for-byte равенство полей после
success, exact replay, conflict и validation failure. Отдельная concurrent
проверка запускает два updates разных profile fields и доказывает оба значения
при неизменной conversation row.

Telegram compatibility oracle вызывает существующие
`begin_profile_field_edit`/`save_profile_field` с прежними arguments и проверяет
прежние outcomes `profile_edit:<field>`/`profile_updated` и existing
`expected_input`. Их implementation/signatures не меняются.

## Exact HTTP delta

```text
PUT /api/v1/me/profile
Origin: <configured exact origin>
Idempotency-Key: <positive decimal>
Content-Type: application/json

{"field":"city","value":"Rosario"}
-> 200 <fresh authoritative MeDto>
```

Один request содержит ровно один existing `ProfileField` и строковое значение.
Body bounded existing limit, extra keys forbidden, actor только из secure session,
response/errors `Cache-Control: no-store`.

- no session: `401 unauthorized`;
- inactive/non-owner server actor: `403 profile_unavailable`;
- invalid JSON/field/value/body: `422 invalid_request`;
- same key/different command или чужой receipt marker: `409 profile_unavailable`.

Client не передаёт Telegram ID, member ID, revision или authorization claims.

## UI

На существующей profile card добавить hard-coded allowlist восьми existing
`ProfileField` с русскими labels и current values. Это локальный mapping, не
schema renderer. Одновременно открывается один native input/textarea; save
отправляет один `PUT` и сохраняет operation key при retryable network/5xx retry.

После `200` UI использует returned authoritative `MeDto`, перечитывает existing
safe member projection для согласованной card и показывает server value. `409`
закрывает старую попытку и требует нового save с новым key. DOM строится только
existing safe element/text helpers; back/focus и stale-screen guard сохраняются.

## Ponytail ceiling и файлы

Лестница остановилась на existing owners: `RegistrationService`, UoW,
`registration.py` DB setter, current Web mutation helpers и current profile card.
Новый service/repository/model/table/framework/dependency не нужен.

Production — ровно 5 existing files:

1. `src/community_bot/application/registration.py` — один new one-shot method,
   existing UoW protocol member/field setter declaration и small replay parser;
2. `src/community_bot/infrastructure/db/registration.py` — public wrapper вокруг
   existing `_set_member_profile_field`, без conversation access;
3. `src/community_bot/infrastructure/db/database.py` — thin UoW delegation;
4. `src/community_bot/transport/web.py` — request DTO, one PUT route, existing
   bounded/auth/origin/idempotency/fingerprint helpers, authoritative reread;
5. `src/community_bot/transport/static/app.js` — editor in existing profile card.

Tests — 4 existing files; это ниже owner ceiling `>5 test files` и является
минимумом без переноса unrelated assertions между test modules:

1. `tests/integration/test_web_api.py` — owner/replay/conflict/validation,
   conversation isolation, concurrent different fields, authoritative reread;
2. `tests/browser/test_mini_app.py` — happy path, stable retry key, validation,
   authoritative value, safe DOM and back/focus;
3. `tests/integration/test_registration.py` — exact unchanged Telegram method
   arguments/outcomes и `expected_input` compatibility oracle;
4. `tests/unit/test_web_auth.py` — обязательное literal closed route-set update
   для `PUT /api/v1/me`, без новой fixture или отдельной suite.

Ponytail stop/reconsider выполнен на планировании: объединять integration,
browser, Telegram compatibility и closed route assertions в чужих modules ради
line/file golf сделало бы тесты менее прямыми. Фактическая граница — 5 existing
production files и 4 existing test files, то есть ни одна категория не выходит
за owner trigger `>5 production/test files`; новых файлов реализации/тестов нет.
Stop сохраняется при выходе за 5 файлов в любой категории, примерно 300 net
production LOC, новой persistence, schema или domain rule. LOC ceiling не
отменяет security/accessibility.

## Именованные проверки

1. `test_web_profile_update_is_actor_native_exact_and_conversation_safe`:
   active owner success; fresh `/me`; exact receipt/audit; unrelated active
   conversation unchanged; invalid field/value; inactive actor; no client ID.
2. В том же scenario/subcases: identical retry leaves counts/state unchanged;
   same key different field/value conflicts before mutation; чужой Telegram
   outcome under derived update ID conflicts.
3. `test_concurrent_web_profile_field_updates_preserve_both_fields`: two unique
   keys and different fields; both committed; one audit/receipt each;
   conversation unchanged.
4. Existing Telegram profile integration test: exact old outcomes,
   `expected_input`, all eight existing fields green.
5. Existing browser profile journey: edit one field; first PUT network abort;
   retry same key; response provides authoritative changed value; validation
   state; literal rendering; focus/back; no foreign-profile mutation.
6. Targeted Ruff/type/tests, minimal Web smoke, secret-pattern scan,
   dependency/schema diff proof и independent final review.

## Исключённая область

Нет profile revision framework, staged editor, generic form/schema, registration,
karma voting, uploads/avatars, foreign profiles, новых fields/rules, tables,
migrations, models, repositories, services, dependencies или Telegram changes.

## Delivery и rollback

После approved plan: implementation → targeted verification →
`implementation-report.md` → independent approved final review → commit/push/PR
→ green CI/review → merge → exact immutable release → serialized production
activation → public profile-edit smoke → Jira evidence → `Готово`.

Rollback удаляет один service method, one UoW/DB delegation, one route и local UI
editor. Schema/data rollback отсутствует; completed profile values не откатываются
автоматически.
