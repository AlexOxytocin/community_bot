# CB-16 — финальное ревью

Status: changes_requested

Схема: `community_bot.final_review.verdict.v1`.

## reviewed_scope

- Jira `CB-16` свежо прочитана напрямую через Atlassian Rovo API: статус
  `В работе`, семь критериев приёмки, комментарии и связи.
- Discovery JQL `project = CB AND labels = cb16-regression ORDER BY key ASC`
  вернул ровно два Bug: `CB-20` и `CB-21`; оба имеют severity `High`, статус
  `Готово`, labels `cb16-regression`/`severity-high` и связи с `CB-16`.
  Отдельный JQL по открытым `Highest|High` в этом discovery set вернул `0`.
- Полностью прочитаны Level 3 package `tasks/CB-16`, канонические process
  документы, approved plan review, test-plan, staged implementation report и
  фактический diff `origin/main...HEAD`.
- Проверен exact combined tree
  `d220e2f40613a8f344327c26ff4563857901ced4` на ветке `task/CB-16`:
  `HEAD=5e3e99badae43f2f9fad24289c11fd39a063cfac`, staged delta — только
  `tasks/CB-16/implementation-report.md`.
- Принято authoritative evidence итогового PostgreSQL 18 gate: `369 passed`,
  `0 skipped`, `0 deselected`, coverage `80.15%`, Ruff/ty/build/entrypoints и
  diff-check зелёные. Полная регрессия повторно не запускалась.
- Узко воспроизведён CLI output на пустом периоде; проверены diff/branch,
  локальные Markdown-ссылки и secret-like patterns. Реальные Telegram-отправки
  и внешние изменения не выполнялись.

## critical_findings

Нет.

## major_findings

### M-001 — фактическая schema метрик не соответствует approved contract и runbook

Approved plan задаёт публичные поля `invite_conversion_rate`,
`task_fill_rate`, `task_fill_rate_48h`, `assignment_completion_rate`,
`repeat_action_rate` и `weekly_retention_rate`; эти же имена используются в
checklist, retrospective и порогах runbook. Модель в
`src/community_bot/application/pilot.py:102-115` сериализует вместо них
`invite_conversion`, `task_fill`, `task_fill_48h`, `assignment_completion`,
`repeat_action` и `weekly_retention`.

Воспроизведение:

```powershell
$env:DATABASE_URL='postgresql+asyncpg://community_bot:community_bot@localhost:5432/community_bot'
uv run community-pilot-report --from 2026-08-01T00:00:00Z --to 2026-08-08T00:00:00Z
```

Фактический JSON содержит `task_fill`, `assignment_completion` и
`repeat_action`, тогда как `docs/operations/PILOT_CHECKLIST.md:40-42` требует
поля с суффиксом `_rate`. Владелец не может механически перенести значения по
проверенному контракту, а versioned schema уже расходится с approved plan.

### M-002 — retention теряет предыдущие изменения кармы

План определяет activity как каждую `karma mutation`. Adapter
`src/community_bot/infrastructure/db/pilot.py:186-195` читает только текущую
строку `KarmaVoteModel.updated_at`. Если участник поставил оценку в предыдущую
неделю и изменил её в текущую, прежняя mutation исчезает из фактов: для пары
остаётся только новый `updated_at`, и weekly retention ошибочно не считает
участника активным в обеих неделях. Канонический источник обеих mutation уже
существует — immutable `karma_vote_history` с `actor_member_id` и `created_at`.

Имеющийся unit test вручную передаёт два `TimedMemberFact` и проверяет только
чистую функцию; PostgreSQL adapter case с двумя revision через границу недель
отсутствует, поэтому общий зелёный gate этот дефект не обнаруживает.

### M-003 — заявленная матрица метрик существенно шире фактических тестов

`implementation-report.md` утверждает покрытие `from`, `to`, `+48h`,
full/partial/reject/cancel, retention, deterministic top-20%, small-cell
merge/suppression и ledger-authoritative values. В
`tests/unit/test_pilot_metrics.py` есть только empty case, один совмещённый
formula case и проверка интервала; integration test проверяет ledger/cache и
отсутствие трёх конкретных participant values.

В совмещённом case partial reward стоит ровно на `to` и потому исключается;
нет positive partial case, reject/reversal case, top-20 tie с несколькими
performers, невозможного для объединения small cell `1|2`, community aggregates
и отчёта на наборе A–D. Поэтому обязательные пункты 2–7 раздела «Метрики и
документы» test-plan не имеют проверяемого evidence, а отчёт завышает покрытие.

### M-004 — supported-schema migration fixture не доказывает обещанное сохранение домена

Approved plan и `test-plan.md:109-112` требуют базу `0009` с members, ledger,
task/assignment, karma и moderation history и проверку сохранения строк и FK
после `0010`. `test_supported_schema_upgrade_preserves_outbox_semantics`
создаёт на `0009` только две строки `outbox_events`; helper
`_seed_legacy_outbox` не создаёт ни одного из перечисленных доменных объектов.

