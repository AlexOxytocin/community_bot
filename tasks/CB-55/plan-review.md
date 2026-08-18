# CB-55 — повторное независимое ревью плана

Schema: `community_bot.plan_review.verdict.v1`

Status: approved

## Проверенные источники (`reviewed_sources`)

- Полностью прочитаны `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`,
  `agents/plan-reviewer/instruction.md`, `tasks/CB-55/plan-source-context.md`,
  `tasks/CB-55/plan.md`, `docs/mvp/01_PRODUCT_REQUIREMENTS.md`,
  `docs/mvp/02_DOMAIN_RULES.md`, ADR-0017 и
  `tasks/CB-64/parity-map.json`.
- Сверены фактические owners в `application/moderation.py`,
  `infrastructure/db/moderation.py`, `infrastructure/db/database.py` и
  `transport/web.py`, а также текущие web API, browser, auth и moderation tests.
- Jira не перечитывалась и не изменялась: review опирается на read-only snapshot
  из source context — CB-55 bloated backlog scope, CB-54 `В работе` и не merged,
  CB-64 `Готово`.
- В обязательном recheck перечитан только исправленный diff
  `plan-source-context.md` и `plan.md`; новых источников и нового review cycle
  не добавлялось.

## Замечания по области (`scope_findings`)

Обязательных замечаний по выбранной области нет.

- CB-55 в исходной формулировке действительно не является одним observable
  increment. Сужение до read-only moderation queue оставляет один путь
  `Модерация -> очередь -> Назад` и не принимает ни одного mutation-решения.
- Полный backend roadmap из требований, ADR-0017 и parity map явно сохранён:
  registration, config, community tasks, disputes/appeals, sanctions,
  karma/risk, audit, conflicts и durable drafts только отложены, а не удалены.
- Runtime корректно заблокирован до merge CB-54, доказанной import reconciliation
  и отдельного approval владельца на narrowed scope.

## Замечания по дизайну (`design_findings`)

Обязательных замечаний нет. Предыдущий High finding закрыт:

- `ModerationService` вычисляет `include_fraud_review` из актуальной роли actor;
- существующий `ModerationMutationPort.list_cases` и его SQL adapter применяют
  predicate `case_type != "fraud_review"` до `order_by(opened_at,id)` и `limit`;
- moderator и administrator получают первые `limit` строк собственного
  разрешённого множества без нового repository, service или permission layer;
- `infrastructure/db/moderation.py` добавлен в точный ожидаемый file plan.

Ponytail-only result: `Lean already. Ship.` Новых спекулятивных слоёв,
dependencies или generic admin abstractions план не требует.

## Замечания по проверке (`verification_findings`)

Обязательных замечаний нет. Предыдущий High finding закрыт exact adversarial
case: самым ранним является `fraud_review`, следующим — visible dispute;
`limit=1` обязан вернуть moderator следующий dispute, administrator — ранний
`fraud_review`, с точным `opened_at,id` ordering внутри разрешённого множества.

Остальная минимальная стратегия достаточна: один API scenario проверяет роли,
статусы, allowlist, closed errors, `no-store` и отсутствие side effects; один
browser journey проверяет literal rendering, закрытые состояния, back/focus и
отсутствие mutation requests; route-set check остаётся условным после CB-54.

## Обязательные исправления (`required_actions`)

Нет.

## Остаточные риски (`residual_risks`)

- Даже после исправления плана реализация остаётся заблокирована до фактического
  merge/CI CB-54, повторной сверки merged shell/API/tests, доказательства import
  reconciliation и явного owner approval. Новый verdict не должен сам снимать
  эти gates.
- Текущая ORM-реализация строит безопасный returned dataclass, но загружает
  `ModerationCaseModel`, содержащий `reason`, и полную текущую resolution row
  ради `current_code`. DTO allowlist и response/DOM negative assertions обязаны
  оставаться основным доказательством отсутствия внешнего раскрытия; переход к
  column-only query допустим в том же adapter, если нужен более узкий DB read.

## Последующее решение владельца

После этого независимого review владелец подтвердил merge CB-54 и одобрил
narrowed scope. Он отдельно установил причинную границу: CB-64 compact-db
import/reconciliation не блокирует read-only чтение текущего authoritative
moderation store, потому что slice не меняет schema/data и не выполняет
import/cutover. Этот owner decision снимает устаревшие implementation blockers
из review, не меняет `Status: approved` и не отменяет import/deploy gates для
будущей миграции.
