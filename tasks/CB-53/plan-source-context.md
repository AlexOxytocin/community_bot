# CB-53 — исходный контекст плана

## Jira, baseline и owner decisions

- `CB-53`, parent `CB-48`, status на 2026-08-17: `К выполнению`.
- `CB-52` merged: `ea8550f4255fb69f7e90828d6b38454f6a743d80`, PR `#65`,
  CI green, Jira `Done`. Это runtime baseline.
- `CB-58` `Done`; reuse tokens, accessibility direction и local Manrope.
- Jira comment `10239` фиксирует owner-approved DTO delta; `10240` и `10242`
  — review blockers; `10241` — предыдущая consolidated revision; `10243`
  фиксирует owner-authorized post-terminal resolution и новый review gate.
- Последний owner decision «да одобряю, и делегирую тебе принимать такие решения
  самому»: минимальные safe transport/integration решения разрешены без
  product/domain changes; table/integration/architecture/product/economy и
  security weakening остаются owner gate.

Status/description Jira и runtime branch до approved plan review не меняются.

## Канонические источники

Прочитаны project guardrails и условные Jira/product/domain/architecture/
multi-agent/release документы, релевантные ADR-0014/0016/0017, global agent
budget, Ponytail/Ponytail-audit instructions, CB-58 artifacts и actual
`origin/main` source/tests. Приоритет: guardrails → Jira/owner decisions →
accepted ADR/product docs → actual source.

## Merged CB-52 contract

CB-52 даёт auth/session и read-only `/me`, `/members`, `/tasks`,
`/leaderboard`; `web_sessions`; zero domain mutations. Cookie:
`__Host-community_session; Secure; HttpOnly; SameSite=Strict`. Resolver
возвращает server-side `ActorContext(member_id, provider, authenticated_at)`.
Unsafe boundary требует exact configured HTTPS Origin. Generic HTTP operation
receipt отсутствует.

## Catalog/detail evidence

- Existing `TaskService.list_available`/DB query владеют eligibility.
- Merged `TaskDto` — allowlisted summary, но данных информированной карточки
  недостаточно.
- `PublishedTask` уже содержит approved detail fields.
- Performer-facing detail owner отсутствует. Поэтому карточка только из
  selected enriched catalog item in memory; deep-link/reload и
  `GET /api/v1/tasks/{task_id}` out.
- Owner разрешил расширить только existing `TaskDto`/`_task_dto`:
  `description`, `completion_criteria`, `performer_instructions`,
  `materials`, `public_input`. Последний — только allowlist intersection
  `public_input_keys`/raw payload; private/unknown keys не выходят.

## Accept/replay/privacy evidence

- Mutation owner: `AssignmentService.accept_with_task`; он уже владеет всеми
  permission/visibility/status/level/deadline/limit/slot rules, locks,
  assignment/reliability/outbox transaction.
- Owner делает existing update gate + receipt lookup до actor/current authority,
  поэтому committed replay переживает последующую смену actor status.
- `processed_telegram_updates.update_id BIGINT` — global primary key; lookup
  идёт только по `update_id`. Raw одинаковый browser key разных members мог бы
  replay чужой outcome.
- Owner-approved correction: length-encode tuple
  `accept + member UUID bytes + task UUID bytes + canonical key ASCII`, stdlib
  SHA-256, first 8 bytes big-endian, positive 63-bit, zero → one. Только derived
  id идёт owner. Нет secret/config/table/migration/codec class/domain rule.
- Receipt schema/fingerprint не расширяются. После replay assignment actor/task
  сверяются с session/command; mismatch/collision → privacy-safe 409/no effects.
- Unique `(task_id, performer_id)` — natural idempotency resource. После
  existing actor/task gates active row возвращается без new effects;
  terminal/cancelled → 409. Task gate исключает duplicate IntegrityError как
  normal control flow для concurrent different keys.
- Existing UoW имеет `append_audit_event`; один allowlisted accept marker
  добавляется атомарно без изменения business outcome.

## Exact transport decisions

1. Exact single Origin → CB-52 session/auth → exact canonical single
   `Idempotency-Key` → manual UUID/empty-body validation → owner.
2. Key `[1-9][0-9]{0,18}`, range `1..9223372036854775807`; any missing/
   malformed/out-of-range/duplicate → 422/zero effects.
3. Expected `LookupError`, `PermissionError`, `AssignmentError` и existing
   transport-neutral equivalents → one `409 assignment_unavailable`; no
   message parsing/predicate duplication.
4. Unexpected infra → generic 500/no-store/rollback.
5. Materials URL/text literal `textContent`; external links out.
6. Catalog data never enters `href/src`/event attribute/HTML sink.
7. Mapper принимает public allowlist только как list/tuple всех string keys;
   missing/malformed/non-string → empty, никогда raw-payload fallback.

## Ponytail reduction и budgets

Только catalog → in-memory detail → accept → confirmed. Profiles, reputation,
history, registration writes, member directory, admin, completion/review и
framework abstractions удалены. Hard: zero domain rewrite; one POST/no detail
GET; zero tables/migrations/dependencies/abstractions; security/privacy/data
integrity. LOC/files/tests — soft trigger: target 8 text files/800 production
LOC; один короткий audit, no line-golf.

## Independent evidence и state

Read-only backend explorer подтвердил owner/locks/replay. UX/Ponytail reviewer
подтвердил две surfaces и CB-58 reuse. Предыдущий independent recheck был
`changes_requested`; owner resolution `10243` закрывает operation identity,
duplicate-resource и fail-open privacy findings. До нового independent
`Status: approved` runtime/branch запрещены.

## Runtime checkpoint 2026-08-17

Owner-authorized independent recheck завершён `Status: approved`. Runtime
baseline подтверждён как `origin/main@ea8550f4255fb69f7e90828d6b38454f6a743d80`;
создана ветка `task/CB-53`. Jira description заменён approved narrow scope,
status переведён точным transition `21` в `В работе`. Implementation не
добавляет table/migration/detail owner/CB-54 behavior.
