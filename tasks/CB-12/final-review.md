# CB-12 — второе финальное ревью

Status: approved

Схема: `community_bot.final_review.verdict.v1`.

## reviewed_scope

- Jira `CB-12` свежо прочитана через Atlassian Rovo API: история «Реализовать
  карму, надёжность, статистику и лидерборд», статус `В работе`, восемь критериев
  приёмки, родитель `CB-2`, закрытые блокеры `CB-5`/`CB-11` и исходящая связь к
  `CB-13`; вложений и новых противоречащих комментариев нет.
- Повторно прочитаны обязательные правила проекта, инструкции процесса и роли
  финального ревью, а также полный актуальный Level 3 пакет `tasks/CB-12`:
  source context, план, test-plan, одобренный plan-review и implementation report.
- Проверена вся staged-разница из 22 файлов и документационное влияние на
  `02_DOMAIN_RULES.md`, `05_BOT_INTERFACE.md`, `06_DATA_MODEL.md`.
- До и после ревью `git write-tree` равен замороженному snapshot
  `156d9419159fb11868c5b24cb0c9a3462e07d3f8`.
- Широкая регрессия повторно не запускалась. Приняты доказательства общего gate:
  PostgreSQL 18 healthy, Alembic `head→0007→head`, `281 passed`, `0 skip`,
  coverage `80.82%`, Ruff, ty, build, entrypoints и diff-check успешны.

## critical_findings

Нет.

## major_findings

Нет.

Замечания первого ревью закрыты консолидированно:

- `M-001`: административная projection теперь возвращает current vote вместе с
  полной упорядоченной immutable history; успешное чтение сохраняет audit и
  receipt, exact replay не дублирует effect, permission/status policy проверена;
- `M-002`: karma `/cancel` принимает `update_id`, проходит update gate, создаёт
  единственные receipt/audit и при чужом flow передаёт update следующему
  обработчику через `SkipHandler`; совместная маршрутизация доказана synthetic
  dispatcher-тестом;
- `M-003`: добавлены сфокусированные проверки fault rollback, полного
  permission/status поведения, terminal reliability, member/community
  статистики, полного leaderboard cursor/tie-breakers и SQL guards; отчёт
  обновлён фактическим результатом gate.

## minor_findings

Нет.

## acceptance_matrix_result

| Критерий Jira | Результат | Доказательство |
|---|---|---|
| Self-vote и недопущённое голосование запрещены | Пройден | Domain/DB guards, paid member-origin eligibility и негативные integration fixtures |
| Повторная оценка обновляет одну запись и сохраняет историю | Пройден | Pair gate, unique current row, append-only revisions, replay/conflict/concurrency assertions |
| `+1→-1` меняет aggregate на `-2` | Пройден | Последовательный integration oracle текущего значения и aggregate delta |
| Получатель не узнаёт автора через UI/callback/API/логи | Пройден | Safe DTO/query/presenter и synthetic forged/stale transport paths не содержат raw автора, комментарий или history |
| Административный просмотр оставляет audit event | Пройден | Непустая current+history projection, exact permission/status cross-product, один audit/receipt на effect и стабильный replay |
| Надёжность учитывает исключения и partial weight | Пройден | Все terminal roots, creator exclusion, excused/restored chain, partial `0.5` и граница sample `4/5` |
| Leaderboard сортируется по опыту, не по credits/karma | Пройден | Ledger-authoritative experience, независимость от credits/karma/cache, полный total-order cursor и pagination |
| Недоступный профиль не раскрывает поля через forged callback | Пройден | Единый unavailable contract для неизвестных/non-active/stale/forged targets и synthetic aiogram |

Итог: `8/8` критериев пройдены.

## test_matrix_result

- Сценарии 1–7: migration cycle, eligibility, последовательные/replay/conflict и
  concurrent/fault-rollback ветви закрыты.
- Сценарии 8–14: participant privacy, непустая admin current+history projection,
  точная permission/status matrix, safe profile и keyset catalog закрыты.
- Сценарии 15–18: terminal reliability, responsibility chain, sample boundary и
  member/community personal statistics закрыты.
- Сценарии 19–21: ledger-authoritative ranking, все tie-breakers и полный cursor
  на sentinel/UUID boundary закрыты.
- Сценарии 22–24: durable karma flow, replay/stale/cancel с handoff и direct SQL
  constraints закрыты.
- Сценарий 25 подтверждён принятым общим gate: `281 passed`, `0 skip`, coverage
  `80.82%`, migration cycle и все обязательные quality-команды зелёные.

Итоговая матрица: `25/25` сценариев имеет соответствующее доказательство.

## security_and_secret_result

- Повторный staged secret scan не нашёл private keys, token signatures, сессии
  или реальные учётные данные; Bot token в тесте синтетический.
- В runtime/test/migration именах нет Jira-ключа `CB-12`; приватные raw поля
  доступны только отдельной server-side admin projection после точной policy.
- Локальные ссылки staged Markdown валидны, stale barriers не найдены,
  `git diff --cached --check` успешен.
- Jira, Telegram, Git remote и иные внешние состояния в ходе ревью не менялись.

## workflow_result

- Level 3 пакет полон, plan-review имеет точный `Status: approved`, реализация и
  отчёт соответствуют Jira и принятым ADR; новый ADR не требуется.
- Ветка `task/CB-12` основана на актуальном `origin/main`: `HEAD`, `origin/main`
  и merge-base равны `ec8c72367d6b08c40f0ceefbd89183163e967486`.
- Staged scope соответствует CB-12; несвязанных/generated файлов нет. Этот
  `final-review.md` остаётся единственным разрешённым unstaged артефактом.
- Это второе ревью после одного консолидированного исправления. Поскольку
  обязательных findings нет, процессная escalation не требуется.

## required_actions

Нет.

## residual_risks

- Полная регрессия готового MVP остаётся отдельной задачей `CB-16`; это не
  препятствует приёмке целевого CB-12 gate.
- Sanctions/dispute/fraud UI и изменение permissions остаются областью `CB-13`.
- Ledger/reliability aggregation без cache приемлема для пилота 20–30 человек;
  оптимизация нужна только по измеренной нагрузке.
