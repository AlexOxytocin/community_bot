# CB-11 — вторая попытка финального ревью

`community_bot.final_review.verdict.v1`

Status: changes_requested

Проверенный staged tree: `5d14ee2e28d95dc9e6d145b2d11998f61cea208e`.

## Закрыто после первой попытки

- community full/partial/reject/no-show settlement;
- базовый единый lock order;
- refund свободных/cancelled slots;
- durable submission draft и router restart;
- last-slot/active-limit, fault и SQL immutability assertions.

## Остаточные обязательные замечания

1. Terminal business replay сверял outcome, но не exact
   `terminal_command_id`, поэтому принимал новый command.
2. Единственный завершённый submission draft не позволял создать result v2;
   synthetic Telegram test не доводил обмен до author full и не проверял stale
   callback.
3. В multi-slot task оплаченный slot считался свободным и мог быть назначен
   повторно.
4. Матрица 1–22 всё ещё заявлялась шире прямых assignment assertions.
5. Точная команда `uv run ty check` находила `int | None` в reserve oracle.

Affected suite: `70 passed`; Testcontainers assignment: `9 passed`; миграции,
build и entrypoints прошли. Полная регрессия CB-16 не запускалась.
