# CB-16 — отчёт общей регрессии и готовности пилота

## Результат

Готовый MVP проверен одним итоговым локальным полным regression после слияния двух обнаруженных
ранее blocking-багов. PostgreSQL 18 regression прошёл `369 passed`, без skip/deselect, с coverage
`80.15%`. Последующее независимое final review нашло два дефекта доказательного контура; по
правилу регрессии они заведены отдельными CB-22/CB-23, исправлены в собственных ветках и влиты
обратно в CB-16. Обязательные GitHub CI после каждого исправления прошли по `374 passed` с coverage
`80.14%` и `80.13%`. Свежий operational smoke на реальном self-hosted runtime подтвердил immutable
release, health, backup и isolated restore с нулевым расхождением ledger/cache.

## Критерии Jira

| Критерий | Статус | Доказательство |
|---|---|---|
| Регистрация, полный обмен, отмена, спор и карма | Пройден | Независимые PostgreSQL E2E A–D через production Dispatcher и fake Bot API |
| Критические гонки и повторная доставка | Пройден | Полный integration suite, replay каждого E2E, concurrency/fault/outbox tests |
| Пустая и поддерживаемая схема | Пройден | `0009 → 0010` с representative domain chain, пустой `head → base → head`, seed и operational constraints |
| Восстановление сохраняет ledger | Пройден | Свежий production backup, isolated restore `0010`, `ledger_mismatch_count=0` |
| Открытых critical/high нет | Пройден | Jira discovery содержит только закрытые CB-20–CB-23; open blocking JQL пуст |
| Метрики и stop-условия доступны | Пройден | Versioned PII-free JSON report, checklist и точные stop thresholds |
| Runbook пилота воспроизводим | Пройден | Immutable deploy, health, timer, backup/restore, rollback и closeout проверены |

## Сквозные сценарии

- **A — полный обмен:** invitation → registration → approval/starting grant → member task →
  acceptance → result → full decision → ledger/cache/experience/leaderboard/eligibility/outbox.
- **B — отмена:** незанятое опубликованное задание отменяется с одним refund, без опыта и
  назначения; повтор не создаёт эффект.
- **C — спор:** reject → durable private dispute → независимое partial resolution → точная
  выплата/возврат/reliability/audit/notification без повторного settlement.
- **D — карма:** paid interaction создаётся внутри сценария; две immutable vote revision,
  anonymous aggregate для пользователя и audit raw-read только для администратора.
- Test-only fixture отдельно доказывает использование только зарезервированных синтетических
  Telegram ID; реальные чаты и отправка сообщений не использовались.

## Регрессионные дефекты

JQL `project = CB AND labels = cb16-regression` возвращает ровно четыре задачи:

| Jira | Severity | Итог | Связи |
|---|---|---|---|
| CB-20 — безопасный bootstrap первого администратора | high | `Готово`, PR №17 merged | `Relates` и `Blocks` к CB-16 |
| CB-21 — полное меню и команды Telegram MVP | high | `Готово`, PR №18 merged | `Relates` и `Blocks` к CB-16 |
| CB-22 — exact JSON metrics и immutable karma retention | high | `Готово`, PR №19 merged в CB-16 | `Relates` и `Blocks` к CB-16 |
| CB-23 — representative oracle миграции `0009→0010` | high | `Готово`, PR №20 merged в CB-16 | `Relates` и `Blocks` к CB-16 |

JQL по открытым `severity-critical|severity-high` с label `cb16-regression` возвращает `0`.
CB-20/CB-21 обнаружены до итогового regression; CB-22/CB-23 найдены последующим независимым
final review и поэтому, по принятому правилу, исправлены как отдельные Bugs/branches.

## Метрики и приватность

- `community-pilot-report` выдаёт только schema `community_bot.pilot_metrics.v1`, фиксированные
  агрегаты и coarse buckets;
- public JSON и nested success используют exact утверждённые rate keys; PostgreSQL retention
  читает каждую immutable revision `karma_vote_history`;
- empty denominator сериализуется как `null`, counts — как `0`; UTC-период строго `[from,to)`;
- unit/integration tests покрывают границы `from`, `to`, `+48h`, full/partial/reject/cancel,
  retention, deterministic top-20%, small-cell merge/suppression и ledger-authoritative values;
- отчёт и runtime logs не содержат имён, Telegram ID, member UUID, комментариев, материалов или
  токенов.

## Итоговый локальный gate

- `uv sync --locked --all-groups` — успешно;
- PostgreSQL `18.4` healthy;
- `uv run ruff format --check .` — `317 files already formatted`;
- `uv run ruff check .` и `uv run ty check src tests` — успешно;
- `uv run pytest` — `369 passed`, `0 skipped`, `0 deselected`, coverage `80.15%`;
- explicit `DATABASE_URL` Alembic `head → base → head` — revision `0010`;
- `uv build` — sdist и wheel собраны;
- `community-bot --check`, `community-worker --check` — успешно;
- `community-pilot-report --from 2026-08-01T00:00:00Z --to 2026-08-08T00:00:00Z` —
  deterministic PII-free empty-period JSON;
- `git diff --check` — успешно.

После regression отдельно выполнены только целевые локальные проверки исправлений:

- CB-22: `9 passed`, exact CLI `22` top-level + `3` success keys, Ruff/ty/build/diff green;
- CB-23: representative migration oracle `1 passed`, Ruff/ty/diff green;
- GitHub Actions run `31515817454`: Quality success; PostgreSQL/Alembic `374 passed`, coverage
  `80.14%`;
- GitHub Actions run `31517497965`: Quality success; PostgreSQL/Alembic `374 passed`, coverage
  `80.13%`.

Первая дополнительная Alembic-команда без `DATABASE_URL` ожидаемо завершилась fail-closed и не
изменила БД. Authoritative cycle затем выполнен с явным локальным Compose URL и exit `0`. Полный
pytest после этого не повторялся: итоговый regression выполнен ровно один раз после merge всех
blocking fixes.

## Фактический self-hosted smoke

- актуальный accepted `main` развёрнут по immutable GHCR digest; migration gate `0010` успешен;
- PostgreSQL, worker и bot имеют `healthy`, backup timer — `enabled`/`active`;
- свежие worker/bot logs: `0` markers `error|exception|traceback`;
- новый backup создан `2026-08-11T16:43:50Z`, root-owned `0600`, размер `148629` bytes,
  возраст при проверке `2` секунды;
- isolated restore: `16:43:50Z → 16:43:52Z`, длительность `2` секунды, revision `0010`,
  восстановлено `4` members, `ledger_mismatch_count=0`; drill database удалена;
- цели `RPO <= 24h` и `RTO <= 4h` соблюдены; production DB не переключалась;
- реальные Telegram updates и сообщения не отправлялись.

После merge CB-16 release workflow должен выпустить финальный immutable digest. До приглашения
когорты этот digest требуется штатно развернуть тем же проверенным script и повторно подтвердить
health; это post-merge release step, а не незакрытая функциональная проверка.

## Остаточные риски

- Same-host backup защищает от логической порчи, но не от потери единственного сервера или диска;
  это явно принято ADR-0009.
- Synthetic Telegram E2E доказывает router/application/DB boundary, но не доступность сети Bot
  API. Реальная отправка без отдельного поручения владельца не выполнялась.
- Текущий production smoke выполнен на accepted `main`; финальный CB-16 digest появляется только
  после merge и должен быть развернут до старта когорты.
