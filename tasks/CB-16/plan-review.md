# CB-16 — независимое повторное ревью плана

Status: approved

Schema: `community_bot.plan_review.verdict.v1`

## reviewed_sources

- Jira `CB-16` и родительский эпик `CB-2`, свежо прочитанные напрямую через
  Atlassian Rovo JQL API 11 августа 2026 года: описания, семь критериев приёмки,
  комментарии, статусы и связи. Блокирующие `CB-8` и `CB-15` имеют статус
  `Готово`; Jira-контракт общей регрессии и отдельных багов не изменился.
- Frozen staged tree `9d30bea8f893a21f5ace83531a4420764e852ae4` на ветке
  `task/CB-16`, база `8b0be36812a65d790fb148b7d895461398424450`.
- Полный актуальный пакет `tasks/CB-16/plan-source-context.md`, `plan.md` и
  `test-plan.md`.
- Все перечисленные в source context процессные, продуктовые и технические
  источники: project/Jira/agent workflow, ADR-0004–ADR-0009, полный комплект
  `docs/mvp`, `TECH_STACK`, `HANDOFF` и `docs/operations/PILOT_RUNBOOK.md`.
- Фактическая реализация staged tree: миграции `0001`–`0010`, Telegram routers,
  application/domain/PostgreSQL adapters, текущие unit/integration/smoke tests,
  Compose, CI/release и self-hosted backup/restore scripts.

Внешнее состояние Jira, Git remote и Telegram не изменялось. Полная регрессия
в рамках plan review не запускалась.

## scope_findings

- Область остаётся одним крупным, но практичным MVP-срезом уровня 3: E2E A–D,
  критические concurrency/replay проверки, пустая и поддерживаемая схема,
  production restore с ledger reconciliation, метрики, checklist и runbook
  вместе закрывают все семь Jira AC.
- План не добавляет новую инфраструктуру и честно отделяет синтетический
  Telegram E2E от реального Bot API smoke. Test-only seed не попадает в
  production, приватные чаты не используются, реальная отправка остаётся за
  отдельным разрешением владельца.
- Регрессионный процесс соответствует принятому правилу: дефект готового MVP
  получает отдельный Jira Bug и ветку, targeted проверки выполняются в bug
  task, а полный regression gate повторяется один раз после слияния всего
  blocking-набора.
- Self-hosted restore, RPO/RTO и раскрытый риск потери единственного хоста
  согласованы с ADR-0009. Новый ADR для read-only отчёта, fixture и checklist не
  требуется.

## design_findings

- **P-001 закрыто.** `community_bot.pilot_metrics.v1` теперь задаёт для каждой
  метрики числитель, знаменатель, event time, UTC-полуинтервал, maturity,
  terminal outcomes и поведение пустого denominator. Три порога PRD однозначно
  сопоставлены полям `task_fill_rate`, `assignment_completion_rate` и
  `repeat_action_rate`; rates/counts/time имеют фиксированное представление.
- **P-002 закрыто.** Output contract закрыт через
  `additionalProperties=false`, фиксированный агрегированный набор и запрет
  participant-shaped keys, идентификаторов, raw labels/text и entity arrays.
  Credits/experience используют только coarse buckets; cells `1|2`
  детерминированно объединяются, а невозможный безопасный остаток выводится как
  `suppressed_count` без диапазона. Это пропорциональная защита малой пилотной
  когорты без бесполезного подавления общих totals/rates.
- **P-003 закрыто.** Каждый A–D test получает собственную PostgreSQL DB и
  создаёт предусловия независимо от порядка pytest. Пользовательские действия
  проходят через настоящий aiogram `Dispatcher`, зарегистрированные routers и
  callbacks с fake Bot API; direct application calls ограничены setup/oracle.
  D сам создаёт paid interaction и больше не зависит от A.
- Доменные исходы A–D не регрессировали: exactly-once registration grant и
  reserve, один cancel refund, partial dispute resolution с независимым
  moderator и audit/reliability, а также eligibility и privacy/audit контракты
  кармы согласованы с текущим кодом и каноническими правилами.

## verification_findings

- **V-001 закрыто.** Representative `0009` fixture содержит published и
  unpublished outbox rows. После `0010` проверяются соответственно
  `materialized`/`pending`, неизменность business key, payload и timestamps,
  defaults, `ck_outbox_*`, due/notification/heartbeat indexes и constraints,
  invalid operational states и повторный `upgrade head`.
- **V-002 закрыто.** Табличные проверки покрывают `from`, `to`, ровно `+48h`,
  empty denominator, full/partial/reject/cancel, cross-week retention,
  concentration tie, merge/suppression и PII-negative schema. Ledger остаётся
  authoritative при намеренно испорченном cache; reconciliation проверяется
  отдельно.
- **V-003 закрыто.** Каждый regression Bug получает общий label
  `cb16-regression`, ровно один severity label и `Relates` с `CB-16`. Связь
  `Blocks` в направлении bug → `CB-16` добавляется только для реально
  блокирующих critical/high. Полный label-based discovery set сверяется с
  implementation report; open medium/low требует decision label и ссылку на
  явное решение владельца.
- Остальные AC не регрессировали: критические race/replay сценарии входят в
  автоматический gate; пустая схема и `0009→0010` проверяются раздельно;
  isolated production restore требует revision `0010`, нулевой ledger/cache
  mismatch и RPO/RTO evidence; stop/checklist/runbook/closeout дают владельцу
  воспроизводимое решение `continue|pause|stop`.
- Gate остаётся разумным для MVP: targeted проверки во время реализации, один
  полный локальный/CI проход готового пакета, затем один финальный проход после
  blocking fixes и production operational smoke без реальных сообщений.

## required_actions

Обязательных исправлений нет.

## residual_risks

- Fake Bot API доказывает Telegram transport wiring и отсутствие сетевой
  отправки, но не доступность внешнего Bot API; план честно отделяет это от
  отдельно разрешаемого manual smoke.
- Локальный backup не переживает потерю self-hosted сервера или диска — это
  явно принятый владельцем риск ADR-0009, а не пробел CB-16.
- После успешного внешнего Telegram call до фиксации `sent_at` сохраняется
  crash-window ADR-0006; persistent replay/dedup проверки не называют его
  end-to-end exactly-once.
