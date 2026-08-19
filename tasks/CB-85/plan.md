# CB-85 — план реализации

## Риск и границы

- Уровень риска: `2`, потому что меняется клиентское удержание idempotency key при неопределённом результате.
- Область: только активная карточка назначения, transport DTO, основной Mini App task flow и минимальные существующие тесты.
- Не входят moderation actionability, terminal assignment history, templates/community, новые доменные правила, schema/migration/model/repository/service/dependency/framework и общий frontend state manager.
- Отдельная проверка плана не нужна: план не меняет concurrency, receipt, fingerprint или transaction contract движка. Он сохраняет исходную client operation identity и переиспользует действующие проверки; независимая итоговая проверка обязательна.

## Владельцы и минимальная правка

1. В `application/assignments.py` вывести bounded `can_submit`/`can_cancel` из существующей `AssignmentCard`: submission использует `require_submit_allowed`, cancellation повторно использует текущую проверку `AssignmentService.cancel`. Нового lifecycle rule нет.
2. В `transport/web.py` добавить эти два значения в существующий `AssignmentDetailDto`; ownership, active visibility, role/status, privacy и test-run scope остаются в `AssignmentService.active_card` и UoW.
3. В `transport/static/app.js` убрать status-based eligibility submission/cancel, рендерить действия только по server projection. Для task creation и accept удерживать тот же exact command/key после network, `5xx` или другого неопределённого результата; очищать после успешного либо определённого non-retryable ответа. После успешного accept перечитать authoritative assignment card.
4. В существующих integration/browser tests доказать deadline projection, подходящие действия, отсутствие client status allowlist, exact retry key/body и корректную ротацию после definite outcome; сохранить happy paths.

## Проверки

- Целевые unit/integration/browser tests изменённых сценариев.
- Ruff/форматирование и type gate по изменённой области, затем требуемый repository gate без широкой продуктовой регрессии.
- Проверка diff, секретоподобных значений и Ponytail ceiling.
- `implementation-report.md`, независимый `final-review.md` со `Status: approved`, затем commit/push/PR/CI/merge.
- После merge: green main CI, новый exact immutable release, manual-first production activation, public smoke области CB-85 и Jira evidence; `Готово` только после green smoke.

## Оракулы приёмки

- `accepted` после deadline получает `can_submit=false`; eligible freeform `accepted` получает `can_submit=true` и `can_cancel=true`.
- Клиент не использует `assignment_status` для показа submission/cancel.
- Task creation и accept повторяют тот же key и payload после network/`5xx`; success и nonretryable outcome очищают key.
- Existing server replay/conflict tests подтверждают отсутствие повторных state/ledger/audit/outbox effects.
- Active assignment, task creation и accept happy paths остаются зелёными; privacy/test-run/ownership не переносятся в UI.
