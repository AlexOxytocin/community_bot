# CB-15 — повторное финальное ревью

Status: approved

Схема: `community_bot.final_review.verdict.v1`.

## reviewed_scope

- Jira `CB-15` повторно прочитана напрямую через Atlassian Rovo API: восемь
  критериев приёмки, завершённые блокеры CB-13/CB-14 и исходящая связь к общей
  регрессии CB-16 подтверждены.
- Проверен новый exact staged tree
  `466d975e5528ee8418a2afcb97f3edb1b27abad2` и точная разница относительно
  первого review: observability logging/Sentry, четыре privacy tests,
  `needs-info.md`, синхронизация implementation report и сохранённый verdict
  первой попытки.
- Повторно проверены только закрытие M-001/M-002 и отсутствие регрессии прежних
  acceptance/self-hosted evidence. Полный notification, PostgreSQL 18,
  `linux/arm64`, deploy, backup/restore и server gate заново не прогонялись:
  приняты ранее подтверждённые `48 passed`, migration/build/entrypoint/Compose
  checks и фактические server evidence. Полная регрессия остаётся CB-16.
- Точечная контрольная проверка:
  `uv run pytest -q --no-cov tests/unit/test_observability.py` — `4 passed`;
  Ruff для трёх изменённых Python-файлов — успешно; отдельный Sentry-shape repro
  подтвердил полное удаление request/user и редактирование message, logentry,
  exception value и breadcrumb message.

## critical_findings

Нет.

## major_findings

Нет.

### Закрытие M-001

- Общий logging scrubber теперь очищает credential-shaped строки независимо от
  имени поля: Telegram Bot API token, Bearer credential, secret/password/token/
  invite/DSN assignment и URL userinfo.
- Sentry `before_send` применяет общий scrubber, полностью удаляет `request` и
  `user`, редактирует top-level `message`, `logentry.message/formatted`, каждое
  `exception.values[].value` и `breadcrumbs.values[].message`.
- Воспроизведение исходного дефекта теперь возвращает только `[REDACTED]`; тип
  исключения и диагностическая структура сохраняются без приватного текста.
- Четыре privacy tests включают embedded credential string и реальную структуру
  Sentry event. Ослабления assertions или отключения Sentry gate нет.

### Закрытие M-002

- `tasks/CB-15/needs-info.md` переименован по смыслу в журнал внешней информации
  и явно имеет статус `Закрыто 2026-08-11`.
- Артефакт фиксирует только несекретные факты: token передан и хранится в
  root-owned `0600` server env, runtime/Telegram/health/backup/restore успешны,
  открытой внешней информации нет.
- `implementation-report.md` согласован с исправленным privacy contract и
  отдельно фиксирует усиленный контур `4 passed`; противоречия о готовности
  больше нет.

## minor_findings

Нет.

## acceptance_matrix_result

| Критерий Jira | Результат | Доказательство |
|---|---|---|
| AC1: временная ошибка даёт ограниченный повтор | Пройден | Ранее подтверждённые bounded retry/backoff и terminal-limit tests |
| AC2: успешная доставка не повторяется | Пройден | Persistent delivery state, dedup и restart evidence |
| AC3: два worker не обрабатывают одну запись | Пройден | PostgreSQL `SKIP LOCKED`, fenced leases и concurrency evidence |
| AC4: timezone участника | Пройден | IANA timezone, DST/window/deadline assertions |
| AC5: restart продолжает pending без DB-дублей | Пройден | Expired lease reclaim и stale-token rejection |
| AC6: health отражает критические зависимости | Пройден | DB/migration/heartbeat/poison checks и healthy server runtime |
| AC7: backup восстановлен по runbook | Пройден | Реальный root `0600` dump, isolated restore `0010`, удаление drill DB и RTO 1 секунда |
| AC8: логи/error reporting не раскрывают секреты | Пройден | M-001 закрыт deny-by-default Sentry projection, credential string scrubber и 4 privacy tests |

Итог: `8/8` критериев пройдены.

## test_matrix_result

| Сценарии test-plan | Результат |
|---|---|
| 1–6: materialization, concurrency, retry, restart, reminders, timezone | Пройдены ранее подтверждённым targeted gate |
| 7: privacy persistence/logs/Sentry | Пройден; исходный leak воспроизведён как закрытый, `4 passed`, Ruff clean |
| 8–9: readiness и migration cycle | Пройдены ранее подтверждённым PostgreSQL evidence |
| 10–13: Compose, deployment order/failure, arm64 image/entrypoints | Пройдены contract/Docker/server evidence без изменений в повторном diff |
| 14–16: backup, isolated restore, server isolation | Пройдены реальным server evidence; contracts не менялись |
| 17: исключённая область | Пройден; external backup/R2/object storage/webhook не добавлены |

Итог: `17/17` сценариев пройдены. Полная продуктовая регрессия корректно
оставлена отдельной задаче CB-16.

## security_and_secret_result

- Повторный staged secret-pattern scan не обнаружил private keys, access tokens,
  Bot API tokens или production credentials.
- Новый negative gate закрывает не только sensitive key names, но и credential
  strings внутри обычных logging fields и стандартные Sentry free-form поля.
- Request/user целиком не экспортируются в Sentry; PII остаётся выключенной,
  traces sampling равен нулю.
- Root-owned secret, private Compose network, PostgreSQL 18 volume, bounded logs
  и isolated restore boundaries не изменились.

## workflow_result

- Level 3 пакет полон: Jira, ветка `task/CB-15`, source context, plan,
  `Status: approved` plan review, test-plan, принятый ADR-0009,
  implementation report и закрытый needs-info journal согласованы.
- Разница между первым и повторным snapshot ограничена единым закрытием
  M-001/M-002; прежний runtime/self-hosted scope не регрессировал.
- `git diff --cached --check`, branch/scope и secret checks чисты. Staged tree
  после проверки остаётся
  `466d975e5528ee8418a2afcb97f3edb1b27abad2`.
- Jira, staged index, Git remote, server и Telegram не изменялись. Обновлён
  только рабочий `tasks/CB-15/final-review.md`, оставленный unstaged поверх
  frozen index.

## required_actions

Нет.

## residual_risks

- Same-host dump не переживает потерю хоста/диска — это явно принятый владельцем
  MVP-риск ADR-0009.
- Внешний Telegram crash-window между Bot API success и сохранением `sent_at`
  остаётся ограничением ADR-0006; exactly-once заявляется только для DB-эффекта.
- Измеренный RTO в одну секунду относится к текущему почти пустому пилотному
  набору; цель `RTO <= 4h` поддерживается последующими четырёхнедельными drills.
