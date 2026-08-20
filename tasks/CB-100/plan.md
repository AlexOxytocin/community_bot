# CB-100 — план уровня 2

## Подтверждённая причина

`TaskService.web_state` уже возвращает только текущий разрешённый free-form
черновик владельца, его точную revision/values и признак `needs_edit`. Stale
preview не теряется на backend. Тупик создаёт frontend-цепочка T04 → T04A →
T05: она смешивает выбор типа, несуществующий template entry и recovery, а
`needs_edit` показывает как error-state без явного безопасного выхода.

Текущий web `start` возобновляет current draft. Нужная атомарная смена current
уже принадлежит существующему repository owner `create_task_draft` и выполняется
под task identity gate; web-контракту не хватает только явной команды для этого
существующего пути.

## Минимальная реализация Ponytail full

1. Удалить production renderers/callers/copy T04 и T04A. Выбор `solo/group`
   оставить только в существующем editor.
2. На `+ Создать` выполнить existing GET без mutation. При `draft=null`
   показать blank editor; первый submit один раз вызывает existing start,
   получает server draft и сохраняет форму.
3. При current draft показать компактный recovery: valid — «Продолжить»;
   stale preview — «Редактировать черновик»; оба состояния дают «Создать новое».
4. Добавить одной веткой существующего `POST /api/v1/task-creation` action
   `start_new`. Она вызывает тот же `TaskService.start`, привязывает замену к
   видимым `draft_id/revision` и сохраняет identity gate, receipt replay, test
   scope и repository transaction.
5. Не добавлять endpoint, model, table, migration, repository, dependency,
   framework, template API или client store.

## Connected-state delta

| Источник | Условие | Цель | Mutation |
|---|---|---|---|
| T01 `+ Создать` | `draft=null` | T05 blank editor | 0 |
| T01 `+ Создать` | current valid draft | T04B recovery | 0 |
| T01 `+ Создать` | `needs_edit=true` | T04B stale recovery | 0 |
| T04B continue/edit | server draft | T05/T06 | 0 |
| T04B create new | owner current draft | T05 new draft | one idempotent `start_new` |
| T05 first submit | no draft at entry | T06 | one `start`, then one `save` |

T04 и T04A удаляются из reachable production graph. Backend template
capability остаётся без изменений.

## Проверка

- browser: zero draft без POST до submit; current/stale recovery; exact values и
  revision; edit deadline → preview; create-new/retry; Back/reload и отсутствие
  T04/T04A/template strings;
- API/integration: `start_new` создаёт один новый current, supersedes previous,
  exact replay не дублирует, foreign/test-run/revision остаются fail-closed;
- Ruff format/lint, `ty`, node syntax, targeted и основной regression gate;
- независимый `final-review.md`, PR/CI/merge и ADR-0019 production delivery.

## Риски

- Blank editor до server draft не может отправить save напрямую: submit сначала
  завершает existing idempotent start и использует только возвращённые id/revision.
- Back после recovery должен восстанавливать server state, а не хранить копию
  authoritative draft в history.
