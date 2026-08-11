# CB-20 — независимое повторное ревью плана

Status: approved

Schema: `community_bot.plan_review.verdict.v1`

## reviewed_sources

- Jira `CB-20`, повторно прочитанная через Atlassian Rovo JQL API 11 августа
  2026 года: описание, семь критериев приёмки, статус `В работе`, приоритет
  `High`, комментарий и связи с `CB-16`/`CB-2`; требования не изменились.
- Актуальные `tasks/CB-20/plan-source-context.md`, `plan.md`, `test-plan.md` и
  все двенадцать целевых сценариев.
- Ранее проверенные обязательные process/MVP документы, ADR-0005/0006/0009,
  `PILOT_RUNBOOK.md` и фактические member/audit/registration/Dispatcher
  контракты базы `8b0be36812a65d790fb148b7d895461398424450`.

Jira, код, Git index/remote и Telegram не изменялись.

## scope_findings

- Область остаётся практичным bug-fix MVP: один CLI entry point, существующие
  `members`/`audit_events`, узкий application/UoW slice, runbook и targeted
  PostgreSQL/Dispatcher tests. Новая таблица, сервис или ADR не нужны.
- Исправление не становится обычным управлением ролями и не создаёт starting
  grant. Обычный backup restore с действующим администратором не запускает
  bootstrap; conflict требует остановки и диагностики, а не ручного SQL.
- Полная регрессия корректно остаётся единым проходом CB-16 после слияния
  blocking regression fixes.

## design_findings

- **P-001 закрыто.** Durable provenance — точное append-only событие
  `initial_administrator_bootstrapped`, связанное с внутренним member UUID.
  Idempotent success разрешён только для того же active administrator с этим
  сохранённым результатом. Любой другой active administrator или существующий
  target без provenance даёт conflict без мутаций; роль сама по себе больше не
  выдаётся за retry bootstrap.
- **P-002 закрыто.** CLI принимает только reason code
  `initial_install|clean_recovery`. Audit schema фиксирует actor/action/entity/
  reason/before/after и сохраняет только роль, status и permissions; Telegram
  ID, username, argv, token и свободный payload исключены из audit и логов.
- **P-003 закрыто.** Создаваемый member полностью детерминирован: безопасные
  display name/timezone, active administrator, `approved_at`, нулевые caches,
  точные `interaction_review`, `karma_review`, `member_read`, отсутствие grant.
  Target любого role/status проверяется fail-closed, а ID валидируется как
  положительный PostgreSQL `BIGINT` до транзакции.
- Операция использует transaction-scoped `pg_advisory_xact_lock` с фиксированным
  namespace и единый порядок lock → saved outcome/admin/target reads → member →
  audit → commit. Ошибка откатывает member и audit и освобождает gate; разные и
  одинаковые конкурентные ID имеют однозначные outcomes.

## verification_findings

- **V-001 закрыто.** Сценарии 9–10 — один PostgreSQL test на пустой схеме: он
  вызывает реальный CLI, затем production `_dispatcher` с подменённым только
  Bot API transport, выполняет `/invite_create`, извлекает token из ответа и
  передаёт `/start <token>` новому пользователю. Проверяются hashed invitation,
  pending registration и transport receipts без сетевой отправки.
- **V-002 закрыто.** Отдельный fault case доказывает полный rollback при ошибке
  audit/commit и успешный последующий retry. Concurrent same ID даёт один
  member/audit и `created`/`idempotent`; concurrent different IDs — одного
  winner и conflict без deadlock.
- Остальные проверки сохраняют fail-closed состояния, exact safe audit/member
  schema, CLI validation и entry-point smoke. Targeted Ruff, ty, pytest, build
  и diff-check достаточны для ветки бага; full regression здесь не дублируется.
- Контракт двух allowlisted причин и ограничения source context дают runbook
  однозначные команды для initial install и clean recovery; обычный restore с
  существующим active administrator явно не является bootstrap-сценарием.

## required_actions

Обязательных исправлений нет.

## residual_risks

- Оператор с production DB credentials остаётся доверенной стороной; CLI не
  заменяет root-only доступ к `.env` и серверу из ADR-0009.
- Fake Bot API доказывает production transport wiring, но не доступность сети
  Telegram; для targeted проверки bootstrap это корректная граница.
