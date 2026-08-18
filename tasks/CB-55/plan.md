# CB-55 — план первого admin/moderation slice

## Решение

CB-55 в нынешнем виде не нужен: «весь административный UI» объединяет несколько
редких, чувствительных и транзакционно разных продуктов. Реализация исходной
широкой области запрещена.

Рекомендуемый первый slice после снятия gates — только read-only очередь
открытых и обжалованных moderation cases:

`Mini App -> Модерация -> открытые/обжалованные кейсы -> Назад`.

Пользовательская ценность: active moderator или administrator видит, что требует
внимания после member task path. Решение кейса, приватные материалы и любая
mutation остаются вне slice.

## Почему не реализовывать CB-55 целиком

| Кандидат | Ценность | Частота | Reuse | Риск | Решение |
|---|---:|---:|---:|---:|---|
| Read-only очередь moderation cases | 4 | 3 | 5 | 2 | Первый будущий slice |
| Registration approve/reject | 5 | 4 | 3 | 4 | Отложить: grant, audit, outbox, idempotency |
| Dispute resolution | 4 | 2 | 3 | 5 | Отложить: ledger, reliability, conflict, preview/confirm |
| Community publication/reviewer replacement | 3 | 1 | 3 | 5 | Отложить: superadmin и независимость reviewer |
| Interaction alert review | 3 | 1 | 3 | 5 | Отложить: private notes и penalty |
| Product config activation | 3 | 1 | 4 | 5 | Отложить: глобальный immutable pointer/backfill |

Шкала `1..5`; большее `Reuse` лучше, больший `Риск` хуже. Полный defer был бы
проще, но очередь оправдана после CB-54: backend уже сохраняет disputes и
appeals, а отсутствие видимости оставляет staff без наблюдаемого входа. Любая
mutation требует отдельного slice и собственного review.

## Предусловия реализации и их состояние

1. Закрыто: CB-54 merged в `main` через PR #67, merge commit
   `64b2cd667c28e56d7f8f2df2a70b09f1e05278f8`; Jira `Готово`, CI green.
2. Закрыто: merged `web.py`, static shell и tests повторно сверены.
3. Закрыто: владелец/Оркестратор одобрил именно read-only очередь и разрешил
   Jira update, ветку и runtime.
4. Закрыто: `task/CB-55` создана от точного `origin/main` commit
   `64b2cd667c28e56d7f8f2df2a70b09f1e05278f8`.

CB-64 compact-db import/reconciliation не является precondition: slice читает
текущий authoritative moderation store, не меняет schema/data и не выполняет
import/cutover. Import gates продолжают действовать для будущей compact-db
миграции и deployment; это отдельная причинная граница, а не отмена data-safety.

## Точная область

### Application reuse

- Сохранить owner `ModerationService`; route не вызывает DB adapter напрямую.
- Заменить только read-сигнатуру `ModerationService.queue` на web-neutral
  `queue(actor: ActorContext, *, limit: int = 20)`.
- Добавить в существующий `ModerationUnitOfWork` protocol метод
  `get_member(member_id: UUID)`, который уже реализован существующим
  `SqlAlchemyUnitOfWork`; нового UoW/repository/service не создавать.
- Проверить active status и роль через существующее правило active staff.
- Расширить существующий `ModerationMutationPort.list_cases` параметром
  `include_fraud_review: bool`. `ModerationService` вычисляет этот boolean из
  актуальной роли actor; DB read при `false` добавляет
  `case_type != "fraud_review"` **до** `order_by(opened_at,id)` и `limit`.
  Так moderator получает первые `limit` строк своего разрешённого множества, а
  administrator — первые `limit` строк полной допустимой очереди. Новый
  permission layer или repository не создавать.
- Не выполнять `commit()`: GET не создаёт receipt, audit, outbox или иной effect.

### Exact API delta

Один endpoint:

```text
GET /api/v1/moderation/cases?limit=1..50
```

Ответ `200`:

```text
ModerationCasesDto {
  items: ModerationCaseDto[]
}

ModerationCaseDto {
  id: UUID
  assignment_id: UUID
  case_type: string
  status: "open" | "appealed"
  revision: int
  current_code: string | null
  opened_at: datetime
  resolved_at: datetime | null
}
```

- no session: `401 unauthorized`;
- registered actor без active moderator/administrator authority: единый
  `403 moderation_unavailable`;
- validation error: существующий `422 invalid_request`;
- response и ошибки: `Cache-Control: no-store`.

Не добавлять case detail endpoint, POST/PATCH/DELETE, operation identity,
preview/confirm или generic capabilities endpoint.

### Privacy, permissions и conflict boundary

- DTO является allowlist; запрещены `reason`, evidence/result payload,
  resolution effects, member contacts, private notes, raw karma, risk details,
  ledger, audit и outbox payload.
- Authorization выполняется в `ModerationService` по актуальному member из
  PostgreSQL, а не по client/session claims.
- Moderator видит только разрешённые ему `open|appealed` cases и не видит
  `fraud_review`; inactive staff и member получают одинаковый closed response.
- Прямой `#moderation` URL проходит тот же GET и не раскрывает данные до `200`.
- Conflict-of-interest не вычисляется в этом slice: нет detail и decision.
  Существующие conflict rules сохраняются и обязательны для будущей mutation.

### Один browser journey

После повторной сверки shell CB-54 добавить ровно один navigation entry
`Модерация`. Не строить dashboard или role/permission framework.

