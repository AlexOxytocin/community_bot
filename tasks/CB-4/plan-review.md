# CB-4 — независимое повторное ревью плана

Status: approved

## Проверенные источники

- Актуальная Jira `CB-4`: описание и критерии приёмки, статус `К выполнению`, приоритет `Medium`, родитель `CB-2`, связи `Blocks` с `CB-7` и `CB-9`, отсутствие вложений и исторический комментарий `10026`.
- Актуальная Jira `CB-2`: область эпика, статус `В работе` и критерии успеха.
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`, `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md`.
- ADR-0001–ADR-0006, включая обязательный для уровня 3 ADR-0004, а также ADR-0005 и ADR-0006.
- Полный пакет MVP, перечисленный в `plan-source-context.md`: `README.md`, `01_PRODUCT_REQUIREMENTS.md`, `02_DOMAIN_RULES.md`, `03_USER_FLOWS.md`, `04_TASK_CATALOG.md`, `05_BOT_INTERFACE.md`, `06_DATA_MODEL.md`, `08_MODERATION_AND_ABUSE.md`, `09_IMPLEMENTATION_PLAN.md`, `10_TEST_PLAN.md`, `11_DECISIONS_AND_OPEN_QUESTIONS.md`, `TECH_STACK.md`.
- `agents/README.md` и контракт роли `plan-reviewer`.
- Актуальные `tasks/CB-4/plan-source-context.md`, `plan.md`, `test-plan.md`, `needs-info.md` и предыдущий verdict.

Все обязательные источники перечитаны на текущем snapshot. Jira snapshot в `plan-source-context.md` соответствует данным API. Секретов, непрочитанных вложений и внешних информационных барьеров нет.

## Вердикт

План соответствует документационной области CB-4 и уровню 3 по ADR-0004. Новый ADR не требуется: решения конкретизируют продуктовые и доменные правила внутри уже принятого модульного монолита, PostgreSQL, ledger/outbox и idempotency-модели.

Предыдущее `changes_requested` полностью снято:

1. Immutable config ingest имеет идентичность `product_config_version:{config_version}:{payload_hash}`, а команда переключения — отдельную идентичность `activate_product_config:{activation_command_id}`. Rollback является новой командой активации уже существующей версии; retry, конфликт target и already-active no-op определены без повторного backfill.
2. `reject` заменяет обычную review/autoconfirm-ветку состоянием `rejected_pending_dispute`. Его отдельное полуоткрытое окно допускает dispute и после исходного review deadline, а dispute и finalizer сериализуются одним assignment lock и дают ровно один финансовый исход.
3. После потери независимого reviewer назначение валидной замены немедленно разрешает manual review и открывает новое полуоткрытое 72-часовое окно с напоминаниями через 24/48 часов и autoconfirm на границе. Добровольная замена всё ещё валидного reviewer исходный срок не продлевает.

План теперь задаёт один непротиворечивый результат для конкурентных операций, точных временных границ, retry, rollback и отказов. Обязательных исправлений нет.

## Проверка решений Q-002–Q-012

| Вопрос | Результат независимой проверки |
|---|---|
| Q-002/Q-003 | Десять уровней, названия и пороги согласованы с D-006. Единственный runtime source of truth — immutable DB versions и atomic active pointer; внешний config является только кандидатом ingest. Version-aware `LevelResolver`, activation/backfill и stale-cache правила покрывают profile, `minimum_level`, acceptance, leaderboard и notifications без ручной миграции опыта. |
| Q-004 | Однократный грант 5 кредитов после первого approval, 0 опыта и business-idempotency на участника заданы точно. |
| Q-007 | UTC-граница `now >= deadline`, per-slot reserve только для member origin, отсутствие reserve для community origin, `settling` и terminal aggregates, а также append-only коррекция `no_show` согласованы. |
| Q-008 | Обычное окно `[submitted_at, review_deadline_at)`, границы manual/autoconfirm, result versions, suppression напоминаний и отдельная reject/dispute-ветка определены без временной или финансовой коллизии. |
| Q-009 | `ceil(reward × 50 / 100)`, запрет partial при reward 1 и примеры для 2/3/4/5/11 точны. Member payout/refund исчерпывает reserve slice одного assignment; community issuance выпускает только фактическую выплату; опыт равен ей. |
| Q-010 | Жёсткого лимита нет. Окно `(T-window,T]`, crossing, pair lock, один глобальный open alert, policy switch, close/disarm/re-arm, privacy и dedup определены точно. Meeting outcome и допустимые penalties выполняются одной атомарной идемпотентной командой, не затрагивая reserve и опыт. |
| Q-012 | `origin=community`, immutable admin-authored card, общий catalog с сохранением safety guardrails, override reward выше 4, независимый reviewer, lifecycle cancel/review/reject/dispute/autoconfirm и `community_task_reward` без личного admin balance/reserve описаны полностью. |

Формулировка `needs-info.md` о новом «минимальном 24-часовом окне» является кратким нижним ограничением, а не альтернативной нормой: файл явно направляет за полными правилами к `plan.md`, где фиксировано ровно новое окно 72 часа, immediate manual review и напоминания 24/48. Для исполнителя вариативности не остаётся.

## Совместимость и последствия

- D-007 сохранён как правило authoring для member-task и датированно дополняется ограниченным `community` origin. Все остальные catalog safety guardrails продолжают действовать.
- D-008 сохраняет append-only journal и дополняется типами `community_task_reward` и `penalty`; прямого редактирования баланса, отрицательного баланса, скрытого reserve или изменения опыта нет.
- Q-007/Q-009 используют разные финансовые источники строго по origin: member reserve slice против system issuance. Lifecycle matrix не допускает одновременно refund и payout/issuance.
- Миграционные последствия перечисляют config versions, activation commands/outcomes, active pointer/backfill, review/reject deadlines, reviewer-required transition, origin-specific constraints, alert episode/pair indexes и уникальные business keys. Они достаточны для последующего планирования реализации и не проектируют миграции вне области CB-4.
- Docs-impact охватывает журнал решений, PRD, domain rules, flows, catalog, interface, data model, moderation, implementation/test plans и ADR index; старые противоположные гипотезы должны быть удалены в заданном порядке.

## Проверки и критерии Jira

Все критерии Jira проверяемы будущим исполнителем:

- Q-002/Q-003/Q-004/Q-007/Q-008/Q-009/Q-010/Q-012 имеют выбранное решение, причину, отклонённые варианты и точные границы.
- 23 сценария покрывают все threshold boundaries, concurrent starting grant, submission/expiration, admin adjustment, ingest/activation/rollback, ordinary и reject deadlines, partial, alert policy episodes, privacy/penalty, полный community lifecycle и reviewer replacement.
- Сценарии 2, 7 и 17 прямо доказывают закрытие трёх последних замечаний, включая retry после rollback, dispute за исходным review deadline и обе стороны нового replacement window.
- Сценарии 19–23 покрывают синхронизацию документов, миграционные последствия, ссылки, `git diff --check`, язык и отсутствие секретов.

## Остаточные риски

Остаются только уже признанные риски пилота: темп роста уровней, инфляция community rewards, злоупотребление autoconfirm и нагрузка от alert episodes. План не маскирует их: параметры версионируются, выплаты и штрафы журналируются, community issuance требует карточку и подтверждённый assignment, а alert не является автоматическим доказательством нарушения. Эти риски требуют наблюдения после реализации, но не дополнительного продуктового решения для утверждения плана CB-4.
