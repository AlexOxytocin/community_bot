# CB-74 — контекст источников и mapping

## Состояние после второго fresh remap 2026-08-18

- Jira `CB-74`: «К выполнению», комментариев и формальных issue links нет; родитель — `CB-48`.
- `CB-70`: merged/deployed/Jira Done; fresh fetch подтвердил `origin/main = d1733cb49ff59a74e893320c19c15d58102b2045` (merge PR #80).
- `CB-73`: merged как PR #81 в exact `origin/main = 95b0da6917c0ba41770be700e12195d50f21a34b`; release `81/1` активирован, public smoke green, Jira Done по owner handoff.
- Рабочий `HEAD` намеренно остаётся detached на `b5a5648` до завершения focused plan review; ветка `task/CB-74` ещё не создана.

Фактический CB-73 diff снял dependency gate и изменил точные reuse seams:

- `src/community_bot/application/assignments.py`: `DecideAssignmentCommand` теперь actor-native; web replay повторно проверяет owner/test-run scope, а `_finish()` хранит scoped web outcome;
- `src/community_bot/transport/web.py`: добавлены `AssignmentReviewDto`, `AssignmentDecisionRequest` и `/api/v1/assignment-reviews/*`; performer detail остаётся `/api/v1/assignments/{id}`;
- `src/community_bot/transport/static/app.js`: «Мои задания» разделены на «Взятые мной»/«Созданные мной», добавлены creator decision UI и общий `submissionRequest()`;
- `tests/integration/test_web_api.py` и `tests/browser/test_mini_app.py`: общие contract и critical-path fixtures.

`CB-73` теперь создаёт непосредственный входной state CB-74 — `REJECTED_PENDING_DISPUTE` с server-owned 24h deadline. CB-74 может встроиться в уже принятый performer detail и reuse actor-native replay pattern без creator DTO или нового navigation layer.

## Изменение web seam в CB-70

- Domain/application/DB dispute owner и assignment read/write contracts не изменились.
- `_submission_update_id()` получил параметр `namespace`; task creation уже переиспользует его с отдельным `b"task-creation-v1"`.
- `_submission_fingerprint()` переиспользован для другого web workflow, а `_json_response()` теперь принимает DTO либо безопасно кодируемый object.
- Assignment list/detail, submission retry и `.submission` styles семантически сохранены; добавленный task-creation UI только сдвинул позиции в `app.js`/`web.py`.

Для CB-74 это реальное улучшение reuse seam, а не изменение domain-контракта: dispute использует тот же operation-id helper с отдельным namespace и тот же canonical fingerprint, без нового helper/framework. Сам CB-70 не требовал менять ceiling; итоговый ceiling уточнён выше уже по фактическому CB-73 overlap.

## Фактический lifecycle после `REJECT`

1. `AssignmentService.decide()` вызывает существующий `set_assignment_decision()`.
2. `AssignmentDecision.REJECT` переводит assignment в `REJECTED_PENDING_DISPUTE`; DB owner записывает `rejected_at` и `reject_dispute_deadline_at = rejected_at + 24h`.
3. `domain.assignments.require_dispute_allowed()` — единственный владелец eligibility: допускается только `REJECTED_PENDING_DISPUTE` и полуоткрытый интервал `rejected_at <= now < reject_dispute_deadline_at`.
4. `AssignmentService.dispute()` повторно проверяет active performer ownership, берёт task aggregate lock, повторно загружает assignment и вызывает тот же domain guard.
5. `infrastructure.db.assignments.open_dispute()` идемпотентно по `open_command_id` и exact comment создаёт private `assignment_disputes` handoff и `moderation_cases(case_type="dispute", status="open")`, затем переводит assignment в `DISPUTED`.
6. Application добавляет privacy-minimal `assignment_disputed` outbox и operation receipt в той же транзакции. Private comment не попадает в outbox. На открытии спора ledger, reliability и `audit_events` не меняются; эти effects принадлежат последующему moderation resolution lifecycle. Текущий dispute→resolution scenario трассирует owner, но пока не содержит прямого `AuditEventModel` oracle — CB-74 добавит его без изменения поведения.
7. `finalize_rejection()` допускается только после deadline и только пока status остаётся `REJECTED_PENDING_DISPUTE`; открытый спор тем самым блокирует undisputed finalization.

## Ownership, privacy и test-run scope

- Read seam `active_card(actor, assignment_id)` повторно загружает active member и возвращает только performer-owned assignment.
- DB projections `get_assignment_card()`/`list_assignment_cards()` фильтруют normal/test-run scope через `active_scope()`; direct mutation дополнительно должна вызвать существующий `ensure_task_test_access()` внутри locked application transaction.
- `AssignmentCardDto` уже содержит `assignment_status`, `reject_dispute_deadline_at`, `result_summary` и `case_status`; private dispute comment/reason/evidence в performer DTO не выдаются.
- Honest states должны опираться на server-owned projection: `available` определяется существующим domain guard; `opened` — `DISPUTED`/`case_status`; `expired` — pending status при отрицательной server eligibility. После resolution terminal assignment исчезает из active performer projection и detail честно возвращает privacy-safe `404/not active`; CB-74 не добавляет historical read seam. Foreign/test-run-hidden assignment имеет тот же непрозрачный read/mutation outcome и не изменяется.

## Существующие web seams для переиспользования

- `POST` mutations в `transport/web.py`: same-origin check, bounded body, canonical UUID, `Idempotency-Key`, `_submission_update_id(..., namespace=...)`, canonical `_submission_fingerprint()`, generic privacy-safe error code.
- `application.assignments`: transport-neutral `ActorContext.member_id` path и exact replay pattern уже используются submission commands.
- `static/app.js`: assignment detail, `newOperationKey()`, retry с сохранением ключа, `submissionResponse()` и live status boundary уже существуют.
- Tests: `tests/integration/test_assignments.py::test_reject_then_dispute_persists_private_handoff`, `tests/integration/test_core_workflows.py::test_dispute_resolution_preserves_ledger_and_audit`, web exact replay/conflict tests и browser assignment-detail flow.

## Контрактные ограничения

- Не вводить новое dispute rule, срок, table, migration, model, repository, service, framework или dependency.
- Не переносить eligibility/ownership/test scope в JavaScript или DTO builder.
- Не показывать private comment, moderation reason/evidence или чужие assignments.
- Exact replay до возврата stored outcome повторно проверяет active actor, performer ownership и текущий test-run scope; затем возвращает прежний outcome без второго dispute/case/outbox/receipt. Тот же operation key с другим comment даёт conflict без эффектов.
- ADR не требуется: план расширяет принятый transport seam поверх существующего application/domain owner и не меняет структуру системы.

## Прочитанные источники

- live Jira `CB-70`, `CB-73`, `CB-74` и fetched `origin/main` `95b0da6917c0ba41770be700e12195d50f21a34b`;
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`;
- `docs/mvp/README.md`, `01_PRODUCT_REQUIREMENTS.md`, `02_DOMAIN_RULES.md`, `TECH_STACK.md`, `11_DECISIONS_AND_OPEN_QUESTIONS.md`;
- `docs/release-2/README.md`, ADR-0014, ADR-0017 и индекс ADR;
- перечисленные domain/application/DB/web/static/test файлы текущего snapshot.
