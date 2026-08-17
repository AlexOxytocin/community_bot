# CB-64 — исходный контекст плана

## Снимок `main`

- Commit: `019850ce05e5e98c23c566dc491fee473892b33f`.
- Production Python: 58 файлов, 20 029 строк.
- Tests: 49 файлов, 14 268 строк, 297 test functions.
- Migrations: 20 revisions, 3 540 строк, 43 SQLAlchemy tables.
- Documentation: `docs/` — 41 файл и 5 936 строк; `agents/` — 1 707 строк;
  `tasks/` — 1 097 строк.
- Прямых runtime dependencies: 10.
- Runtime frontend отсутствует; в `main` есть только дизайн-артефакты CB-58.
- GitHub API показывает 17 historical deployments в environment `production`;
  предыдущий deployment завершался успешно. Наличие и ценность строк БД этим
  не доказаны, но считать shared database заведомо пустой нельзя.

## Неприкосновенный функциональный контракт

Источники контракта: Jira CB-64, `docs/mvp/01_PRODUCT_REQUIREMENTS.md`,
`docs/mvp/02_DOMAIN_RULES.md`, `docs/mvp/04_TASK_CATALOG.md`,
`docs/mvp/06_DATA_MODEL.md` и `docs/mvp/08_MODERATION_AND_ABUSE.md`.

Сохраняются все возможности бизнес-движка:

- приглашение, заявка на регистрацию, ручное решение и статусы участника;
- профиль, роли, права и видимость карточек;
- категории и шаблоны;
- обычные, групповые и community tasks, слоты и независимый reviewer;
- создание, публикация, принятие, отказ, отмена, версии результата, полное и
  частичное принятие, отклонение, сроки и автоматическое завершение;
- кредитный и опытный ledger, резерв, возврат, выплата и корректировки;
- уровни, карма, история кармы, надёжность и лидерборд;
- споры, доказательства, решения, апелляции и reversals;
- предупреждения, ограничения, suspension, ban и история санкций;
- risk signals, interaction alerts, review outcome и штрафы;
- неизменяемые версии продуктовой конфигурации и атомарная активация;
- уведомления, напоминания, retry, audit и идемпотентность.

Старый Telegram chat UI, callback navigation, conversation FSM и long polling
не относятся к сохраняемому бизнес-функционалу: их заменяет Telegram Mini App.
Production test-run entities являются эксплуатационной оснасткой, а не
продуктовым движком; их можно убрать только после inventory и безопасного
архивирования данных.

## Проверенные признаки лишней сложности

- `SqlAlchemyUnitOfWork`: 1 260 строк и 144 метода.
- `TaskService`: 1 158 строк и 24 метода; `TaskUnitOfWork`: 56 методов.
- `AssignmentService`: 837 строк; `AssignmentUnitOfWork`: 47 методов.
- `PostgresNotificationQueue`: 618 строк.
- 43 таблицы во многом повторяют один и тот же паттерн: typed state/history,
  отдельный adapter и отдельный UoW-метод для каждого небольшого события.
- Архитектурные тесты проходят 17/17, но обычный целевой запуск возвращает
  ошибку из-за глобального runtime coverage `80%`, хотя runtime не импортирован.

## Ponytail-аудит: что именно сокращается

1. `shrink:` moderation, disputes, appeals, sanctions, risk signals и
   interaction alerts остаются поведением, но используют один типизированный
   case/event store вместо россыпи однотипных таблиц и adapters.
2. `shrink:` karma, reliability, levels и leaderboard сохраняются. Карма и
   надёжность читаются из компактного append-only event store, уровни — из
   активной версии конфигурации, leaderboard — запросом, а не отдельным слоем.
3. `delete:` production test-run runtime, conversation FSM и Telegram update
   receipts после подтверждения, что это transport/operations scaffolding, а
   не бизнес-история. HTTP mutations получают общий operation receipt.
4. `shrink:` схема из 43 таблиц до целевых 11–12 без потери истории, денег,
   сроков, слотов, moderation и config semantics.
5. `yagni:` UnitOfWork/repository protocols с одной реализацией. Транзакционная
   граница — SQLAlchemy `AsyncSession` и небольшие feature functions.
6. `shrink:` `tasks` и `assignments` сохраняют весь lifecycle, group/community
   semantics и версии результатов, но без параллельных service/domain/adapter
   state machines.
7. `shrink:` categories, templates, levels и thresholds живут в одной
   неизменяемой versioned product config; Pydantic проверяет typed config, а
   `jsonschema` сохраняет точную Draft 2020-12 validation шаблонов.
8. `shrink:` уведомления, reminders и finalizers остаются, но один компактный
   PostgreSQL outbox заменяет разросшиеся queue/worker abstractions.
9. `native:` aiogram, structlog, Sentry и pydantic-settings удаляются после
   исчезновения их реальных use cases; остаются stdlib logging/env/HTTP и
   небольшая web/API граница.
10. `shrink:` 297 тестов заменяются 53–68 сценарными и инвариантными тестами;
    историческая документация консолидируется в шесть living documents после
    принятия ADR. Функции защищает parity matrix, а не число test methods.

`net: -18,000–22,000 lines, -2 dependencies expected; a third only after
template-validation equivalence is proven.`

Это оценка удаления реализации, а не обязательство удалить функциональность.
Если доказанный parity не помещается в ceiling, метрика пересматривается до
изменения функции.

## Незавершённые ветки

- `task/CB-51`: commits поверх `main` отсутствуют; worktree содержит только
  незакоммиченные планы и изменения документации старой архитектуры.
- `task/CB-52`: commits поверх `main` отсутствуют; worktree содержит около
  61 КБ незакоммиченных плановых артефактов.
- Открытых GitHub PR нет.

Эти артефакты не являются реализацией и не задают новый контракт. После
принятия ADR их path/hash inventory сохраняется в CB-64, worktrees удаляются,
а CB-51 и CB-52 продолжаются от актуального `main` с новой областью. Сами
Mini App-задачи CB-51—CB-57 не удаляются: при полном parity каждая из них нужна.
