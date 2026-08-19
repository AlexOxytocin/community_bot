# CB-81 — контекст и источники плана

## Jira и owner decision

- `CB-81`: редактирование одного existing profile field на текущем Mini App
  экране через существующий backend.
- Initial review `Status: changes_requested` правильно остановил staged
  conversation reuse до runtime diff.
- Owner decision после stop gate: отдельную Jira-задачу не создавать; разрешён
  ровно one-shot `RegistrationService` Web command без любого доступа к
  `conversation_states`; staged Telegram methods и semantics неизменны.
- Разрешён reuse `ProfileField`, `normalize_profile_value`,
  `require_profile_owner`, identity/member locks, existing single-field DB setter,
  audit/receipt/idempotency machinery и authoritative `/me` reread.
- Обязательные oracles: сохранность чужого active conversation flow и concurrent
  updates разных fields без lost update.

## Канонические sources

- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`;
- `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md`;
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md`, `02_DOMAIN_RULES.md`, `TECH_STACK.md`,
  `11_DECISIONS_AND_OPEN_QUESTIONS.md`;
- `docs/release-2/README.md`, ADR-0016, ADR-0018, ADR-0019;
- `agents/config.yaml`, `agents/workflow.yaml`, plan/final reviewer instructions;
- Ponytail `full`: existing code/platform first, no abstraction/dependency.

## Факты exact base и mapping

- Branch `task/CB-81` основана на fresh `origin/main`
  `7981d5b222843c9e8eda219b0244be2077f55635`.
- До нового plan review изменены только `tasks/CB-81/*`; runtime/tests untouched.
- `RegistrationService` already owns registration/profile UoW factory, receipt,
  audit and `own_profile` authoritative read.
- `ProfileField` and `normalize_profile_value` already define all eight fields and
  complete server validation.
- `require_profile_owner`, `get_member(member_id)`,
  `acquire_registration_identity_gate`, `lock_members`, `acquire_update_gate`,
  `get_receipt_outcome`, `add_registration_receipt`, `append_audit_event` and
  `commit` already exist on current UoW/implementation.
- `infrastructure/db/registration.py::_set_member_profile_field` already maps one
  `ProfileField` to one ORM attribute. Existing `save_profile_edit` uses it only
  after conversation checks; the new thin public DB wrapper can reuse the setter
  directly without importing conversation storage.
- Existing Web mutations already derive namespaced numeric update IDs and
  canonical SHA-256 fingerprints, encode typed replay markers in existing receipt
  outcomes and reject marker/fingerprint mismatch without schema change.
- `/api/v1/me`, `MeDto`, secure actor session, Origin check, bounded JSON,
  `Idempotency-Key`, no-store and profile screen/browser test already exist.

## Почему stop gate снят

Initial plan требовал изменить conversation revision/ownership semantics. Новый
command вообще не зависит от conversation state: one locked ORM field update,
existing receipt replay and fresh `/me`. Поэтому он не меняет Telegram flow,
shared text-flow owner или persistence schema и соответствует owner-approved
thin adapter.

Exact replay не требует новой persistence: existing receipt outcome достаточно
для closed marker `web_profile_update:actor:field:fingerprint`, как в existing Web
task/assignment replay contracts.

## Ограничения

- Не изменять `begin_profile_field_edit`, `save_profile_field`, their callers,
  outcomes or conversation behavior.
- Новый path не может ссылаться на conversation model/store/helper.
- Не добавлять revision, state table, model, migration, repository, service,
  dependency, framework, schema renderer or client identity.
- Не более 5 production и 5 targeted test files; exact plan использует 5
  production и 4 existing test files. Это буквальная граница owner trigger
  `>5 production/test files`, применённая отдельно к каждой категории; около
  300 net production LOC — дополнительный stop/reconsider threshold.
- При невозможности typed exact replay в existing receipt outcome задача снова
  останавливается до runtime diff.

## Открытые вопросы

Product/domain вопросов нет. Release run/manifest/image/public URL выбираются по
existing ADR-0018/0019 runbook только после green merge; schema gate отсутствует,
поскольку migration/schema diff запрещён.
