# CB-59 — эскалация двух непройденных финальных ревью

Режим: `review_cycle` по R-008 и ADR-0007.

## Сохранённые попытки

- `final-review-attempt-1.md` — `Status: changes_requested`, SHA-256
  `84FFAC54C2F9327EC990893EB8E4323E1905B0EECD6FF74F4258A363CA801B4C`;
- `final-review-attempt-2.md` — `Status: changes_requested`, SHA-256
  `B251E177B5C5D207472EF61F69230D71CC005B875676C3D87238118614839AC7`.

Текущий `final-review.md` совпадает со второй попыткой и имеет SHA-256
`B251E177B5C5D207472EF61F69230D71CC005B875676C3D87238118614839AC7`.
Все три reviewer-owned файла сохраняются неизменными в этом remediation-цикле.

## Что произошло в двух попытках

Первая проверка нашла три самостоятельных fail-open класса: возможную коллизию
production и drill DB до destructive cleanup, потерю padding/blank cardinality
из-за `.strip()` и пропущенные orchestration cases. Один консолидированный цикл
устранил эти замечания и добавил прямые tests.

Вторая проверка подтвердила исправление первой группы, но воспроизвела более
низкий transport-level дефект. Функция с именем `capture_raw_text()` запускала
`subprocess.run(..., text=True)`. Universal-newline conversion превращала
реальные stdout bytes `CRLF` и одиночный `CR` в `LF` ещё до literal parser.
Поэтому последующий parser уже не мог отличить запрещённый протокол от
разрешённого.

## Корневая причина

Корневая причина не в текущем split/row-cardinality алгоритме, а в неверной
границе доказательства. Regression tests подменяли transport и передавали
готовый `str` непосредственно parser-у. Этот `str` находился уже после той
точки, где настоящий subprocess выполняет universal-newline normalization.
Такие моки доказывали поведение string parser, но не доказывали сохранность
исходных stdout bytes.

Иными словами, контракт назывался raw, а фактический seam был text-mode. Это
позволило двум зелёным уровням проверки описывать разные протоколы — классическая
щель ровно в один символ, только символ этот `\r` и умеет портить recovery gate.

## Одно консолидированное исправление

Последний разрешённый R-008 цикл использует один bytes-first контракт:

1. Transport захватывает `stdout` только как `bytes`, без `text=True`, encoding
   и universal-newline conversion.
2. Literal rows разделяются только байтом LF; удаляется не более одного
   терминального LF. Все внутренние/дополнительные blank rows сохраняются.
3. Image head принимается только как одна revision из ASCII-грамматики
   `[A-Za-z0-9][A-Za-z0-9_.-]*`. Эта грамматика является строгим ASCII-подмножеством
   UTF-8. Разрешены ровно `REVISION` или `REVISION\n`; CR, CRLF, invalid UTF-8,
   padding, blank и multiple rows отклоняются.
4. Production/restored DB revisions остаются bytes до exact equality с
   проверенным image head; никакого промежуточного text normalization нет.
5. Cleanup count также проверяется как ровно одна raw row `b"0"` или `b"1"`.
6. Regression запускает настоящий дочерний процесс, пишет через
   `sys.stdout.buffer` bytes `b"0020\r\n"`, `b"0020\r"` и invalid UTF-8 и
   проводит их через реальный capture seam и все три parser/gate boundary.

Исправление не меняет migrations, schema, release image CLI, DB-name collision
guard, restore/ledger порядок или внешние release boundaries.

## Критерии выхода

- reviewer-owned attempt/review files сохранили указанные SHA-256;
- transport не использует `text=True` и возвращает исходные stdout bytes;
- real-child regressions доказывают буквальное сохранение и отклонение CRLF,
  CR и invalid bytes для image, DB revision и cleanup count contracts;
- `REVISION` и `REVISION\n` проходят, а padding/blank/multiple остаются
  fail-closed;
- production/restored orchestration, collision, missing/empty backup,
  restore/ledger/cleanup матрица остаются зелёными;
- оба target coverage gate не ниже `90%`, exact/full type and lint gates,
  необходимый bounded smoke и repository tests проходят;
- migration diff, secret scan и внешние действия остаются пустыми.

## Terminal stop

После этого консолидированного исправления разрешена одна третья и последняя
полная независимая final review. Если она снова вернёт не `Status: approved`,
четвёртый remediation-цикл запрещён: работа останавливается, новая попытка
сохраняется, а дальнейшее решение явно запрашивается у владельца/техлида.
