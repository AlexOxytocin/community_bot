# CB-73 — план проверки результата создателем задания

## Статус и граница запуска

`Status: ready`

Уровень процесса: `2`. Это ограниченный web-slice поверх существующих
application/domain владельцев без schema, architecture или dependency change.
Независимое plan review всё равно обязательно из-за privacy, exact replay и
ledger/outbox gates и прямого поручения владельца.

Fresh remap выполнен по live Jira CB-73 и `origin/main` на exact CB-70 merge
`d1733cb49ff59a74e893320c19c15d58102b2045`. CB-70 gate снят владельцем.
Merged actor-native fingerprint/receipt helpers и текущий vanilla shell
переиспользуются; file ownership, контракт и diff ceiling плана не изменились.

Owner/Jira correction от 2026-08-18 сняла исходный контрактный разрыв:
пользовательские действия — «Принять полностью / Принять частично / Отклонить».
`REJECT` честно означает переход в `rejected_pending_dispute` на 24 часа с
замороженными выплатой/резервом и без обещания новой версии результата.

## Проверенная карта переиспользования

- `_cards` уже владеет safe projection и active test-run scope, но существующий
  `list_review_cards` намеренно шире CB-73: он включает `creator_id`,
  `created_by_admin_id` и `reviewer_admin_id`. Публиковать эту выборку напрямую
  нельзя. List и detail CB-73 используют один узкий member-owned predicate:
  `TaskModel.creator_id == actor.member_id` и assignment `submitted`.
- `AssignmentService.decide` уже владеет ownership/role checks, deadline,
  полной/частичной выплатой, refund, ledger, reliability, receipt,
  outbox, task aggregate и транзакционной атомарностью.
- `AssignmentCard` и `_cards` уже дают безопасную проекцию задания,
  исполнителя и последней версии результата. Для free-form результата нужно
  переиспользовать поле `result`; raw payload и внутренние идентификаторы не
  выдавать.
- Web foundation уже даёт server-side session → `ActorContext`, Origin check,
  bounded JSON, строгий `Idempotency-Key`, no-store ответы и детерминированные
  transport identity helpers.
- Текущий shell уже содержит «Мои задания», список, detail, focus/back/loading/
  error patterns и authoritative refresh после mutation. Новый framework,
  router или state manager не нужен.

## Минимальный working slice после снятия gates

План применяет только существующую семантику `FULL / PARTIAL / REJECT`.

1. Обновить рабочую копию от актуального `origin/main`, проверить merge CB-70
   и только затем создать/обновить `task/CB-73` без потери несвязанных правок.
2. Добавить в существующий `AssignmentService` узкий actor-native read/decision
   seam поверх тех же UoW-владельцев. Exact replay обязан сверять actor,
   assignment, command и canonical decision fingerprint; same key + same
   command возвращает прежний outcome, same key + different decision даёт
   deterministic conflict без эффекта.
3. Переиспользовать `_cards` для creator-scoped списка и detail, но не
   публиковать широкий `list_review_cards`: один application filter
   `card.task.creator_id == actor.member_id` обслуживает оба чтения без нового
   UoW method, слоя или repository. Application projection сообщает допустимые решения из
   существующего domain owner: reward `1` исключает `PARTIAL`, reward `>=2`
   включает его через `partial_reward`; UI это не вычисляет. Foreign/inactive
   actor, community-task creator/reviewer, terminal/непроверяемый assignment и
   чужой test-run fail closed; projection показывает только необходимый
   literal result и безопасные display fields.
4. Добавить минимальные API routes в существующий FastAPI transport: список
   ожидающих проверки, detail и одна decision mutation. Transport не вычисляет
   права, reward, статусы или deadline и после mutation перечитывает
   authoritative state.
5. В существующем vanilla JS shell добавить под «Мои задания» компактный путь
   «Созданные мной → результат → Принять полностью / Принять частично /
   Отклонить» с явным описанием последствий `REJECT` до confirm,
   disabled/loading, ошибкой, back/focus и literal text rendering. Dispute UI,
   история и generic workflow renderer не входят.
