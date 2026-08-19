# CB-82 — план реализации

## Уровень и цель

Уровень 3: интеграционный Web write затрагивает identity, authorization,
privacy, idempotency и concurrency. Цель — подключить один существующий member
profile flow к уже работающему `ReputationService`, не развивая движок и не
меняя domain/schema.

## Контракт

1. Существующий `GET /api/v1/members/{member_id}` остаётся единственным safe
   profile read.
2. Добавляется один компактный endpoint
   `POST /api/v1/members/{member_id}/karma-vote` с закрытыми действиями
   `begin|save_value|save_comment|confirm`.
3. Actor берётся только из `current_actor`; тело не принимает actor,
   `telegram_user_id`, role, status или permissions. Path target считается
   недоверенным и на каждом action сопоставляется с server-owned draft/locks.
4. `begin` проверяет active actor/target, self-vote, moderation restriction и
   permanent eligibility через существующий `ReputationService`.
5. `save_value`, `save_comment` и `confirm` используют exact target и
   `expected_revision`; stale revision/foreign target дают privacy-safe `409`
   без mutation.
6. Receipt scope для всех четырёх actions вычисляется только из constant
   namespace `karma-vote-v1`, authenticated `actor_id` и external
   `Idempotency-Key`. При reuse `_submission_update_id` его `resource_id` и
   `operation` передаются как server-owned constants; action и path target не
   участвуют в receipt identity. Canonical fingerprint включает action, path
   target, expected revision и action-specific value/comment. Тот же scoped
   key с любым другим fingerprint даёт privacy-safe `409` без нового эффекта.
7. Receipt хранит versioned safe outcome `karma_web_v1` без raw value/comment:
   для `begin|save_*` — target/step/revision/fingerprint, для `confirm` —
   target/vote revision/score/count/fingerprint. Exact replay парсит этот
   сохранённый outcome и возвращает тот же action response даже после advance
   или удаления draft; он не перечитывает current draft/aggregate.
8. После успешного exact confirm response UI отдельно перечитывает существующий
   `GET /api/v1/members/{member_id}`. Этот read не является частью immutable
   mutation outcome: он даёт authoritative current safe profile/aggregate и
   заменяет карточку. Draft/value/comment удаляются из UI state до reread;
   ошибка reread предлагает только безопасный retry GET, не повтор confirm.

## Минимальная реализация Ponytail

1. В `src/community_bot/infrastructure/db/reputation.py` добавить локальный
   fail-closed guard: `begin_draft` не вызывает общий claim для любого
   существующего non-karma flow. Не менять `conversations.py`, список owners,
   таблицы или модели.
2. В `src/community_bot/application/reputation.py` добавить тонкое разрешение
   actor-native identity в существующие четыре use cases и Web fingerprint/
   versioned-outcome replay validation в уже существующем receipt. Actor-native
   path после DB actor lookup использует тот же identity gate и lock order, что
   legacy path. Перед confirm заново проверить current actor/target status,
   eligibility и `RestrictedAction.KARMA_VOTE`. Общая draft/upsert/signals/
   audit/aggregate последовательность остаётся одной; второй service/engine не
   создаётся.
3. В `src/community_bot/transport/web.py` добавить один strict request DTO,
   один safe action-response DTO и один route. Для operation ID использовать
   constant resource/operation scope; target входит только в fingerprint и
   server validation. Использовать существующие origin/body/key/fingerprint/
   update-id/error helpers; не добавлять dependency, middleware, generic action
   router или form framework.
4. В `src/community_bot/transport/static/app.js` сделать leaderboard row
   кнопкой safe member profile, показать существующий safe projection и одну
   минимальную karma form. Стабильный operation key сохранять только для retry
   текущего action; при изменении payload создавать новый. После confirm
   очистить form/comment state, выполнить отдельный authoritative safe-profile
   GET и заменить карточку; сообщить результат через `aria-live`.
5. CSS менять только если существующих `card`, `detail`, `task-form`, `status`
   недостаточно; новых frontend modules/state manager не создавать.

## Проверки

### Application/DB

- eligibility: paid member assignment разрешает begin; self/ineligible/
  non-active/restricted actor или target отклоняются;
- revision/target: stale revision и target mismatch не меняют draft;
- exact replay/conflict: delayed replay каждого `begin|save_value|save_comment|
  confirm` после следующего action или удаления draft возвращает сохранённый
  safe response; один key с другим action, target, revision или payload даёт
  conflict без нового receipt/domain effect;
- confirm: один current vote/history/audit/receipt/signals outcome, повтор не
  дублирует, aggregate соответствует current vote;
- reauthorization: status/restriction change после draft блокирует confirm без
  vote/history/audit/signal/receipt effect и без потери draft;
- concurrency: два confirm одной revision дают один winner/effect; Web/legacy
  begin/confirm сохраняют единый identity gate/lock order без overwrite/deadlock;
- foreign flow: table-driven `task`, `assignment_result`,
  `assignment_dispute`, `profile_edit` сохраняют exact flow/step/payload/
  revision после rejected begin.

### API/privacy

- auth cookie actor побеждает любые client hints; actor fields запрещены
  closed schema;
- path target повторно проверяется server-side на каждом action;
- invalid content type/body/key/action/revision/value/comment дают только
  allowlisted generic codes, без comment/private fields;
- absent и hidden/non-active target дают одинаковые status/body;
- response schemas не содержат raw author/comment/history, Telegram ID,
  чужой balance, sanctions или audit; confirm возвращает reread aggregate.

### Browser

- leaderboard → safe member profile → begin/value/comment/confirm → отдельный
  authoritative profile GET → обновлённая aggregate;
- lost-response retry повторяет тот же operation key и не дублирует effect;
- stale/conflict показывает понятный status и допускает безопасный reread;
- comment не вставляется через `innerHTML`, не остаётся после confirm/navigation
  и не появляется в visible error/status; loading/error/retry и stale screen
  revision не перерисовывают ушедший экран;
- keyboard flow, labels, focus return и `aria-live` сохраняются.

### Gates

- быстрые targeted unit/integration/browser tests с coverage изменённых
  runtime-модулей;
- один необходимый integration gate, Ruff, ty и основной CI набор по принятому
  workflow;
- diff/privacy/secret scan и независимый final review;
- после merge: green main CI → новый exact release artifact → manual-first
  compatible activation → public smoke из `test-plan.md` → Jira evidence →
  только затем переход `Готово`.

## Не входит

Новые rules/tables/migrations/models/repositories/services/dependencies,
notifications/signals, admin raw karma, member search/recommendations, generic
forms, frontend framework/state manager и любое восстановление Telegram UI.

## Риски и stop gates

- Если actor-native reuse потребует нового persistence owner, schema/domain
  change или второго operation store — остановить runtime и вернуть blocker.
- Если existing receipt outcome нельзя расширить для versioned safe exact Web
  replay/conflict без изменения таблицы, остановить runtime; не ослаблять
  idempotency и не подменять exact replay current reread.
- Любой migration diff перед delivery требует отдельного owner gate; план
  миграций не содержит.
