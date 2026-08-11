# CB-16 — план проверки общей регрессии

## Правила выполнения

- Основной контур: настоящий PostgreSQL 18, синтетические Telegram updates,
  обезличенные test-only данные.
- Full regression запускается на полностью готовом CB-16 и затем один раз после
  слияния всех blocking-багов. Во время реализации выполняются только targeted
  тесты изменяемой области.
- Любой `skip`, `deselect`, warning-as-error, coverage failure или скрытая
  зависимость от локальной production-конфигурации считается непройденным gate.
- Реальная Telegram-отправка не является частью автоматического gate и требует
  отдельного разрешения владельца.

## Матрица критериев Jira

| Критерий | Результат | Воспроизводимая проверка |
|---|---|---|
| Регистрация и полный обмен | Сценарий A от invite до выплаты и leaderboard | `tests/e2e/test_pilot_scenarios.py::test_full_exchange` |
| Отмена | Один refund, ноль опыта, task недоступен | `tests/e2e/test_pilot_scenarios.py::test_unaccepted_task_cancellation` |
| Спор | Durable dispute и частичное решение без двойной выплаты | `tests/e2e/test_pilot_scenarios.py::test_dispute_partial_resolution` |
| Карма | Eligibility, anonymous aggregate, две raw revisions с audit | `tests/e2e/test_pilot_scenarios.py::test_karma_after_paid_interaction` |
| Concurrency и replay | Нет lost update, overdraw, duplicate effect/outbox/receipt | Полный `tests/integration/` плюс сценарии ниже |
| Пустая/поддерживаемая схема | `base→head`, empty cycle и `0009→0010` сохраняют данные | `tests/integration/test_pilot_readiness.py` |
| Restore и ledger | Restore DB на `0010`, mismatch count = 0 | `ops/restore_drill.sh BACKUP_FILE` |
| Нет critical | Каждый defect найден JQL, имеет severity/outcome; blocking critical/high закрыты | `labels=cb16-regression`, Jira links и implementation report |
| Метрики/stop | Владелец получает PII-free JSON и checklist | pilot-report tests + проверка документов |
| Runbook | Release/health/backup/restore/rollback/closeout выполнимы | production operational smoke и checklist |

Каждый E2E использует собственную временную DB и реальный aiogram
Dispatcher/router/callback path с fake Bot API. Setup helpers не разделяют
mutable state; DB assertions выполняются после transport flow.

## E2E A — полный обмен

1. Администратор создаёт два ограниченных приглашения.
2. A и B завершают регистрацию; moderator одобряет обе заявки.
3. Повтор одобрения и повтор update возвращают прежний outcome; у каждого один
   `starting_grant`, credits `5`, experience `0`.
4. A публикует member-task за `2`; reserve и task создаются одним commit.
5. B принимает последнее место и сохраняет v1 результата.
6. A подтверждает full; duplicate callback не создаёт второй ledger/outbox.
7. Проверить: A available credits `3`, B credits `7`, B experience `2`, сумма
   ledger равна кэшам, assignment/task terminal, eligibility A↔B есть,
   leaderboard использует опыт.

## E2E B — отмена

1. A публикует незанятый task за `2`.
2. A отменяет; повтор и конкурентная отмена возвращают terminal outcome.
3. Проверить один refund, нулевую дельту опыта, отсутствие assignment и
   недоступность task в каталоге.

## E2E C — спор

1. B отправляет результат, A отклоняет его с сохранённым окном `24h`.
2. B открывает dispute с приватным комментарием; повтор update не создаёт вторую
   запись и не копирует текст в outbox/log.
3. Независимый moderator без конфликта выбирает `partial_payment`.
4. Проверить `ceil(2*50%)=1`, возврат остатка A, experience B `+1`, terminal
   assignment, reliability correction/audit/notifications и отсутствие второго
   расчёта при replay.

## E2E D — карма

1. В собственном setup D общий helper создаёт завершённую оплаченную
   member-assignment, после чего A выставляет B `+1` с валидным комментарием.
2. B и moderator видят только aggregate/count.
3. A меняет оценку на `-1`; aggregate меняется на `-2` относительно предыдущего.
4. Active administrator с `karma_review` читает текущую строку и обе history
   revision; каждый raw-read создаёт audit. Неуполномоченный callback не
   создаёт эффекта.

## Критические cross-cutting проверки

