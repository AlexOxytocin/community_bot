# Release 2 — Mini App-only направление

**Статус:** принято владельцем
**Каноническое решение:** [ADR-0016](../adr/0016-mini-app-only-runtime.md)
**Эпик:** `CB-48`

## Результат

Release 2 заменяет старый Telegram chat UI новым Mini App/web UI поверх существующего backend. Параллельного fallback-бота и обязательного паритета с его меню нет.

Сохраняются:

- domain/application use cases и PostgreSQL UoW;
- ledger кредитов и опыта, audit и idempotency receipts;
- transactional outbox, worker и дедлайны;
- роли, статусы, permissions и ownership;
- каталог, задания, назначения, споры, карма и надёжность;
- неизменяемая история Alembic и защита test-run данных.

Telegram остаётся только для запуска Mini App, auth proof/deep link и коротких исходящих уведомлений без callback UI.

## Очередность

1. `CB-62` — очистка старого UI/runtime и фиксация границы.
2. `CB-51` — завершённая Pareto-cleanup backend без schema consolidation.
3. `CB-52` — минимальная web foundation: Telegram proof, короткая server
   session, internal `ActorContext` и пять read projections. Первый domain
   write и его operation identity добавляются в `CB-53` вместе с реальным UI
   consumer.
4. `CB-53` — frontend shell, routing и platform bridge.
5. `CB-54`—`CB-55` — продуктовые экраны и административные сценарии.
6. `CB-56` — новый HTTPS/deployment/observability контур.
7. `CB-57` — browser, integration и live Mini App acceptance.

## Обязательные свойства

- backend остаётся единственным источником бизнес-состояния;
- frontend не вычисляет права и допустимые переходы;
- auth proof проверяется server-side;
- mutation replay/conflict детерминирован;
- state, ledger, audit и outbox не расходятся;
- прямой URL не обходит authorization или rollout gate;
- новый deployment не объявляется готовым без PostgreSQL, migration и restore доказательств.
