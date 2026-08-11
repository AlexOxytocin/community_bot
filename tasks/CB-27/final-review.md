# CB-27 — финальное ревью

Status: approved

Схема: `community_bot.final_review.verdict.v1`.

## reviewed_scope

- Jira `CB-27`, blocking-связь с `CB-26` и relation с исходной notification-задачей `CB-15` свежо прочитаны напрямую через Atlassian Rovo API.
- Проверены `plan.md`, `test-plan.md`, `implementation-report.md` и полный staged diff на ветке `task/CB-27`.
- Ревью выполнено на HEAD `342370f8180f750e2e648a01228850a281eca681`, exact frozen staged tree `23760a31b2f9ffbe3c6313f7ecf521be1080d0ed`.
- Независимо повторён согласованный targeted gate: `uv run pytest -q --no-cov tests/integration/test_notifications.py` — `5 passed`; Ruff format/check, targeted ty, staged diff-check и secret scan — успешно. Локальный full suite не запускался: authoritative PostgreSQL full-suite остаётся GitHub CI gate после публикации PR.

## critical_findings

Нет.

## major_findings

Нет.

## minor_findings

Нет.

## acceptance_matrix_result

| Критерий Jira | Результат | Доказательство |
|---|---|---|
| Test timestamps фиксированы и не зависят от wall clock | Пройден | `_IN_WINDOW_UTC = 2026-01-15 12:00 UTC`; seed/outbox принимают явный aware timestamp |
| Оба исходно failing tests проходят в любое время runner | Пройден | Immediate delivery и reminder invalidation используют одну фиксированную временную шкалу; notification file даёт `5 passed` |
| Production `DeliveryWindow [09:00, 21:00)` не ослаблен | Пройден | Staged diff не содержит production/config/schema файлов; существующие boundary/DST unit-oracles не изменены |
| Targeted notification file, Ruff и ty успешны | Пройден | `5 passed` без skip/deselect; Ruff/ty/diff clean |
| Повторный GitHub CI | Ожидает внешнего gate | Implementation report честно фиксирует, что full PostgreSQL suite будет запущен после публикации PR; merge до зелёного CI не допускается |

Локально проверяемая область пройдена полностью; отложенный GitHub gate не требует изменения frozen реализации.

## test_matrix_result

| Сценарий test-plan | Результат |
|---|---|
| 1. Немедленная доставка независима от wall clock | Пройден; materialize и один worker tick выполняются в 12:00 UTC |
| 2. Три obsolete reminder становятся `failed` | Пройден; все due timestamps находятся внутри UTC delivery window, поэтому invalidation проверяет статус, а не перенос окна |
| 3. Readiness cleanup без вторичных warnings | Пройден; весь файл завершился успешно, unclosed-resource/unraisable warnings отсутствуют |
| 4. Весь notification integration file | Пройден; `5 passed`, без skip/deselect |
| 5. Ruff/ty/diff и GitHub CI | Локальная часть пройдена; full GitHub CI остаётся обязательным post-publication gate |

## security_and_secret_result

- Изменены только synthetic integration fixture и русские task artifacts; production sender, worker, queue, schema и policy не менялись.
- Test payload `must-not-be-copied` остаётся искусственным oracle и проверяет, что outbox token-like поле не попадает в notification payload.
- Staged secret scan чист; Bot API token, connection credentials и реальные пользовательские данные отсутствуют.
- Внешних Telegram отправок нет: `_Sender` только записывает synthetic Telegram IDs в память теста.

## workflow_result

- Scope соответствует отдельному CI Bug: один integration test file и три обязательных артефакта задачи.
- Причина обоих Jira failures закрыта без изменения поведения продукта: immediate test синхронизирует task/outbox/worker timestamps, reminder test синхронизирует published/submitted/due timestamps.
- Фиксация времени не маскирует delivery-window policy: production code неизменён, а существующие unit-oracles по pre-window, post-window, timezone, DST и deadline остаются в репозитории.
- Implementation report не выдаёт ещё не запущенный повторный GitHub CI за успешный и корректно оставляет его внешним gate до merge.
- Frozen index после ревью остаётся `23760a31b2f9ffbe3c6313f7ecf521be1080d0ed`; Jira, code/index, remote, Telegram и server не изменялись. Approved review оставлен unstaged.

## required_actions

Нет изменений к реализации. После публикации PR обязательны зелёный GitHub PostgreSQL full-suite и запрет merge при его failure.

## residual_risks

- Локально не повторялся весь suite по явной границе CB-27; возможная межфайловая проблема остаётся под authoritative GitHub CI gate.
- Tests, которые намеренно проверяют lease/retry progression через относительный `datetime.now(UTC)`, не были механически заморожены: их assertions зависят от относительных интервалов, а не от попадания в одно конкретное delivery window.
