# CB-11 — целевой план проверки

## Контур

PostgreSQL 18, реальные CB-7 economy и CB-10 task UoW, synthetic aiogram.
Только CB-11 и непосредственно затронутые economy/task/migration boundaries;
полная регрессия остаётся CB-16.

## Сценарии

| № | Сценарий | Обязательный результат |
|---:|---|---|
| 1 | Empty upgrade и `0006→0007→0006→0007` | Схема/constraints/triggers воспроизводимы |
| 2 | Два active участника одновременно принимают последний slot | Ровно один assignment, второй получает отказ без receipt/effects |
| 3 | Self/low-level/paused/expired/duplicate/active-limit accept | Все отклоняются; cached level не обходит `ResolvedLevel`; при двух active и двух конкурентных accept разных tasks ровно один доводит счётчик до configurable лимита 3 |
| 4 | Accept exact replay и новый command после сохранённого assignment | Exact replay стабилен; conflict не дублирует slot/reliability/receipt |
| 5 | Performer cancel с каждой responsibility до submit | Slot освобождён; reliability event корректен; reserve не возвращён; прямой SQL и две конкурентные replacement-попытки дают ровно одну новую assignment в том же slot |
| 6 | Submit v1 и v2 по historical result schema | Две append-only versions; current payload v2; review deadline от v1 не сдвинут; конкурентные submits получают последовательные версии без потери |
| 7 | Invalid/stale/foreign/after-deadline submit | Нет version/status/audit/outbox/receipt |
| 8 | Full decision и exact/business replay | Одна полная выплата+опыт, terminal state, audit/outbox/receipt один раз |
| 9 | Partial rewards `1/2/3/4/5/11` | Для 1 отказ; выплаты `1/2/2/3/6`, остаток reserve точно возвращён |
| 10 | Reject и dispute до/на 24h | До границы immutable dispute с приватным comment и без comment в outbox/log; exact/concurrent retry один; на границе один refund/rejected |
| 11 | Manual review за микросекунду до 72h и finalizer на границе | Только один terminal settlement |
| 12 | Submit против deadline finalizer | Ровно submitted review либо no-show+refund, без mixed outcome |
| 13 | Cancel task против accept и decision против cancel | Один сериализованный исход, reserve invariant сохранён, timeout без deadlock |
| 14 | Multi-slot deadline/settlement aggregate | `settling` → exact expired/partial/completed; payout+refund исчерпывают reserve |
| 15 | Failure injection ledger/assignment/result/outbox/receipt | Полный rollback; retry даёт один полный outcome |
| 16 | Community-origin fixture full/partial/reject/no-show | Нет author balance/reserve; один system issue либо отсутствие выпуска |
| 17 | Direct SQL constraints/immutability | Нет duplicate occupied slot/performer/version/command; cancelled slot заменяем; result/reliability/dispute history append-only |
| 18 | Outbox privacy и business keys | Payload без result/private comments; события уникальны |
| 19 | Synthetic Telegram restart/full exchange | Accept→submit→author full проходит; callbacks ≤64; stale/exact replay безопасны |
| 20 | Финальный gate | Targeted pytest, Ruff, ty, build, entrypoints, diff/link/secret scans успешны |
| 21 | Product config v1→v2→v1 и существующая БД | Повторный ingest исходного v1 сохраняет прежний hash/replay; v2 ingest/activate даёт лимит 3; rollback применяется к новым accept без отмены существующих |
| 22 | Correlated economy batch | all-new/all-stored replay успешен; иной task/assignment под тем же key конфликтует; legacy reserve/refund hash и migration replay стабильны; fault даёт общий rollback |

## Jira AC

- последнее место: 2, 13;
- недопустимый переход: 3, 5, 7, 10–13;
- versioned result: 6–7, 17;
- full exactly once: 8, 11, 15;
- partial rule: 9, 14, 16;
- dispute freezes: 10, 16;
- cancel/review concurrency: 12–14;
- полный обмен: 19.

## Дефекты

До готового CB-11 targeted gate дефекты исправляются в этой ветке. Впервые
найденные на полной регрессии CB-16 получают отдельные Jira issues/branches.
