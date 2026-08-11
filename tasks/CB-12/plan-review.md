# CB-12 — независимое ревью плана

Status: approved

Схема: `community_bot.plan_review.verdict.v1`.

## Проверенные источники

- свежие Jira `CB-12`, `CB-5`, `CB-11`, `CB-13`, прочитанные напрямую через
  Atlassian Rovo API: описания, восемь критериев приёмки CB-12, статусы,
  родители и связи;
- `tasks/CB-12/plan-source-context.md`, актуальные `plan.md` и `test-plan.md`;
- `agents/plan-reviewer/instruction.md`,
  `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`;
- канонические `docs/mvp/02_DOMAIN_RULES.md`, `05_BOT_INTERFACE.md`,
  `06_DATA_MODEL.md`, `07_SECURITY_AND_PRIVACY.md`, `10_TEST_PLAN.md`,
  `11_DECISIONS_AND_OPEN_QUESTIONS.md`;
- ADR-0005 и ADR-0006;
- фактические Alembic migrations `0003`, `0004`, `0007`, SQLAlchemy models,
  economy ledger/cache, registration и `conversation_states`, assignments и
  `reliability_events`, общий DB UoW, Telegram receipts и существующие tests.

Jira подтверждает: CB-5 и CB-11 имеют статус `Готово`; CB-12 находится `В
работе`, имеет родителя CB-2 и блокирует CB-13 со статусом `К выполнению`.
Внешнее состояние не изменялось.

## Выводы по области

Пакет соответствует области CB-12: карма, safe profiles, личная статистика,
reliability и основной leaderboard реализуются одним крупным MVP-циклом.
Dispute resolution, санкции, fraud и публичная state-changing correction
reliability оставлены CB-13; полная регрессия оставлена CB-16. Новый ADR не
нужен: изменения остаются внутри принятого модульного монолита, PostgreSQL UoW
и транзакционного update-протокола ADR-0005/0006.

Все восемь Jira AC сопоставлены с конкретными сценариями `test-plan.md`:
self/eligibility — 2–3, 7; versioned current vote — 4–6, 24; delta `-2` — 5;
anonymity — 8, 12–14, 22–23; audited admin read — 9–10; reliability — 15–17;
experience leaderboard — 19–21; unavailable profile/forged callback — 7–8,
11–14, 23.

## Выводы по проектированию

### P-001 — закрыто

Karma draft использует существующую строку `conversation_states` с PK
`member_id`; callback содержит только revision, а actor определяется через
Telegram identity. План фиксирует общий порядок `update gate → exact receipt →
identity gate → locked state → exact flow/step/revision`, поэтому отсутствующая
строка и первая вставка сериализуются тем же identity gate, а существующая —
row lock. `registration`, `registration_paused`, `profile_edit` и другие flows
не перезаписываются: `/karma` отказывает, а `/cancel` изменяет только flow,
которому принадлежит строка. Отдельный draft UUID или новая таблица не нужны.

### P-002 — закрыто

Reliability формально разделена на immutable acceptance fact, единственный
terminal root и линейную responsibility chain. Заданы допустимые root/chain
типы, связь с текущим leaf того же assignment, запреты cycle,
cross-assignment, supersede `accepted`, повторного покрытия leaf и второго
root. Denominator определяется effective responsibility, numerator — исходным
root с partial weight `0.5`, effective no-show — сочетанием root и
responsibility. Таким образом существующая история `accepted + terminal` не
двусмысленна. CB-12 добавляет DB foundation и чтение; команда коррекции и её
permission остаются CB-13, а `karma_review` не расширяется до mutation.

### P-003 — закрыто

Порядок leaderboard авторитетно вычисляется из
`SUM(account_transactions.experience_delta)`, а
`experience_total_cached` используется только для reconciliation.
`level_config_version_id` не участвует ни в sort keys, ни в cursor; stale level
cache не меняет выдачу. Полный cursor содержит experience, recipients, флаг
достаточности sample, нормализованный reliability key, no-show, reached_at и
UUID. Для insufficient sample есть отдельный sentinel-флаг, для zero experience
`reached_at = members.registered_at`; этим задан строгий total order без
неопределённого NULL.

### P-004 — закрыто

Raw-read policy задана полным пересечением: active target требует active
administrator и `karma_review`; non-active target дополнительно требует
`member_read`. Любая другая комбинация не подтверждает существование target.
Migration backfill выдаёт оба права только существующим active administrators;
inactive administrators, moderators и members получают `[]`, а runtime всегда
повторно требует active status, administrator role и exact permission.

## Выводы по проверке

Test-plan доказывает не только happy path, но и критические границы:

- два разных Telegram update конкурируют за один locked karma state; fault
  rollback, stale revision, exact replay и collision с чужим flow проверяются;
- `accepted + terminal + responsibility chain`, exclusions, restore, partial
  weight, порог 4/5 и DB-инварианты supersede проверяются на реальном PostgreSQL;
- каждый leaderboard tie-breaker, zero experience, insufficient sample, stale
  level cache, UUID tie и полный cursor round-trip проверяются отдельно;
- permission/status cross-product, active-admin-only backfill, moderator,
  inactive admin и отсутствие client-side обхода проверяются негативно;
- migration cycle, targeted PostgreSQL/aiogram suite без skip/deselect, Ruff,
  ty, build, entrypoints, link/diff/secret checks образуют достаточный gate для
  области CB-12 без преждевременной полной регрессии.

## Обязательные исправления

Нет.

## Остаточные риски

- Ledger/reliability aggregates и оконный `reached_at` query приемлемы для
  пилота 20–30 участников; необходимость отдельного cache следует оценивать по
  наблюдаемой нагрузке, а не вводить заранее.
- DB foundation responsibility chain должен сохранить заявленные инварианты и
  сериализацию при будущей state-changing команде CB-13; это граница следующей
  задачи, а не незакрытый контракт CB-12.
- JSONB permissions практичны для двух прав MVP при условии реализации
  заявленного CHECK и обязательной server-side проверки role/status/permission;
  сценарий 24 это доказывает.

Полный актуальный пакет CB-12 реализуем без угадывания ключевых решений,
непротиворечив источникам и имеет достаточный план доказательства всех восьми
критериев приёмки.