1. Два принятия последнего slot и limit `3` — один победитель, без deadlock.
2. Две публикации на один доступный баланс — один полный reserve, no overdraw.
3. Submit против deadline, dispute против финализатора, review против deadline —
   один terminal outcome и ровно один economy effect.
4. Повтор update/callback после commit, timeout и restart возвращает stored
   outcome; payload conflict отклоняется.
5. Community full/partial/reject/expiry не использует member reserve и не
   допускает reviewer/performer conflict.
6. Profile/raw-karma/admin callbacks повторно проверяют status, role,
   permission, ownership и не раскрывают существование скрытой записи.
7. Outbox/notification lease fencing, retry limit, deduplication и privacy
   allowlist сохраняются при двух workers.
8. Начальная пустая база имеет исполнимый, документированный путь создания
   первого администратора; отсутствие пути — отдельный blocking bug.
9. Зарегистрированные команды/кнопки сопоставлены каноническому
   `05_BOT_INTERFACE.md`; команда, обещанная пользователю, не может молча
   отсутствовать или вести в технический тупик.

## Jira discovery для регрессионных багов

1. Каждый новый Bug имеет `cb16-regression`, ровно один severity label и
   `Relates` к `CB-16`; blocking critical/high дополнительно `Blocks CB-16`.
2. JQL `project = CB AND labels = cb16-regression` равен полному списку defects
   в implementation report без пропусков и посторонних задач.
3. JQL по open `severity-critical|severity-high` возвращает `0`.
4. Каждый open medium/low имеет `decision-accepted|decision-deferred` и ссылку
   на явное решение владельца.

## Миграции и восстановление

1. Новая пустая DB: `alembic upgrade head`; seed = 8 категорий/8 шаблонов,
   active product config валиден.
2. Пустая DB: `head→base→head` без остаточных объектов.
3. DB на `0009` с members, ledger, task/assignment, karma и moderation history:
   upgrade `0010`, все строки и FK сохранены. Unpublished/published outbox
   становятся соответственно `pending`/`materialized`, сохраняя business key,
   payload и timestamps; `ck_outbox_*`, due indexes, notifications и heartbeats
   отклоняют невалидные operational states; повтор `upgrade head` безопасен.
4. Свежий production backup: isolated restore без cutover; revision `0010`,
   обязательные таблицы доступны, ledger/cache mismatches = `0`.
5. Зафиксировать age backup, duration restore, `RPO <= 24h`, `RTO <= 4h`; drill
   DB удалена, production не изменена.

## Метрики и документы

1. Пустой UTC-период даёт counts `0`, rates/median `null` при пустом denominator
   и валидный `community_bot.pilot_metrics.v1`.
2. Табличные cases ставят события ровно на `from`, `to`, `+48h`, full, partial,
   rejected и cancelled; `[from,to)` и maturity не считают событие дважды.
3. Onboarding cohort, task fill, completion и repeat-action проверяют точные
   numerator/denominator из plan; три success thresholds читают только
   `task_fill_rate`, `assignment_completion_rate`, `repeat_action_rate`.
4. Cross-week activity проверяет retention; равные completion counts —
   deterministic top-20% tie; SQL не выводит tie-break UUID.
5. Credit/experience bucket с count `1|2` объединяется либо подавляется;
   schema запрещает dynamic/member keys, UUID, Telegram ID, raw labels/text и
   participant event timestamps.
6. Report считает rewards и distributions по immutable ledger даже при
   намеренно отличающемся cache; reconciliation отдельно сообщает mismatch.
7. Набор данных с A–D даёт ожидаемые counts/rates и deterministic JSON.
8. Daily checklist содержит release, health, errors, failed outbox,
   reconciliation, backup age, metrics и решение `continue|pause|stop`.
9. Runbook содержит preflight, normal release, partial rollback, restore,
   monitoring, stop и closeout; retrospective остаётся честным пустым шаблоном.

## Итоговый gate

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check src tests
uv run pytest
uv run alembic downgrade base
uv run alembic upgrade head
uv build
uv run community-bot --check
uv run community-worker --check
```

Ожидается: exit `0`, `0 skipped`, `0 deselected`, coverage `>=80%`, PostgreSQL
18, чистый diff-check, валидные Markdown-ссылки и отсутствие секретоподобных
значений. CI PR повторяет quality и полный PostgreSQL gate. Production smoke
добавляет healthy services, immutable digest, fresh backup, isolated restore и
нулевую ledger reconciliation.