6. Добавить один PostgreSQL/API critical-path test, который вместе проверяет
   safe projection, ownership, test-run isolation, exact replay/conflict и
   zero duplicate ledger/reliability/receipt/outbox effects без нового audit
   behavior, и один browser journey для
   literal result, confirm, refresh, retry и focus/error basics. Существующие
   assignment/domain regression tests менять только при доказанной необходимости.
7. После targeted checks выполнить независимый Ponytail/diff final review,
   commit/push/PR, дождаться green CI/review и merge. Затем получить новый exact
   release artifact, выполнить manual-first production activation и public
   smoke по ADR-0019. Jira `Done` допустим только после green smoke.

## Числовой diff ceiling

- approved owner amendment: не более 7 implementation/test файлов;
- не более 550 добавленных строк без учёта task-артефактов; owner absolute
  stop — 550 добавлений;
- 0 новых tables, migrations, models, repositories, services, frameworks и
  dependencies;
- 0 изменений доменных reward/status/permission/test-run правил.

Превышение любого потолка останавливает реализацию для повторного Ponytail-
сокращения или owner decision; автоматически расширять scope нельзя.

## Reuse и delete-first gates

- Сначала удалить дублирующую transport/UI логику, если после merge CB-70
  появился общий actor-native receipt или owned-task pattern; второй вариант
  того же helper не создавать.
- Использовать существующие `AssignmentDecision`, `AssignmentCard`, UoW,
  receipt, ledger, audit, outbox, test-run scope и vanilla JS patterns.
- Не копировать ownership, deadline, payout или status transition в web/JS.
- Не добавлять комментарии `ponytail:`: для этого slice не ожидается осознанный
  технический потолок, требующий будущей upgrade path.

## Stop gates

Немедленно остановиться и сообщить Оркестратору, если:

- формулировка снова требует «вернуть на доработку» или resubmission после
  `REJECT`;
- exact web replay требует нового persistence owner или не может использовать
  существующий receipt в одной транзакции с decision effects;
- actor-native seam нельзя отделить от Telegram identity/conversation state;
- creator privacy или test-run isolation требуют transport-side правил;
- после merge CB-70 контракт web shell конфликтует с этим plan или diff
  превышает ceiling;
- нужны schema/dependency/architecture changes либо расширение в partial,
  disputes, history, admin UI или generic workflow.

## Критерии проверки после разблокировки

1. Active creator видит только submitted result своих member-owned заданий;
   foreign, inactive, community-task creator с назначенным другим reviewer и
   actor вне test-run scope не получают literal result или private fields ни в
   list, ни по прямому detail URL.
2. Literal free-form result видим без raw payload/private fields; template/
   unsupported result fail closed.
3. `FULL / PARTIAL / REJECT` проходят только через canonical application
   workflow; authoritative projection исключает `PARTIAL` при reward `1` и
   включает при reward `>=2` через существующий `partial_reward`; UI не
   вычисляет eligibility, итоговый status или reward.
4. `REJECT` даёт `rejected_pending_dispute`, exact 24h deadline и нулевые
   payout/refund; same key + same decision replay exact, same key + different
   decision — deterministic conflict. Конкурентный loser не создаёт duplicate
   ledger/reliability/receipt/outbox effects, а новый audit event не вводится.
5. После mutation UI перечитывает authoritative state; повтор, ошибка и back/
   focus не запускают скрытый второй effect.
6. Targeted PostgreSQL/API test и один browser journey green; обязательный
   независимый final review — `Status: approved`.
7. PR/CI/merge, exact release, production activation и public smoke завершены
   до финального Jira transition.

## Planned checks

После implementation diff и до final review выполнить один раз в порядке
стоимости:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check src tests ops
uv run pytest -q tests/integration/test_assignments.py tests/integration/test_web_api.py --cov=community_bot.application.assignments --cov=community_bot.infrastructure.db.assignments --cov=community_bot.transport.web --cov-report=term-missing --cov-fail-under=0
uv run pytest --no-cov -q tests/browser/test_mini_app.py
git diff --check origin/main
```

Targeted coverage gate фиксирует покрытие добавленных runtime lines/branches в
implementation report; `--cov-fail-under=0` отключает только нерелевантный
глобальный package threshold. После approved final review — PR CI, затем после
merge green main CI и delivery/smoke по ADR-0019. Secret-like scan выполняется
по exact planned diff до commit без вывода потенциальных значений.
