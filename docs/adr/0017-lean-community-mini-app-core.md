# ADR-0017 — Компактный движок Community Mini App с полным parity

**Статус:** Принято

**Дата:** 2026-08-17

**Принято владельцем:** 2026-08-17

## Контекст

Текущий `main` содержит 20 029 строк production Python, 14 268 строк тестов,
43 таблицы и 10 direct runtime dependencies. Runtime web UI ещё не существует.
Масштаб пилота — 20–30 приглашённых участников, поэтому стоимость реализации
несоразмерна продукту.

При этом размер нельзя сокращать удалением домена. Текущий движок уже задаёт
нужный продукт: профили и роли, member/group/community tasks, templates,
settlement, credits/experience/levels, karma/reliability/leaderboard,
disputes/appeals/sanctions, interaction alerts, versioned config,
notifications, audit и idempotency. Все эти возможности сохраняются.

Проблема не в ширине функций, а в том, что одно правило разнесено между
protocol, service, domain object, UoW method, DB adapter, отдельной таблицей и
несколькими повторяющимися тестами. Добавление web UI поверх этой формы
закрепит её стоимость.

## Решение

1. Сохранить полный функциональный parity существующего backend. Метрики кода,
   таблиц и тестов не являются основанием удалить или ослабить функцию.
2. Удалить старый Telegram chat UI, callbacks, long polling и conversation FSM.
   Единственный пользовательский UI — Telegram Mini App; Bot API остаётся для
   уведомлений и deep links.
3. Перестроить backend в небольшой feature-oriented Python monolith. SQLAlchemy
   `AsyncSession` является транзакционной границей; protocols/repositories/UoW
   с одной реализацией не создаются.
4. Консолидировать 43 таблицы в целевые 11–12: members, invitations, sessions,
   product config versions, tasks, assignments, account transactions,
   reputation events, moderation cases, operations и outbox events. Финальный
   DDL принимается только после полного parity/import spike.
5. Typed JSON хранит редкие версии payload внутри config/reputation/moderation
   stores. State, actor, subject, timestamps, business keys и query-critical
   поля остаются обычными constrained/indexed колонками. Payload discriminator
   и version обязательны и валидируются Pydantic. Исторические динамические
   schemas шаблонов продолжают исполняться `Draft202012Validator`; Pydantic не
   заменяет JSON Schema.
6. Деньги, state transition, audit, operation receipt и outbox intent
   коммитятся одной транзакцией. PostgreSQL остаётся единственным stateful
   сервисом.
7. Notifications, reminders, retries и finalizers сохраняются. Один компактный
   background loop читает PostgreSQL outbox; broker и отдельный queue framework
   не вводятся.
8. FastAPI обслуживает API и static Mini App. Frontend использует native
   HTML/CSS/ES modules без React/Vite/Node, пока browser gates не докажут
   необходимость framework.
9. Direct dependencies ограничиваются реально используемыми пакетами. Пакет
   `jsonschema` сохраняется ради точного контракта шаблонов. Telegram
   signature, Bot API HTTP, logging и environment parsing используют stdlib.
10. 297 test functions заменяются 50–65 scenario/invariant tests. Удаляется
    global coverage percentage; обязательными становятся полный
    machine-checkable mapping `old capability/invariant → new owner → scenario
    node ID`, exact cases и targeted coverage изменённых runtime-модулей.
11. Актуальная документация после migration консолидируется в шесть living
    Markdown documents. Git history хранит заменённые подробности. До принятия
    этого ADR действующее правило о сохранении accepted ADR не меняется.
12. Shared/production database сначала проходит read-only inventory, encrypted
    backup и isolated restore. Новая compact schema создаётся отдельно, весь
    бизнес-функционал и история импортируются с проверкой инвариантов. Старая БД
    не удаляется этим refactor. До первой реальной mutation возможен rollback
    на legacy image/database; после неё rollback использует только предыдущий
    compatible compact image с той же compact DB, чтобы не потерять новые
    ledger/state/audit/outbox effects.

## Неприкосновенные инварианты

- registration/invitation/role/status permissions и audit сохраняются;
- member/group/community task lifecycle, slots, publication/reviewer rules,
  cancellation, result versions, deadlines и finalization сохраняются;
- credit/experience ledger остаётся append-only и атомарным, settlement — один
  на slot, idempotency — exact replay;
- levels, karma/history/privacy, reliability/corrections и leaderboard
  сохраняются;
- disputes/evidence/resolutions/appeals/reversals, sanctions/risk signals и
  interaction alerts/penalties сохраняются;
- versioned config activation, notifications/reminders/retries и restart
  recovery сохраняются.
- durable task/submission/moderation drafts сохраняют ownership, revision,
  restart/resume и exact-confirm semantics; исчезает только Telegram FSM cursor.

Инвентаризация CB-64 классифицировала все 43 legacy tables и зафиксировала
new owner, DB constraint, transformation, exact planned scenario и oracle.
Строка без passing exact case блокирует удаление соответствующего старого кода.

## Рассмотренные альтернативы

### Добавить web UI поверх текущего backend

Отклонено: сохраняет 43-table/297-test стоимость и добавляет новый transport,
не устраняя дублирующие слои.

### Удалить расширенные функции ради простого пилота

Отклонено решением владельца: весь функциональный движок должен сохраниться.
Простота достигается формой реализации, а не урезанием продукта.

### Оставить функции выключенными flags и переписать позже

Отклонено: создаёт две реализации и временный compatibility layer без даты
удаления. Каждый slice переносится один раз и старый код удаляется только после
parity gate.

### Сохранить React/Vite из ADR-0014

Отклонено для первого Mini App: текущий масштаб не доказывает пользу Node build
и dependency tree. Решение пересматривается только по измеримой сложности UI.

### Best-effort уведомления без outbox

Отклонено: reminders и значимые notifications являются частью движка. Один
небольшой PostgreSQL outbox дешевле, чем потеря событий или отдельная очередь.

### Немедленно переписать существующую database in place

Отклонено: historical production deployments не позволяют предполагать, что
данных нет. Separate database, verified import и rollback обязательны.

## Последствия

Положительные:

- полный продуктовый движок остаётся доступен через новый web UI;
- один feature обычно читается в одном модуле и одной транзакции;
- уменьшаются schema, layers, dependencies, test count, CI noise и docs;
- каждый шаг проверяется parity scenario до удаления старой реализации;
- старый Telegram UI не диктует архитектуру Mini App.

Ограничения:

- compact typed event stores требуют строгих payload versions и индексов;
- data migration сложнее clean start и блокирует cutover при расхождении;
- один process/background loop подходит пилоту, но требует restart/retry probe;
- ceiling может быть пересмотрен вверх, если иначе нарушается parity;
- отказ от frontend framework пересматривается при доказанной сложности, не
  заранее.

После принятия ADR заменяет применимость частей ADR-0005, ADR-0014 и ADR-0016,
которые требуют прежние layered abstractions, React/Vite или current backend
shape. Решение Mini App-only, PostgreSQL, безопасность, data durability и весь
доменный контракт сохраняются.

## Связанные материалы

- [ADR-0016 — Mini App как единственный UI](0016-mini-app-only-runtime.md)
