# CB-73 — terminal blocker после final review

## Статус

`Status: resolved`

Owner amendment разрешил ровно один седьмой файл — существующий authoritative
UoW forwarder `infrastructure/db/database.py` — и absolute ceiling 550 строк.
Correction выполнен без нового слоя или owner: strict predicate и exact identity
передаются в существующий PostgreSQL query до `ORDER/LIMIT`; missing oracles
добавлены в прежние integration/browser файлы.

Независимый final review выявил корректный pre-limit defect: application
фильтрует broad `list_review_cards` уже после `ORDER BY/LIMIT 50`, поэтому
community rows могут вытеснить member-owned result, а exact detail вернуть
ложный `404`.

## Почему correction не выполнен

Чистое исправление обязано расширить существующий query seam параметрами
member-owned/freeform/submitted и exact assignment identity до применения
order/limit. Для этого одновременно нужны:

1. protocol/application call в `application/assignments.py`;
2. query predicate в `infrastructure/db/assignments.py`;
3. forwarding signature существующего UoW в `infrastructure/db/database.py`.

Третий путь становится седьмым implementation/test файлом. Остальные четыре
текущих файла нельзя убрать: `web.py` владеет HTTP contract, `app.js` — Mini App
journey, PostgreSQL/API test — privacy/replay/query oracle, browser test —
focus/dialog/retry/literal-render oracle.

Обход без седьмого файла требует скрыто кодировать query mode в UUID/tuple,
context variable или дублировать DB query вне текущего owner. Это нарушает
прямые запреты на нечитабельное сжатие, новый generic mechanism и duplicated
owner. Поэтому runtime/test diff после finding не изменён.

## Незакрытые обязательные действия

- pre-limit strict member-owned/freeform/submitted/test-scope query;
- exact detail query без зависимости от list limit;
- foreign list и inactive list/detail HTTP oracles;
- browser Back→focus и точный REJECT dialog oracle;
- полный targeted gate и повторный independent final review;
- commit/push/PR/CI/merge/release/activation/public smoke/Jira Done.

Предыдущий `final-review.md` остаётся историей finding; после полного targeted
gate требуется независимый re-review до публикации.
