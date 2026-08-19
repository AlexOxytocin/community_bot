# CB-82 — исходный контекст плана

## Jira

- Jira `CB-82`: «Mini App: оценка кармы через существующий ReputationService».
- Статус на 2026-08-18: `В работе`; комментариев, вложений, связей, родителя и
  блокирующих зависимостей нет.
- Основной путь: safe profile участника → значение и комментарий → confirm →
  authoritative reread safe profile/karma aggregate.
- Обязательные ограничения: actor только из Web session, target повторно
  проверяется сервером; существующие eligibility, draft/revision, receipt,
  audit, signals и aggregate переиспользуются; raw karma и приватные поля не
  выдаются; Telegram legacy path не получает отдельный engine.

## Процесс и принятые решения

- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`: Jira-first, ветка
  `task/CB-82`, Ponytail full, независимые plan/final review, delivery gate.
- ADR-0004 и ADR-0010: задача относится к уровню 3, потому что затрагивает
  identity, authorization, privacy, idempotency и concurrency; fast lane
  неприменим.
- ADR-0014, ADR-0016 и D-033: Web proof разрешается во внутренний
  `ActorContext`; status/permissions/ownership перечитываются из PostgreSQL;
  HTTP operation identity не доверяет клиентскому actor и не создаёт второй
  backend.
- ADR-0017: native HTML/CSS/JS и существующий feature-oriented монолит;
  dependencies, frontend framework, generic form/state layer и новая
  persistence abstraction запрещены без доказанной необходимости.
- ADR-0018 и ADR-0019: после merge нужен новый exact immutable artifact,
  manual-first compatible activation и public smoke; Jira `Done` до green
  public smoke запрещён.
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md`, D-020—D-022 и
  `docs/mvp/02_DOMAIN_RULES.md`: одна текущая оценка `-1|0|1`, обязательный
  комментарий 10–300 символов, permanent eligibility только после paid member
  assignment, оба участника `active`, self-vote запрещён, получатель видит
  только aggregate.
- `docs/mvp/07_SECURITY_AND_PRIVACY.md`: safe profile не содержит Telegram ID,
  чужой баланс, raw karma authors/comments/history, sanctions или audit;
  одинаковый отказ не раскрывает hidden target.

## Read-only mapping от fresh origin/main

- Fresh `origin/main` и исходный HEAD совпадают:
  `dfaabe091797f4120db8d58144ae8efd9815aeba`.
- `src/community_bot/application/reputation.py` уже владеет
  `begin_vote`, `save_value`, `save_comment`, `confirm_vote`, eligibility,
  current member/status checks, pair/update/identity locks, audit, signals,
  revision и Telegram receipt semantics.
- `src/community_bot/infrastructure/db/reputation.py` и
  `Database` уже владеют karma draft, current vote/history, aggregate и safe
  profile. Новая таблица, model, repository, service или migration не нужны.
- `src/community_bot/transport/web.py` уже разрешает HttpOnly session cookie в
  `ActorContext`, проверяет same-origin, strict JSON, bounded body и
  `Idempotency-Key`, а `_submission_update_id`/`_submission_fingerprint`
  дают существующий Web seam для receipt replay/conflict.
- `src/community_bot/transport/static/app.js` уже показывает own safe profile
  и leaderboard; строки leaderboard пока не открывают чужой safe profile.
- `tests/integration/test_reputation.py`, `tests/integration/test_web_api.py`,
  `tests/unit/test_web_auth.py` и `tests/browser/test_mini_app.py` содержат
  ближайшие transaction/API/privacy/retry/browser oracles.

## Обязательная проверка foreign flow

`begin_draft` блокирует `ConversationStateModel` и при любом non-karma state
вызывает `claim_text_flow`. Общий `claim_text_flow` защищает только
`registration`, `registration_paused` и `profile_edit`; поэтому существующие
`task`, `assignment_result` и `assignment_dispute` сейчас могут быть заменены
на `karma`. Имеющийся integration test доказывает только `profile_edit` и не
закрывает остальные owners.

Безопасный минимальный вывод: новый owner или domain change не требуется.
Karma persistence должна fail-closed отклонять любой существующий foreign
`flow_type` до вызова `claim_text_flow`; exact foreign row остаётся неизменной.
Общий conversation policy и другие callers не меняются. Это исправляет
фактическое нарушение docstring `begin_vote` без восстановления Telegram UI.

## Границы решения

- Один actor-native seam внутри существующего `ReputationService`: Web передаёт
  только server-created `ActorContext`; прежний Telegram-shaped caller остаётся
  совместимым и использует те же transaction methods, identity gate и lock
  order. Current restriction/status/eligibility повторно проверяются на confirm.
- Один resource/action endpoint для `begin`, `save_value`, `save_comment`,
  `confirm`; action payload закрытый и action-specific, без generic schema.
- Draft response содержит только target/step/revision. Собственный ввод живёт
  только в form controls и очищается после confirm; stored raw karma rows,
  authors/history и чужие comments никогда не сериализуются, не рендерятся и
  не попадают в ошибки или логи.
- Receipt scope literal: constant `karma-vote-v1` + authenticated actor +
  external key. Action/target/revision/payload входят в fingerprint, поэтому
  смена action или target не разводит receipts.
- Versioned receipt outcome хранит только safe action response. Delayed replay
  не читает current draft или aggregate. После confirm UI отдельным GET читает
  existing safe profile; immutable mutation outcome и fresh authoritative read
  намеренно разведены.
- ADR не нужен: используются уже принятые identity, receipt, reputation и
  delivery contracts; структурная форма системы не меняется.
