# CB-74 — план подачи спора через Mini App

## Статус и уровень риска

Уровень 3: mutation затрагивает ownership, privacy, test-run isolation и exact replay. Dependency gates сняты; fresh remap выполнен на exact `origin/main` `95b0da6917c0ba41770be700e12195d50f21a34b`. ADR не нужен.

## Результат

Исполнитель открывает своё отклонённое назначение, видит server-owned состояние и deadline, вводит обязательный комментарий и одним явным подтверждением вызывает существующий dispute lifecycle. Повтор того же запроса не создаёт новых эффектов; конфликтующий replay, чужой/скрытый assignment, закрытое окно и уже открытый спор завершаются без изменений.

## Reuse list

1. `require_dispute_allowed()` — status и полуоткрытое 24h-окно.
2. `AssignmentService.dispute()` + `open_assignment_dispute()` — ownership, lock, private handoff, moderation case и переход `DISPUTED`.
3. `ensure_task_test_access()` и assignment-card scope filter — test-run isolation.
4. Existing receipt, `_submission_update_id(..., namespace=...)`, `_submission_fingerprint()`, same-origin, bounded-body и canonical-UUID patterns из submission/task-creation web flows — exact replay/conflict без нового helper.
5. Existing assignment detail, `newOperationKey()`, request/retry helpers и submission form/status styles — UI без нового framework/component layer.
6. CB-73 actor-native decision replay (`_command_actor()`, scope recheck, scoped receipt outcome) — непосредственный минимальный образец web dispute path.
7. Existing integration scenario dispute→moderation resolution — owner downstream ledger/audit effects; план добавляет недостающий прямой audit oracle, не новый effect.

## План изменения после снятия gate

1. **Fresh remap и stop-check.** Выполнено на `95b0da6917c0ba41770be700e12195d50f21a34b`: CB-73 merged, dispute owner не изменён, performer detail и creator decision seams совместимы с этим планом. После focused review создать `task/CB-74` прямо от этого commit.
2. **Application owner.** Минимально расширить существующий `AssignmentService.dispute()` для optional internal `member_id` и web replay fingerprint, сохранив Telegram-compatible вызов и его порядок действий. Только для web path сначала разрешить active actor и взять существующий transaction-scoped `acquire_task_identity_gate(actor.telegram_user_id)`, затем под этим gate вызвать receipt `_begin()`: два одновременных запроса одного actor сериализуют первый receipt read. До возврата stored outcome повторно проверить active actor, performer ownership, текущий `ensure_task_test_access()` и fingerprint; новый locked path выполняет те же проверки и затем применяет существующий domain guard. Сохранить один scoped receipt outcome, один private handoff, один moderation case и один privacy-minimal outbox; не добавлять ledger, reliability или `audit_events` effect при открытии.
3. **HTTP seam.** Добавить один `POST /api/v1/assignments/{assignment_id}/disputes` с `{comment}`: same-origin, current session, bounded JSON, typed UUID path, `Idempotency-Key`, `_submission_update_id(..., namespace=b"assignment-dispute-v1")` и `_submission_fingerprint()`. DTO boundary нормализует `comment.strip()` и отклоняет missing/empty/whitespace-only input как `422 {"code":"invalid_request"}` до owner call. Успех — `204`; foreign/hidden/closed/expired/already-disputed/conflict mutation — единый privacy-safe `409 {"code":"assignment_unavailable"}` по принятому CB-73 seam. Performer detail GET сохраняет отдельный существующий privacy contract `404 {"code":"not_found"}`.
4. **Server-owned detail state.** Расширить только `AssignmentDetailDto` минимальным `can_dispute: bool`, рассчитанным existing application/domain owner; `AssignmentCardDto` list и новые CB-73 creator DTO не менять. `false` вместе с existing status/case/deadline различает expired и opened без копирования deadline rule в frontend. Closed contract остаётся существующим: после resolution terminal assignment исключён из active projection, refresh получает privacy-safe `404/not active`; historical read не добавляется.
5. **Mini App.** В существующий `showAssignmentDetail()` для «Взятые мной» добавить deadline/условия и одну dispute form только при `can_dispute`. Переиспользовать `submissionRequest()`, retry classification, `newOperationKey()` и `.submission-form`; CB-73 creator decision UI не менять. После `204` или `409` повторно загрузить performer detail и честно показать opened/expired; terminal `404` использует существующее «назначение больше не входит в активные».
6. **Targeted verification.** Расширить один web integration scenario: timely success; sequential exact replay; same-key/different-comment conflict; два одновременных exact POST дают `204/204`; одновременные same-key/different-comment дают один `204` и один `409`; deadline boundary; already disputed; foreign и test-run-hidden direct POST; replay после смены active test-run scope. Для replay/concurrency подтвердить итоговые counts `1 dispute + 1 case + 1 outbox + 1 receipt`, `0` duplicate/ledger/reliability/audit effects на opening и отсутствие private comment в response/outbox. Missing/empty/whitespace-only comment дают `422` и нулевые receipt/domain/outbox effects; foreign/hidden mutation точно дают `409 assignment_unavailable`. Exact replay после смены scope обязан отказать после повторной проверки active actor/ownership/scope и не добавить ни одного эффекта. В existing dispute→resolution scenario добавить точный audit oracle: ожидаемые `action`, `entity_type`, `entity_id`, count и неизменность при replay. Расширить один browser critical-path test: rejected detail → условия/deadline → confirm → `DISPUTED`; проверить expired, already-open и terminal `404/not active` states в той же компактной fixture boundary.
7. **После реализации.** Targeted unit/integration/browser checks, secret scan, `implementation-report.md`, независимый final review с Ponytail review, затем commit/push/PR/CI/merge. После green `main`: новый immutable release, production activation и public smoke этого пути; только затем Jira evidence и возможный `Done`.