Сам upgrade и backfill outbox доказаны, но обязательный representative-data
oracle отсутствует. Следовательно, критерий поддерживаемой схемы закрыт лишь
частично, несмотря на формулировку implementation report.

## minor_findings

Нет.

## acceptance_matrix_result

| Критерий Jira | Результат | Доказательство |
|---|---|---|
| Регистрация, полный обмен, отмена, спор и карма | Пройден | E2E A–D через production Dispatcher/fake Bot API входят в authoritative `369 passed` |
| Критические гонки и повторная доставка | Пройден | Integration/replay/concurrency suite и повтор updates/callbacks в A–D |
| Пустая и поддерживаемая схема | Частично | Пустой `head→base→head` и `0009→0010` outbox пройдены; representative domain fixture отсутствует (M-004) |
| Восстановление сохраняет ledger | Пройден | Fresh backup, isolated restore `0010`, `ledger_mismatch_count=0`, drill DB удалена |
| Открытых critical/high нет | Пройден | Jira JQL: ровно CB-20/CB-21, оба `Готово`; open blocking set = `0` |
| Метрики и stop-условия доступны владельцу | Не пройден | Schema/runbook mismatch и неверная история karma activity (M-001, M-002), неполная test matrix (M-003) |
| Runbook запуска, мониторинга, отката и завершения проверен | Пройден | Immutable deploy/health/timer/backup/restore/rollback/closeout evidence; post-merge deploy честно оставлен будущим шагом |

Итог: `5/7` критериев пройдены, `1/7` закрыт частично, `1/7` не пройден.

## test_matrix_result

| Контур | Результат |
|---|---|
| E2E A — полный обмен | Пройден |
| E2E B — отмена/replay | Пройден |
| E2E C — спор/partial settlement/replay | Пройден |
| E2E D — карма/history/raw-read audit | Пройден |
| Critical concurrency/replay/outbox | Пройден в authoritative full regression |
| Пустая schema и base cycle | Пройден |
| Supported `0009→0010` | Частично: outbox/constraints доказаны, representative domain preservation — нет |
| Backup/restore/ledger/RPO/RTO | Пройден по фактическому self-hosted evidence |
| PII-free output boundary | Базовая negative проверка пройдена; имена schema и karma-history semantics требуют исправления |
| Полная формульная матрица metrics | Не пройдена: обязательные cases test-plan отсутствуют |
| Runbook/checklist/retrospective | Пройдены по структуре и ссылкам; checklist сейчас не совпадает с runtime keys |
| Итоговый quality gate | Принят: `369 passed`, `0 skip/deselect`, coverage `80.15%` |

## security_and_secret_result

- Secret-like scan изменённого diff и staged report не выявил учётных данных,
  приватных ключей, Bot API token или connection string.
- E2E использует зарезервированные синтетические Telegram ID и fake Bot API;
  реальных чатов и отправок не было.
- Фактический CLI output на проверенном периоде не содержит имён, Telegram ID,
  UUID участников, комментариев или материалов.
- M-001/M-002 относятся к корректности и операционному контракту, а не к
  обнаруженной утечке PII.

## workflow_result

- Уровень 3 подтверждён. Jira, `plan-source-context.md`, `plan.md`,
  `test-plan.md`, точный `Status: approved` в `plan-review.md` и staged
  implementation report присутствуют.
- Ветка `task/CB-16` содержит плановый commit, implementation commit и merge
  актуального `main`; combined index tree совпадает с переданным exact tree.
- Diff ограничен E2E/regression, pilot metrics и operational readiness; ключ
  Jira не используется в runtime names/logs/metrics.
- Staged index не изменён; `final-review.md` оставлен единственным unstaged
  артефактом ревью. Jira, Git remote, server state и Telegram не менялись.
- Post-merge release step описан честно: финальный CB-16 digest ещё не выпущен
  и должен быть штатно развёрнут до приглашения когорты; это не выдано за уже
  выполненное действие.

## required_actions

1. Привести serialized `community_bot.pilot_metrics.v1` к exact именам
   approved plan/runbook либо единообразно пересогласовать versioned contract;
   добавить assertion фактических JSON keys.
2. Строить karma activity из всех immutable revision и добавить PostgreSQL
   case «создание в предыдущей неделе → изменение в текущей».
3. Закрыть оставшиеся обязательные metrics cases test-plan отдельными точными
   assertions и синхронизировать implementation report с реально выполненным
   набором.
4. Расширить fixture `0009→0010` representative members/ledger/task/assignment/
   karma/moderation rows и доказать сохранение значений и FK после upgrade.
5. После единого исправления повторить только затронутые targeted checks,
   обновить implementation report и передать новый exact snapshot на повторное
   final review; полный regression повторно не нужен без изменения общего
   runtime-контура сверх этих исправлений.

## residual_risks

- Same-host backup не защищает от потери единственного сервера/диска; риск явно
  принят ADR-0009.
- Synthetic Telegram E2E не доказывает доступность внешней сети Bot API;
  реальная отправка корректно вынесена за отдельное разрешение владельца.
- Финальный immutable digest CB-16 появится только после merge и должен быть
  развёрнут с повторной health-проверкой до допуска когорты.
