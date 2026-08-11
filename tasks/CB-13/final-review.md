# CB-13 — финальное ревью после CI-fix

Status: approved

Схема: `community_bot.final_review.verdict.v1`.

## reviewed_scope

- Jira `CB-13` свежо прочитана через Atlassian Rovo API: семь критериев
  приёмки, статус `На проверке`, закрытые блокеры `CB-11`/`CB-12`, родитель
  `CB-2` и исходящая связь к `CB-15`.
- Повторно сверены обязательный Level 3 пакет, принятые P-001–P-003/D-023,
  одобренный эскалационный plan review, актуальный implementation report и
  полный staged diff.
- Проверен консолидированный delta после первого final review: миграция `0009`,
  domain/persistence/UoW, implementation report и targeted integration tests.
- Отдельно проверен CI-fix поверх commit
  `f09b570423cf19f677dada7aa262897999f791b2`: staged delta содержит только
  синхронизацию одного migration assertion с правом `interaction_review` из
  `0009` и фактическое дополнение implementation report данными CI run
  `31480039435`.
- До и после проверки `git write-tree` равен frozen snapshot
  `2cd6690932491524b42fc97b1fba2cf0aa1a8362`.
- Независимо повторён только утверждённый moderation gate:
  `uv run pytest -q --no-cov tests/unit/test_moderation_domain.py tests/integration/test_moderation.py`
  — `17 passed` за `26.19s`, без skip/deselect. Полная регрессия MVP не
  запускалась и остаётся `CB-16`.
- Принято доказательство первого полного CI run `31480039435`: quality gate и
  `308` PostgreSQL-тестов прошли, единственным падением было устаревшее ожидание
  набора прав после migration `0009`. Независимо повторён только этот тест:
  `test_migration_backfills_only_active_administrators` — `1 passed` за `6.85s`.

## critical_findings

Нет.

## major_findings

Нет.

Замечания первого final review закрыты одним пакетом:

- `M-001`: active-case index и query включают `open|resolved|appealed`, а
  resolution и appeal получают тот же assignment-scoped advisory gate, что и
  paid-fraud opening; повторное дело на appealed assignment отклоняется тестом;
- `M-002`: `slot_ever_paid` теперь меняется только при положительной выплате
  исполнителю; неоплаченный `cancel_without_fault` сохраняет `false`, после чего
  тот же slot успешно занимает replacement assignment;
- `M-003`: paid-fraud opening готовит exact reversal и применяет его внутри
  откатываемого savepoint до создания case/audit/receipt; insufficient balance
  оставляет БД без case и processed update; отдельный fault hook доказывает
  полный rollback resolution UoW;
- `M-004`: отчёт больше не заявляет полное декартово произведение сценариев, а
  точно описывает риск-ориентированный MVP gate из 17 тестов и остаточные
  границы. Downgrade с существующим `resolution_reversal` теперь останавливается
  явным preflight barrier до любых DDL-изменений, исключая потерю или неверную
  переклассификацию ledger history.

CI-fix не меняет runtime-код, миграцию или authorization policy. Assertion
по-прежнему точный: active administrator обязан получить ровно
`interaction_review|karma_review|member_read`, paused administrator и member —
пустой набор. Барьер не ослаблен, а приведён в соответствие с проверяемым head.

## minor_findings

Нет.

## acceptance_matrix_result

| Критерий Jira | Результат | Доказательство |
|---|---|---|
| Спор блокирует выплату до решения | Пройден | Frozen disputed fixture и единый atomic resolution boundary |
| Resolution codes дают ожидаемые status/ledger | Пройден | PostgreSQL matrix full/partial/refund/cancel и отдельный exact fraud reversal |
| Конфликт интересов запрещает решение | Пройден | Server-side conflict policy и negative case-party integration test |
| Санкция хранит автора, основание, срок и отмену | Пройден | Role matrix, admin-only ban, issue/revoke history, suspension expiry и action restriction |
| Карма сама не списывает credits и не блокирует | Пройден | Private signal и exact exclude/restore без sanction/status/economy effect |
| Решение и апелляция воспроизводятся по audit trail | Пройден | Append-only resolutions, exact replay, second-appeal/second-case barriers, reversal links и immutable history |
| Integration покрывает full/partial/refund/fraud | Пройден | Targeted PostgreSQL tests всех четырёх экономических направлений, concurrency и rollback |

Итог: `7/7` критериев пройдены.

## test_matrix_result

- Migration/data barriers: empty cycle успешен; append-only history защищена;
  downgrade после реального `resolution_reversal` безопасно запрещён до DDL.
- Resolution/appeal/fraud: matrix, exact/conflicting replay, permanent paid slot,
  replacement unpaid slot, единственный active case, second appeal, different
  administrator, insufficient reversal, concurrency и injected rollback закрыты.
- Sanctions/actions: conflict denial, ban role boundary, reversible history,
  suspension expiry и exact restriction enforcement закрыты.
- Abuse/Telegram: karma signal/exclude/restore без автоматической санкции,
  interaction alert/penalty и durable preview/restart/foreign callback закрыты.
- Общий targeted gate: `17 passed`, `0 skip/deselect`; приняты зафиксированные
  успешные Alembic cycle, Ruff, ty, build, entrypoints и diff-check.
- CI-перепроверка: полный run дал `308 passed` до одного stale assertion; после
  точной синхронизации сфокусированный migration test дал `1 passed`. Новых
  поведенческих ветвей или оснований повторять локально полную регрессию нет.

Итог: риск-ориентированный MVP gate достаточен для CB-13. Необоснованного
утверждения о полном переборе всех комбинаций в отчёте больше нет.

## security_and_secret_result

- Повторный staged secret scan не нашёл private keys, token signatures,
  Telegram sessions или реальные credentials; Bot token тестовый.
- Jira-ключ отсутствует в runtime/test/migration именах, локальные Markdown
  links валидны, смысловые артефакты написаны по-русски.
- `git diff --cached --check` успешен. Реальных Telegram-отправок не было;
  проверенный callback actor-bound, restart-safe и не превышает 64 байта.

## workflow_result

- Level 3 пакет полон, контрольный plan review имеет точный
  `Status: approved`; новый ADR не нужен, реализация остаётся внутри
  ADR-0005/0006.
- Проверяемый CI-fix staged поверх commit
  `f09b570423cf19f677dada7aa262897999f791b2` в ветке `task/CB-13`; delta строго
  ограничен одним test expectation и implementation report.
- Staged scope соответствует CB-13, несвязанных/generated файлов нет. Jira,
  staged index, Git remote и Telegram не менялись; этот `final-review.md`
  оставлен единственным unstaged артефактом.
- Предыдущее `Status: approved` перепроверено на новом snapshot и остаётся
  применимо: CI-fix не изменяет принятые M-001–M-004 границы. Обязательных
  findings нет, final-review escalation не нужна.

## required_actions

Нет.

## residual_risks

- Полная регрессия собранного MVP остаётся отдельной задачей `CB-16`.
- Фоновая доставка outbox и ускорение expiry остаются `CB-15`; correctness
  проверенных status/action paths от worker не зависит.
- Downgrade после `resolution_reversal` намеренно запрещён сохранным preflight,
  а не выполняет разрушительное преобразование финансовой истории.
