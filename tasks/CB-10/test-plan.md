# CB-10 — целевой план проверки

## Контур

- PostgreSQL 18 в Compose/Testcontainers с временной БД на integration test;
- реальный ledger/cache UoW и активная product config;
- synthetic aiogram без Bot API;
- только CB-10 и непосредственно затронутые catalog/economy/registration/
  migration/architecture tests, без полной регрессии MVP.

## Сценарии

| № | Сценарий | Обязательный результат |
|---:|---|---|
| 1 | Upgrade пустой БД и `0005→0006→0005→0006` | Схема воспроизводима, seed каталога сохраняется, task rows не дублируются |
| 2 | Создание двух drafts, current switch/resume и каждый FSM-шаг с expected step/revision | Оба draft долговечны, current один; состояние продвигается один раз; stale/replay не меняет draft |
| 3 | Перезапуск между шагами и на preview | Новый service/router восстанавливает тот же draft, payload и callback revision |
| 4 | Input required/type/unknown fields | Ошибка до записи следующего шага и до task/economy effect |
| 5 | Deadline past/equal/naive и future UTC | Первые три отклоняются, будущий принимается и повторно проверяется при publish |
| 6 | Template online/offline/any, city и slots boundaries | Format/city совместимы, slots `1..maximum_performers` |
| 7 | Preview | Показаны snapshot, per-slot reward и полный reserve; balance/ledger неизменны |
| 8 | Недостаточный баланс | Нет task, reserve, audit, outbox и receipt; draft остаётся preview |
| 9 | Exact publish callback replay | Один task, один reserve, один audit/outbox/receipt; возвращается тот же task |
| 10 | Другой update с тем же publish command | Возвращает тот же task при совпадении identity; конфликт payload/revision не создаёт эффектов |
| 11 | Два принудительных расписания publish против deactivate/new version; отдельно activation level config | Mutation-first: publish отклонён без task/reserve/audit/outbox/receipt; publish-first: обе операции commit, task хранит старый snapshot; оба с timeout без deadlock; level решён по одной exact config version |
| 12 | Два preview drafts, созданные публичным API; concurrent publish с разными keys, средств хватает на один | Ровно один полный task/reserve/outbox/receipt; у проигравшего нет эффектов; balance неотрицателен; retries детерминированы, timeout без deadlock |
| 13 | Failure injection после ledger flush, task flush, outbox и receipt | Вся транзакция откатывается; retry создаёт один полный результат |
| 14 | Мои задания и keyset | Actor видит только свои rows, status filter/cursor без дублей, чужие приватные поля не читаются |
| 15 | Чистая acceptance eligibility на заблокированном snapshot с явным `ResolvedLevel` | Автор и недостаточный authoritative level отклоняются; достаточный проходит; намеренно stale cached level не влияет; slot/assignment checks остаются CB-11 |
| 16 | Корректная отмена до assignment | Точный полный refund, experience `0`, status cancelled, один audit/outbox/receipt |
| 17 | Exact replay/конкурентная двойная отмена | Exact replay возвращает terminal outcome; из двух разных update commit получает один, конкурент отклоняется; один refund и один receipt |
| 18 | Чужой/paused actor и уже cancelled task | Отмена отклоняется без второго refund/status/audit/outbox/receipt; assignment-aware cancel перенесён в CB-11 |
| 19 | Telegram restart/preview/publish/list/cancel | Persistent flow восстанавливается; callbacks ≤64 bytes; invalid/stale/replay без частичных эффектов |
| 20 | Direct SQL invariants | Snapshot/delete/origin-reserve checks отклоняют нарушение; outbox business key уникален |
| 21 | Контроль готового diff | Targeted pytest, Ruff, ty, migration, diff/link/secret scans дают exit 0 |

## Соответствие Jira

- недостаточный баланс: 8, 12–13;
- повторный callback: 2, 9–10, 19;
- deadline: 5, 11;
- автор не принимает своё: 15;
- точная отмена без опыта: 16–18;
- restart восстанавливает draft: 3, 19;
- конкурентные публикации и неотрицательный баланс: 12–13.

## Правило дефектов

Дефекты, найденные до завершения реализации и targeted-проверки CB-10,
исправляются в этой ветке. Полная регрессия выполняется после готовности MVP в
CB-16; впервые найденные там дефекты получают отдельные Jira-задачи и ветки.
