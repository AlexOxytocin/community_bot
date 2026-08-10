# CB-7 — третье независимое ревью плана

`community_bot.plan_review.verdict.v1`

Status: approved

## status

`approved`

## Проверенные источники

- Jira `CB-7` заново прочитана через Atlassian Rovo API: описание, семь
  критериев приёмки, статус `К выполнению`, приоритет `Medium`, parent `CB-2`,
  комментарии, вложения, labels и связи. Входящие CB-4/CB-6 завершены; CB-7
  блокирует CB-8, CB-10 и CB-11.
- Jira `CB-17` заново прочитана через Atlassian Rovo API: описание ty defect,
  критерии, статус и комментарий владельца о включении исправления в ветку
  CB-7 без отдельной bugfix-ветки.
- С нуля полностью прочитаны актуальные `tasks/CB-7/plan.md`,
  `plan-source-context.md`, `test-plan.md` и предыдущие два verdict.
- Повторно сверены правила роли/процесса, ADR-0004–0006, требования к
  credits/experience/config/reconciliation из документов MVP, принятый пакет
  CB-4 и фактические `MemberModel`, `SqlAlchemyUnitOfWork`, migration `0002`,
  `migrations/env.py`, PostgreSQL fixture и CI.
- Секретов в плановом пакете не обнаружено. Jira, Git remote, Telegram, код,
  тесты и исходные плановые файлы в ходе ревью не изменялись.

## Область задачи

Область соответствует CB-7 и уточнённому решению владельца по CB-17. Ledger,
atomic caches, named mutations, history, reconciliation, versioned product
config, `LevelResolver`, bootstrap coordinator и точечная аннотация Alembic
входят в текущую ветку. Telegram FSM, task/assignment/alert aggregates и их FK
не создаются преждевременно. Нового ADR не требуется: архитектурная форма уже
принята ADR-0005, а продуктовые правила — D-008/D-011/D-012/D-016.

## Логика решения

### Закрытие M-001–M-010

| Замечание | Итог третьего ревью |
|---|---|
| M-001 | `content_hash` строится без `config_version`; canonical projection и DB-монотонность определены и тестируются |
| M-002 | schema v1 включает levels и top-level interaction policy `threshold=3/window=7` |
| M-003 | первая activation и ingest collisions сериализованы общим config gate; exact retry/conflict outcomes заданы |
| M-004 | ledger, cache и thresholds согласованы как `BIGINT`; legacy upgrade и destructive downgrade имеют явные preconditions |
| M-005 | cross-row reversal trigger проверяет source/member/deltas/chaining; history tables append-only и покрыты direct-SQL тестами |
| M-006 | admin adjustment опыта имеет active-admin authorization, reason, audit, idempotency, неотрицательный итог и level recalc |
| M-007 | public UoW/port не раскрывает session и не делает nested commit; окончательный batch contract проверен ниже |
| M-008 | dangling task/assignment/alert correlation columns полностью отсутствуют |
| M-009 | bootstrap coordinator имеет operator-supplied actor/command ID, четыре точных startup outcome и не выдаёт роль |
| M-010 | ledger payload projection включает type/member/deltas/actor/reason/comment/reversal source и точную normalization |

CB-17 не регрессировал: план сохраняет точечную замену аннотации на
`sqlalchemy.engine.Connection`, `uv run ty check`, реальную async Alembic
migration, Ruff, полный pytest и migration cycle. Статус Jira-багу меняется
только после фактического исправления, зелёных проверок и слияния CB-7.

### Закрытие N-001

Все config mutations теперь используют один
`product_config_mutation` transaction-scoped advisory gate до actor row.
Standalone ingest/activation и bootstrap подчиняются одному порядку.
`ingest_locked`/`activate_locked` получают уже захваченный guard и actor и не
берут повторные gates/rows. Поэтому прежний цикл `actor ↔ activation gate`
устранён конструктивно, а не retry-политикой.

Сценарий 20 одновременно запускает coordinator против standalone ingest и
activation с тем же actor, разными command IDs/targets и жёстким timeout. Он
требует последовательную history, согласованный pointer, отсутствие deadlock,
сырого `IntegrityError` и частичного эффекта.

### Закрытие N-002

`EconomyMutationPort.apply_batch` принимает полный непустой набор entries. До
первого append он валидирует canonical payloads, сортирует и получает все
idempotency advisory gates, выполняет exact reads, затем блокирует объединённые
member UUID и reversal sources в едином порядке. Business order применяется
только после общего prelock. Владелец outer UoW делает один commit.

Batch-retry имеет закрытую семантику: допустим либо `all-new`, либо
`all-stored` с теми же canonical payloads. Смешанный `stored/new` набор
отклоняется как inconsistent retry до member/reversal locks и append, поэтому
не оставляет новых ledger, cache, marker или audit effects. Changed payload для
любого сохранённого ключа также отклоняется exact read до новых эффектов.

`apply_one` оставлен только как standalone convenience и делегирует batch из
одного элемента. Последовательные `apply_one` внутри составного settlement
явно запрещены. Сценарий 25 проверяет публичный API без `_session`, marker и
несколько ledger entries, rollback/commit/fault, `all-stored` retry и
`stored/new` mixed reject без частичного эффекта, а также два concurrent batch
с reverse input order и жёстким timeout. Это достаточная композиционная граница
для будущих CB-10/CB-11.

## Стратегия проверки

Тридцать один сценарий сопоставлен с Jira-критериями. Обязательная матрица
включает unit, Hypothesis, PostgreSQL constraints/triggers, concurrency,
migration, authorization, restart, Compose и отдельный Testcontainers fallback.
Compose и Testcontainers не допускают `skip`/`deselect`; fault tests доказывают
rollback до повторной попытки. Отдельно проверяются Ruff, ty, build,
entrypoints, Markdown links, diff и secret scan.

Проверки M-001–M-010, N-001/N-002 и CB-17 имеют конкретные входы, ожидаемые
состояния и наблюдаемые доказательства. Исполнителю не оставлено скрытого выбора
lock order, hash projection, numeric type, bootstrap authority или transaction
ownership.

## Обязательные исправления

Обязательных исправлений плана нет. Реализация может начаться после соблюдения
процессных шагов: публикации одобренного плана в рамках выраженного намерения
владельца, получения актуального Jira transition и перехода CB-7 в реальный
эквивалент `В работе`.

## Остаточные риски

- Синхронный backfill приемлем для пилота, но при росте потребует отдельной
  задачи; correctness остаётся в `LevelResolver`.
- Production provisioning первого administrator и runtime wiring остаются
  будущей эксплуатационной работой; coordinator не создаёт скрытый admin path.
- Negative experience adjustment является исключительной административной
  коррекцией; final review должен подтвердить, что обычные grant/refund/spend
  paths не уменьшают опыт.
- Exactly-once внешнего Telegram response не входит в PostgreSQL-гарантию по
  ADR-0006 и задачей не расширяется.
