# ADR-0016 — Mini App как единственный пользовательский интерфейс

**Статус:** Принято

**Дата:** 2026-08-17

**Решение владельца:** полноценный Telegram-only бот и Release 1 pilot больше
не являются целевым продуктом; развитие ведётся только в направлении Mini App.

**Принято владельцем:** 2026-08-17 после terminal post-escalation review плана
CB-62 с `Status: approved`. Владелец явно ответил «да принимаю».

## Контекст

ADR-0014 вводил Mini App, но одновременно сохранял полный bot fallback и parity.
Это заставляет новые application contracts поддерживать rollback bridge,
двойные receipts, старые chat flows и отдельный release-процесс. Владелец снял
это требование: ценность находится в Mini App, а общее доменное ядро уже можно
переиспользовать без второго полноценного UI.

## Решение

Community Bot развивается как Mini App-first модульный монолит: FastAPI, SPA,
worker и одна PostgreSQL. Полноценный Telegram chat UI, long polling runtime и
R1 pilot/release topology удаляются. Telegram допускается только как proof
provider, launch/deep-link integration и канал коротких outbound уведомлений;
такой shell не реализует параллельные меню, FSM или business mutations.

Сохраняются domain/application, ledger, audit, outbox, migration history и
PostgreSQL. Telegram-shaped application signatures переводятся на internal
actor/operation contracts последующими задачами, а не защищаются новой
совместимостью со старым bot image.

Исторические test-run rows сохраняют fail-closed visibility/recipient
quarantine до отдельной data migration. PostgreSQL backup и isolated restore
drill остаются data-safety capabilities и адаптируются к transitional core
runtime, даже если bot-specific deploy/release automation удаляется.

## Альтернативы

### Поддерживать Mini App и полный bot одновременно

- Плюс: прежний UI остаётся доступен.
- Минус: двойные adapters, parity matrix, rollback bridge и постоянная цена
  тестирования.
- Отклонено: владелец явно отказался от старого продукта.

### Немедленно переписать всё ядро вместе с удалением UI

- Плюс: сразу исчезают Telegram-shaped signatures.
- Минус: большой неделимый migration diff смешивает удаление, auth/API и все
  продуктовые use cases.
- Отклонено: CB-51–CB-55 дают проверяемые вертикальные срезы.

### Оставить legacy код выключенным feature flag

- Плюс: быстрый формальный rollback.
- Минус: код, зависимости, security surface и тесты продолжают жить и влиять
  на решения.
- Отклонено: Git уже является достаточной историей удалённой реализации.

## Последствия

### Положительные

- один пользовательский интерфейс и один набор acceptance-сценариев;
- CB-51 не строит dual-write/rollback bridge для снятого runtime;
- меньше production entrypoints, deployment scripts и Telegram attack surface;
- доменные правила и данные сохраняются для Mini App.

### Отрицательные

- после удаления UI и до CB-52/CB-53 репозиторий временно содержит только core,
  worker и design artifacts без пользовательского runtime;
- возврат полного bot UI потребует нового решения и новой реализации;
- production deployment заново определяется в CB-56.

### Риски и меры

- потеря общей логики: keep/delete inventory, domain/integration suite и
  независимый review;
- потеря исторических данных: migrations не переписываются и destructive
  schema changes запрещены;
- размытый Telegram shell: import allowlist ограничивает его auth/launch/
  outbound integration.

## Заменяемые решения

После принятия ADR заменяет bot fallback/parity и параллельный R1 pilot из
ADR-0014, а также текущую применимость R1 runtime/release частей ADR-0008,
ADR-0009, ADR-0011, ADR-0012 и ADR-0013. Эти ADR остаются в истории и не
удаляются.
