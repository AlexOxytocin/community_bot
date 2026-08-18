# CB-75 — план решения модератора по спору в Mini App

## Статус и ожидаемый результат

Уровень процесса: `3` — задача затрагивает authorization, privacy, экономику,
идемпотентность и конкурентное применение решения.

Наблюдаемый путь:

```text
active moderator/administrator → Модерация → открытый спор → безопасная карточка
→ выбрать реально допустимый исход и указать причину → явное подтверждение
→ существующий ModerationService применяет решение ровно один раз
```

Плановый terminal state: `approved fresh-remapped plan → full delivery`.
На 2026-08-18 CB-73 и CB-74 имеют Jira status/resolution `Готово`; CB-74
доставлена release `82/1`, public smoke green. Ветка `task/CB-75` создана от
точного `origin/main` `a62ed11c9f1f0fa98b0d42f440aa591cac9a4059`.

## Ponytail full: выбранный минимальный путь

Лестница останавливается на reuse. Уже существуют `ResolutionCode`,
`resolution_effect`, `ModerationService`, `ResolveCaseCommand`,
`SqlAlchemyModerationMutation.resolve_case`, transaction gate, receipts,
ledger, reliability, audit, outbox и moderation queue. Поэтому план:

- расширяет существующую очередь безопасной detail-проекцией;
- вызывает существующую application-команду решения;
- переиспользует HTTP mutation identity после fresh remap CB-73/CB-74;
- не добавляет schema, migration, dependency, service, repository, framework,
  generic admin panel или новую доменную абстракцию.

Удалено из области: appeals, sanctions, fraud-review UI, evidence upload,
interaction alerts, karma review, новые исходы и изменение экономики.

## Точная фактическая матрица исходов

Канонические значения находятся в `domain/moderation.py` и проверяются
повторно server-side при mutation.

| `ResolutionCode` | member origin | community origin | assignment | payout | reliability | дополнительный эффект |
|---|---:|---:|---|---|---|---|
| `full_payment` | да | да | `approved` | full | `approved` | нет |
| `partial_payment` | да | да | `partially_approved` | `ceil(50%)` | `partially_approved` | member remainder возвращается creator; community выпускает только фактическую сумму |
| `full_refund` | да | да | `rejected` | none | `rejected` | member reserve возвращается creator; community выпуска нет |
| `cancel_without_fault` | да | нет | `cancelled` | none | `cancelled_creator` | slot освобождается |
| `performer_no_show` | да | да | `no_show` | none | `no_show` | member reserve возвращается creator; community выпуска нет |
| `creator_abuse` | да | нет | `approved` | full | `approved` | private risk signal на creator |
| `fraud` | да, только administrator | да, только administrator | `rejected` | none | `rejected` | private risk signal; fraud case/reversal остаётся admin-only |

Mini App не хранит вторую матрицу. Detail owner возвращает allowlisted
`allowed_resolution_codes`, вычисленные текущим server owner из фактических
origin/case status/revision/actor role и существующего applicability rule.
Если это нельзя сделать без копирования правил, реализация останавливается.

## Scope и контракт

### Входит

1. Существующий `GET /api/v1/moderation/cases` остаётся очередью только
   `open|appealed`; moderator не видит `fraud_review`, administrator может
   видеть его, но CB-75 UI показывает только `case_type=dispute`.
2. Один detail route для кейса спора. Он возвращает только данные, необходимые
   решению: case ID/status/revision, task origin/title/reward, assignment status,
   nullable safe result summary из exact projection, принятой CB-73 после
   fresh remap, приватную причину спора только уполномоченному
   staff, и server-owned `allowed_resolution_codes`.
3. Один mutation route initial resolution (`status=open`, version 1) с
   `expected_revision`, code и обязательной reason. UI перед отправкой показывает
   точную сводку и требует явного подтверждения.
4. Route вызывает существующий `ModerationService.resolve` /
   `ResolveCaseCommand`; transport не вычисляет payout, status, reliability,
   conflict-of-interest или последствия ledger/outbox.
5. Один компактный integration scenario критического пути плюс обновление
   существующих route/privacy checks.

### Не входит

- appeal request или resolution версии 2;
- `fraud_review`, reversal UI, sanctions, karma и interaction alerts;
- просмотр raw evidence/reference, audit history, receipt/command IDs,
  Telegram IDs, member IDs, private hashes или ledger rows;
- новый moderation draft workflow: существующий durable Telegram draft не
  переносится в web, если один подтверждённый HTTP command уже обеспечивает
  exact replay/conflict;
