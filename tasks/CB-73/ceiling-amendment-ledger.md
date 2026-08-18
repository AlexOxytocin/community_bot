# CB-73 — причинный ledger изменения diff ceiling

## Результат восстановления

После owner resolution второго final-review finding implementation/test diff
составляет 8 файлов, 553 добавления и 32 удаления. Абсолютный owner stop `<=560`
соблюдён.

Предыдущие 448 добавлений не были честным minimum slice: ради исходного
диагностического потолка были однострочно сжаты JS `catch`, удалены retry списка,
возврат фокуса, поля времени из DTO и UI, а проверки изоляции и side effects
переписаны в менее читаемую форму. Эти сокращения отменены.

## Причины 100 строк сверх исходных 450

- formatter-friendly loading/error/retry и back-focus состояния Mini App;
- `aria-live`, disabled mutation и exact-key retry сохранены без сокращений;
- literal result и performer остаются видимыми в списке и detail;
- DTO снова явно несёт `submitted_at` и `review_deadline_at`;
- browser oracle содержит полный контракт результата и проверяет literal render,
  REJECT confirm, сетевой retry с тем же ключом и authoritative refresh;
- PostgreSQL/API oracle читаемо доказывает member ownership, community creator /
  reviewer privacy, test-run isolation, PARTIAL eligibility, REJECT 24h freeze,
  replay/conflict и отсутствие duplicate ledger/reliability/outbox effects.
- Первый независимый amendment review выявил mutable-replay gap: прежний receipt
  ссылался только на assignment и после штатной финализации REJECT уже не мог
  доказать исходную команду. Existing receipt outcome теперь неизменно хранит
  actor, assignment и decision; replay сначала перепроверяет active actor,
  ownership и test-run scope. Oracles доказывают same-key replay после
  `finalize_rejection` и fail-closed replay для paused actor.
- Final review выявил pre-limit availability/privacy gap: broad community rows
  могли вытеснить member-owned result из `LIMIT 50`, а detail зависел от того же
  усечённого списка. Седьмой файл — только существующий UoW forwarder;
  PostgreSQL predicate теперь до order/limit, exact detail использует его же.
  Добавлены displacement, foreign list, inactive list/detail, Back→focus и exact
  REJECT-dialog oracles.

## Ponytail/reuse audit

- Новых table, migration, model, repository, service, framework и dependency нет.
- Domain rules не копируются: права и переходы остаются в `AssignmentService`,
  PARTIAL eligibility — в существующем `partial_reward`, проекция — в `_cards`.
- Web переиспользует actor session, Origin/JSON/idempotency helpers CB-70; UI —
  существующий vanilla shell и native `confirm`.
- Дальнейшее сокращение затрагивает критерии приёмки, читаемость тестов или
  accessibility/error/focus/privacy/exact-replay contract. Итоговый amendment —
  8 файлов и 553 additions; это absolute stop, не target.

## Exact route-contract amendment

GitHub CI PR #81 обнаружил единственный пропущенный authoritative oracle:
`test_web_config_and_route_set_are_closed` сравнивает точное множество route.
Исправление добавляет ровно три уже одобренных creator-review endpoint tuple в
существующий set. Runtime diff и его hash не изменены; wildcard, новый helper,
новый test file и ослабление assertion не добавлены.
