# CB-30 — контекст источников плана

## Jira

- CB-30, High, `severity-high`, `cb16-regression`, статус `В работе`;
- родитель CB-2 завершён;
- CB-30 относится к CB-29 и блокирует CB-24;
- пять критериев Jira перенесены в `plan.md` и сценарии 1–22 `test-plan.md`.

## Код и данные

- `transport/telegram/assignments.py` сейчас раскрывает assignment/draft UUID,
  revision и JSON-команды; review callback существует, но не выдаётся очередью;
- `application/assignments.py` уже содержит атомарные accept, result draft,
  decision, dispute, payout/refund/community reward и replay;
- `transport/telegram/moderation.py` требует case/member/sanction UUID и reason,
  хотя application/infrastructure уже имеют durable preview, appeal, sanctions и
  interaction alert settlement;
- `transport/telegram/reputation.py` выводит member UUID и требует
  `/karma_comment <revision>`, при этом karma draft уже хранится в
  `conversation_states`;
- `transport/telegram/tasks.py` требует JSON, ISO timestamp и скрытые команды;
- `tasks.origin=community` и settlement-ветка существуют, но production task
  creation hardcode-ит `member`; фактическая schema не хранит канонические
  `created_by_admin_id`/`reviewer_admin_id`, а review допускает любого admin;
- `_dispatcher` создаёт сервисы повторно и conversation router пробует task до
  registration, не имея единого durable владельца текста;
- `/mod_fraud` и административная raw-karma moderation остаются скрытыми
  командами/не имеют transport UI.

## Принятые решения

- D-007—D-010: уровни, assignment settlement, review/dispute windows и
  interaction policy;
- D-023: матрица moderator/administrator, appeals, sanctions, fraud, karma и
  interaction alerts;
- ADR-0006: update receipt, identity/advisory gates и effect-before-complete
  receipt внутри одного UoW;
- принятый MVP-каталог использует одну `standard_input` и одну
  `standard_result` schema, поэтому transport может дать простой русский ввод
  без универсального form builder.

## Проверяемая матрица Jira

| Критерий Jira | Результат | Проверка |
|---|---|---|
| output-driven UI всех перечисленных областей | карточки и callbacks без ручных ID | сценарии 1–21 |
| роли и права на каждом mutation | повторная application-авторизация | 4, 8–19, 23 |
| production Dispatcher, без DB-driven input | captured Bot API chain | правило E2E, 1–24 |
| member/community/no-show/reversal/penalty | ledger и status oracles | 5–20 |
| idempotency и ledger invariants | exact replay/concurrency/no duplicate effects | 2, 5–13, 17–23 |

## Исключения

Новые продуктовые формулы, веб-интерфейс, универсальная динамическая форма,
другая transport-технология и полная регрессия продукта в CB-30 не входят.
