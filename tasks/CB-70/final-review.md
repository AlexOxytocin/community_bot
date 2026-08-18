# CB-70 — независимая финальная проверка реализации

**Status: approved**

## Результат проверки

Runtime implementation одобрена: текущая 20/80 реализация заменяет отклонённый
эксперимент и остаётся тонким web adapter поверх existing task engine. Diff
содержит ровно шесть runtime-файлов и `467 net LOC` против `origin/main`, не
добавляет table, migration, dependency, service, framework или route вне одного
GET/POST resource.

Условие owner amendment `<=500` соблюдено: дополнительные строки нужны для
actor-native replay, test-scope isolation и closed transport; domain rules
остаются в existing application/domain owners. Speculative abstraction и
скопированных business validators в transport нет. Реализация существенно
меньше отклонённого эксперимента `+1015/-53`.

## Закрытые findings

1. Direct web publish теперь fail-closed для template/community draft и не
   меняет legacy Telegram flow.
2. Publish replay повторно проверяет active test scope до выдачи immutable
   результата.
3. Explicit null и non-JSON payload получают `422`, а не внутреннюю ошибку.
4. Форма канонизируется до fingerprint только чистыми transport-операциями:
   strip строк, closed material keys и UTC projection. Deadline freshness,
   limits, reward, slots, materials и format/city валидируются existing domain
   функциями после `_begin_update` под draft lock.
5. Same-key save после наступления deadline проходит replay до time-dependent
   validation; отдельный integration oracle переводит clock за deadline.
6. Browser Back после publish возвращает каталог без неявного POST `start`.

## Проверки

- `ruff format --check`, `ruff check`, `ty check src tests ops` — green;
- финальная local unit/browser матрица — `26 passed`;
- предыдущая targeted PostgreSQL integration/unit матрица — `39 passed`;
- browser suite до финальной transport correction — `7 passed`;
- финальный PostgreSQL integration oracle собран, но локально не исполнен после
  последних guards: sandbox не даёт доступ к Docker pipe. Exact integration
  matrix обязательна в PR CI до merge;
- `git diff --check origin/main` — green;
- runtime ledger: `467 net LOC` в шести approved файлах.

## История и delivery gate

Первый независимый review отклонил эксперимент `+1015/-53`, выявил Back-history
defect и неполную isolation matrix. Эксперимент полностью удалён. Последующие
review findings по hidden draft publish, stale replay, malformed transport и
time-dependent pre-replay validation исправлены.

Текущий reviewer не нашёл новых code findings; plan и review синхронизированы с
фактическими `467 net LOC`. Approval разрешает commit/PR, но не заменяет green
PostgreSQL CI, merge, immutable release, production activation, public smoke и
Jira gate: эти действия ещё не выполнялись и остаются обязательными.