1. При открытии entry выполнить exact GET очереди.
2. Показать `loading`, затем список компактных case cards либо текст
   `Открытых кейсов нет`.
3. При `401/403` не показывать данные и вывести закрытое состояние без role
   details.
4. Кнопка `Назад` возвращает на предыдущий экран и восстанавливает focus.
5. Карточка не кликабельна: detail и decision отсутствуют намеренно.

Использовать существующие native HTML/CSS/ES modules и CSS tokens. Новые
компонентные abstractions и design-system expansion запрещены.

## План файлов

Точный список подтверждается после merge CB-54; ожидаемый максимум:

- `src/community_bot/application/moderation.py` — web-neutral read entry;
- `src/community_bot/infrastructure/db/moderation.py` — применить существующий
  `fraud_review` predicate до deterministic ordering/limit;
- `src/community_bot/transport/web.py` — DTO, `ModerationService`, один GET;
- `src/community_bot/transport/static/app.js` — один экран и back/focus flow;
- `src/community_bot/transport/static/index.html` и/или `styles.css` — только
  если merged shell не даёт существующего navigation/card primitive;
- `tests/integration/test_web_api.py` — один объединённый API scenario;
- `tests/browser/test_mini_app.py` — один browser journey;
- `tests/unit/test_web_auth.py` — только exact route-set/error contract, если он
  остаётся после CB-54.

Soft target: не более 6 runtime files и 3 test files, без line-golf. Если merged
CB-54 требует новый service/repository/table/dependency/framework либо generic
navigation platform, остановиться и вернуть owner decision вместо расширения.

## Минимальные exact tests

### API integration

Один parametrized scenario
`test_web_moderation_cases_authorizes_filters_and_projects_safe_queue`:

- seed самый ранний по `opened_at,id` `open fraud_review`, следующим
  `open moderator-visible`, затем `appealed` и `resolved`;
- при `limit=1` active moderator получает следующий moderator-visible dispute,
  а не пустой список; `fraud_review` и `resolved` отсутствуют;
- при `limit=1` active administrator получает самый ранний `fraud_review`;
- для обеих ролей порядок внутри разрешённого множества точно равен
  `opened_at,id`;
- member, paused/restricted moderator: `403 moderation_unavailable`;
- без session: `401 unauthorized`;
- `limit=1` детерминированно выбирает первый по `opened_at,id`, `0|51` дают
  `422 invalid_request`;
- JSON keys совпадают с allowlist; сериализованный ответ не содержит reason,
  evidence, private notes, raw karma, Telegram identity, ledger/audit/outbox;
- до/после GET равны counts/checksums state, operations, ledger, audit и outbox.

### Browser

Один Playwright scenario
`test_moderation_queue_loading_empty_closed_and_back_focus` на уже установленной
зависимости:

- route mock отдаёт safe cases и проверяет literal rendering без HTML injection;
- переход `Модерация -> список -> Назад` восстанавливает focus;
- повторные варианты ответа покрывают loading, empty, `401/403` и network error;
- DOM не содержит запрещённых полей и не создаёт mutation request.

### Узкий contract check

Если route-set test сохранён после CB-54, добавить только новый GET и проверить
`no-store`/closed error shape. Существующие moderation domain/integration tests
не копировать: они продолжают защищать dispute, sanctions, alerts и conflicts.

## Stop, rollback и доказательство завершения

Stop при любом из условий:

- точный `origin/main` не содержит merge CB-54 `64b2cd6`;
- merged layout расходится с одним GET/read-only scope;
- owner approval narrowed scope отозван или изменён;
- safe projection требует нового доменного правила или таблицы;
- frontend должен вычислять role/permission;
- для GET внезапно нужен receipt, audit или mutation;
- privacy allowlist либо moderator filter не доказаны exact integration test.

Rollback будущего slice удаляет один route/DTO/screen и web-neutral read glue.
Schema, data, ledger, operations, audit и outbox не меняются, поэтому data
rollback отсутствует.

Доказательство реализации: green targeted API + browser + route contract checks,
zero schema/dependency diff и один green контрольный non-browser suite. Перед
delivery остаётся независимый level-3 final review. Deployment/live acceptance
остаются CB-56/CB-57.

## Точно отложенная область

Backend engine не удаляется и не ослабляется. UI consumer откладывается для:

- invitation create/revoke и application approve/reject/resubmit;
- member roles/status/permissions;
- categories/templates и versioned config ingest/activate/backfill;
- community task draft/publication/reviewer replacement/review;
- case detail, evidence, resolution preview/confirm и durable drafts;
- appeals/reversals;
- warnings/restrictions/suspensions/bans/revoke;
- raw karma review/history и audit-on-read;
- risk signals, interaction alerts/outcomes/private notes/penalties;
- immutable audit views;
- любые conflict-of-interest decisions;
- generic admin dashboard, analytics, schema renderer, permission framework,
  workflow engine и design-system expansion.

Каждый будущий mutation slice обязан повторно использовать соответствующий
CB-64 owner/UoW и иметь собственные operation identity, privacy/conflict exact
cases и owner approval.

## Ponytail simplicity audit

`shrink:` заменить «весь admin UI» одним существующим read-owner и одним GET;
не добавлять mutation, platform или dependency. Возможный net-addition мал и
обратим; весь backend roadmap остаётся нетронутым.

## Owner decisions и блокеры

Оба решения приняты: read-only moderation queue нужен, Jira/runtime/ветка
разрешены. Ложная import dependency снята только для этого slice по причинной
границе выше. Реальных implementation blockers на повторном снимке нет.