## Числовой diff ceiling

- runtime + tests: не более **400 добавленных** и **40 удалённых** строк;
- не более **7 runtime/test файлов**: `application/assignments.py` (до 80 добавленных строк), `transport/web.py` (до 60), `transport/static/app.js` (до 70), `tests/integration/test_web_api.py` (до 125), `tests/browser/test_mini_app.py` (до 45), `tests/integration/test_core_workflows.py` (до 10 на audit oracle), `tests/unit/test_web_auth.py` (до 10 на closed route-set/DTO boundary);
- **0** новых dependencies, migrations, tables, models, repositories, services, frameworks и ADR.

Ceiling диагностический, не цель уплотнения. При превышении остановиться и один раз зафиксировать concrete blocker с недостающими обязанностями; не запрашивать approval, не скрывать объём механическим сжатием и не дробить один контракт по фиктивным задачам.

## Stop gates

- Актуальный `main` больше не содержит одного существующего dispute owner/command или требует schema change.
- Для eligibility приходится копировать срок/status rule в web/JS.
- Для mutation требуется новый storage/model/repository/service или изменение moderation resolution, appeals, sanctions либо экономики.
- Exact replay/conflict нельзя обеспечить существующим receipt seam без сквозного redesign.
- Private dispute data появляется в performer response, outbox, логах или browser fixture.
- Diff ceiling превышен либо targeted test требует несоразмерного framework/scaffolding.

## Приёмка и доказательство

| Критерий | Реализация | Проверка |
|---|---|---|
| Только владелец и только в открытом окне | locked application ownership + test scope + `require_dispute_allowed()` | success/foreign/hidden/deadline integration cases |
| Exact replay, conflict, zero duplicates | existing receipt + stable command/fingerprint; active actor/ownership/test scope recheck before replay return | повтор, same-key/different-comment и replay после смены scope, DB counts |
| Private handoff без утечки | existing dispute/case owner + minimal DTO/outbox | response/outbox denylist и browser fixture без private fields |
| Honest expired/opened/closed UI | server `can_dispute` + existing status/case/deadline; terminal closed = existing privacy-safe `404/not active` | web contract + browser states |
| Сохранён downstream lifecycle | existing moderation case and resolution owner | targeted dispute→resolution scenario с exact audit oracle |
| Никакой новой архитектуры | reuse list и ceiling | diff review/Ponytail review |

## Не входит

Moderator decision, evidence upload, appeals, sanctions, новые уведомления, изменение 24h, новая экономика, история terminal assignments, generic action schema и полный продуктовый regression.