- schema/model/migration, новый service/repository/framework/dependency;
- browser-side eligibility либо hardcoded origin matrix.

## Authorization, conflict-of-interest и privacy

- Queue/detail/mutation каждый раз загружают актуального member из PostgreSQL.
- Разрешены только `active` `moderator|administrator`; `member`, anonymous и
  non-active staff получают fail-closed ответ.
- Appeal и fraud остаются administrator-only даже при ручном HTTP-вызове.
- До выдачи actionable detail и повторно внутри mutation применяется один
  существующий conflict owner: actor не performer/creator, не inviter стороны,
  не автор её prior sanction; версию 2 не решает прежний administrator.
- Foreign, missing, resolved, test-run-invisible и конфликтный detail не
  раскрывают наличие приватного кейса и схлопываются в одинаковый публичный
  `404 not_found` либо один уже принятый fail-closed code без деталей причины.
- DTO whitelist-only, `extra=forbid`, `Cache-Control: no-store`. В list не
  добавляются dispute reason/result/evidence. Detail не выдаёт raw result
  payload, evidence reference, case payload hash, creator/performer IDs,
  command/receipt IDs, audit/ledger/outbox internals.
- `result_summary` переиспользует ровно safe projection, зафиксированную CB-73,
  и допускает `null`. Moderation route не читает и не сериализует произвольный
  `AssignmentResultVersionModel.payload_json`; если CB-73 не оставляет
  однозначной allowlisted projection, CB-75 показывает `null` и фиксирует gap.
- Логи и outbox не получают private reason спора или evidence; resolution
  outbox сохраняет текущий минимальный payload `{case_id, code}`.

## Test-run scope

Существующая queue сейчас не scoped по `TaskModel.test_run_id`; это transport
projection gap, а не новое доменное правило. Queue/detail/mutation должны
переиспользовать `active_scope`:

- staff вне active run видит и решает только обычные кейсы (`test_run_id IS NULL`);
- staff внутри active run видит и решает только кейсы того же run;
- прямой UUID не обходит scope;
- ledger и audit тестового решения остаются immutable, а task/assignment facts
  не попадают в pilot metrics по существующим правилам;
- текущий `moderation_case` outbox owner не фильтрует test-run recipients.
  Поэтому для task с `test_run_id` его существующая recipient branch обязана
  пересечь всех получателей с текущим `participant_ids`; active member, который
  больше не является active participant run, уведомление не получает.

Scope проверяется server-side до projection и ещё раз в mutation transaction.

## Receipt, exact replay и concurrency

Fresh remap подтвердил HTTP operation identity owner CB-74: actor загружается и
проверяется до update receipt, затем identity gate закрывает actor-native
receipt oracle, а stored marker сравнивает actor и canonical payload
fingerprint. Receipt identity связывает namespace, command, internal actor,
case ID и external `Idempotency-Key`; stored marker дополнительно связывает
fingerprint канонического payload `{expected_revision, code, reason}`.

- exact replay возвращает сохранённый outcome без нового эффекта;
- тот же scoped key для того же case с другим payload даёт `409` conflict;
- тот же внешний key на другом case образует отдельную resource-scoped identity,
  как в native CB-74 owner, и не является cross-case receipt conflict;
- новый key со stale revision даёт `409`, а не второе решение;
- case/assignment advisory gate и row locks оставляют одного победителя;
- resolution, assignment state, ledger, reliability, risk signal, audit,
  receipt и outbox фиксируются одной PostgreSQL transaction;
- rollback не оставляет частичных эффектов.

Если свежий `main` не имеет HTTP owner, который доказывает payload-bound exact
replay/conflict, это terminal blocker: CB-75 не создаёт собственную receipt
таблицу или bridge и не имитирует Telegram `update_id`.

## Фактические эффекты существующего движка

Initial dispute resolution создаёт одну append-only `dispute_resolutions`
version 1, меняет assignment terminal state, добавляет один reliability root,
применяет idempotent economy commands, при необходимости добавляет private risk
signal, создаёт один `moderation_case_resolved` outbox event, audit event и
recomputes interaction alert. `DisputeResolutionModel.command_id`, payload hash,
case revision, unique `(case_id, version)` и business keys защищают от дублей.

Web не меняет эту последовательность и не добавляет побочных эффектов.

## Минимальный порядок реализации после снятия gate

