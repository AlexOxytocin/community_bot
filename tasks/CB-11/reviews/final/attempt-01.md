# CB-11 — первая попытка финального ревью

`community_bot.final_review.verdict.v1`

Status: changes_requested

Проверенный staged tree: `a8a69ae43d243e71d2345a6ac03f4c8a257d1937`.

## Обязательные замечания

1. Для `origin=community` отсутствовал отдельный settlement: task snapshot не
   нёс origin, а расчёт всегда использовал member reward/refund.
2. Lifecycle-команды брали assignment row до task gate, тогда как deadline шёл
   в обратном порядке; это создавало цикл ожидания.
3. Deadline не возвращал резерв за незанятые и освобождённые slots.
4. Новый Telegram update для уже сохранённого решения не возвращал terminal
   outcome по business identity.
5. Отсутствовал сохраняемый Telegram input→preview→callback/restart сценарий
   отправки результата.
6. Сценарии 1–22 были доказаны только четырьмя assignment integration и тремя
   unit tests; не хватало concurrency, fault, community, SQL immutability,
   synthetic Telegram и economy correlation assertions.

Локально при этом проходили семь core tests, migration cycle, Ruff, ty, build,
entrypoints, diff, secrets и links. Полная регрессия CB-16 не запускалась.