Fresh remap выполнен до runtime diff. Overlap CB-73/CB-74 не меняет source
ceiling, но уточняет reuse: safe result projection берётся из текущего
`AssignmentReviewDto`/assignment cards; web receipt ordering и payload-bound
replay — из CB-74 dispute mutation; route inventory расширяется ровно двумя
маршрутами ниже.

1. `src/community_bot/application/moderation.py`
   - расширить существующий owner actor-native detail/allowed-code projection;
   - добавить web-compatible resolve entrypoint только если CB-73/CB-74 не
     оставили универсальный ActorContext mutation path для reuse.
2. `src/community_bot/infrastructure/db/moderation.py`
   - расширить текущий `list_cases` и detail test-run scope через существующий
     `active_scope`;
   - переиспользовать один conflict/applicability owner для projection и
     `resolve_case`; не дублировать матрицу.
3. `src/community_bot/transport/web.py`
   - добавить whitelist detail/request/response DTO и два узких routes:
     `GET /api/v1/moderation/cases/{case_id}` и
     `POST /api/v1/moderation/cases/{case_id}/resolution`;
   - переиспользовать current auth/origin/idempotency/error helpers после remap.
4. `src/community_bot/transport/static/app.js`
   - сделать существующую moderation card открываемой;
   - добавить native detail/form/confirmation/result states без нового router,
     state layer или CSS component. `index.html`/`styles.css` менять только если
     существующие primitives реально не покрывают accessibility.
5. `src/community_bot/infrastructure/outbox/postgres.py`
   - в существующей ветке `aggregate_type == "moderation_case"` применить тот
     же `participant_ids` filter, который модуль уже использует для test-run
     review notifications; новый notification owner не создавать.
6. `tests/integration/test_web_api.py`
   - один end-to-end PostgreSQL scenario initial dispute resolution;
   - дополнить существующий moderation queue scenario scope/privacy checks.
7. `tests/browser/test_mini_app.py`
   - расширить существующий moderation UI scenario: detail, confirmation, 409,
     focus, keyboard и back; отдельный browser harness не создавать.
8. `tests/unit/test_web_auth.py`
   - обновить закрытый exact route inventory обоими маршрутами и operation
     identity checks, без отдельного дублирующего test file.

Soft target: 5 production files и 3 существующих test files; dependencies,
tables, migrations, services и repositories added: `0`.

## Проверки и критерии приёмки

Один compact web/PostgreSQL critical-path scenario обязан доказать:

1. active moderator видит обычный member-origin спор и только шесть non-fraud
   кодов; active administrator дополнительно получает `fraud`;
2. community-origin detail не содержит `cancel_without_fault` и
   `creator_abuse`; server отклоняет их даже при ручном POST;
3. member/non-active/anonymous, conflicted actor, foreign test run и direct UUID
   fail closed; list/detail exact key sets не содержат private internals;
4. confirmed `partial_payment` через existing command даёт ожидаемые state,
   `ceil(50%)`, creator remainder либо community issuance, reliability root,
   resolution, receipt, audit и один outbox event;
5. exact replay возвращает тот же outcome и не меняет counts/balances;
   payload conflict/stale revision не создают receipt или эффекты;
6. test-run кейс виден только staff того же run; outbox получатели пересекаются
   с current `participant_ids`, включая active бывшего участника как negative oracle.

Существующие `tests/integration/test_moderation.py` rollback и concurrent
one-winner scenarios остаются engine oracles и не дублируются в web scenario.
Существующий `tests/browser/test_mini_app.py` отдельно доказывает UI path queue
→ detail → confirmation → resolved/409, keyboard/focus/back и
loading/empty/error без обещания appeal/sanction.

Переиспользуются существующие moderation domain/integration tests; full product
regression и live Telegram account не входят. После merge обязательны новый
immutable release, production activation и public smoke до Jira `Done`.

## Stop и rollback

Остановиться с одним concrete blocker, если fresh remap показывает хотя бы одно:

- CB-73 или CB-74 не завершили production smoke;
- общий HTTP mutation owner не обеспечивает payload-bound exact replay/conflict;
- detail требует нового domain transition, schema/migration или копирования
  resolution/conflict/economy rules в transport;
- test-run isolation нельзя обеспечить существующим `active_scope`;
- test-run outbox recipients нельзя ограничить существующим `participant_ids`;
- shared web/static seams имеют неразрешённый overlap.

Rollback после будущего runtime diff — предыдущий совместимый application/static
artifact. Schema downgrade и data rollback не нужны, потому что schema не
меняется; уже зафиксированные immutable resolution/ledger/audit effects не
удаляются.
