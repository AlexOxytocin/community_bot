# Release 2 — capability-контракт интерфейсной платформы

**Статус:** Зафиксировано

**Дата:** 2026-08-16

**Каноническое решение:** [ADR-0014](../adr/0014-multi-interface-release-2.md)

**Jira:** эпик `CB-48`, архитектурная задача `CB-49`.

## CAPABILITY

Активный участник закрытого сообщества получает полный визуальный Telegram
Mini App для действующих сценариев Community Bot: просмотр профиля и экономики,
поиск, создание и выполнение заданий, проверка результата, карма, споры и
доступные роли администрирования. Telegram-бот сохраняется как канал
регистрации, входа, уведомлений, deep link и резервный интерфейс. Все
интерфейсы вызывают одни application services, используют одну доменную модель
и одну PostgreSQL.

Release 2 создаёт интерфейсно-независимую границу, к которой позднее можно
подключить полноценный браузерный режим без второго backend и без копирования
правил. Browser UI в Release 2 не выпускается.

## CONSTRAINTS

### Зафиксированная продуктовая политика

- Release 2 сохраняет правила Release 1: роли, состояния, кредиты, опыт, уровни,
  карму, модерацию, аудит и правила заданий не меняет сам новый интерфейс.
- Источник истины — PostgreSQL, domain и application services. Frontend не
  вычисляет баланс, права, допустимые переходы или итог операции.
- Публичная регистрация не появляется. Первичный `/start`, приглашение,
  принятие правил и незавершённая анкета остаются bot-only до отдельного
  продуктового решения.
- Bot fallback сохраняется как минимум до подтверждённого rollout R2.
- Пилот Release 1 продолжается параллельно. До его данных запрещены новая
  экономика, монетизация, публичная регистрация и новые направления платформы.

### Архитектурные инварианты

- Один модульный монолит, одна PostgreSQL и одна система миграций.
- Inbound transports: существующий `transport/telegram` и новый versioned HTTPS
  API на FastAPI.
- `domain` и `application` не зависят от aiogram, FastAPI, React, Telegram
  WebApp SDK и ORM-моделей.
- Bot, API, worker и frontend assets входят в согласованный immutable release.
- Миграции последующих задач только expand-only и совместимы с частичным
  rollback предыдущего image.
- `main` остаётся выпускаемым; незавершённые R2 surfaces скрыты server-side
  fail-closed feature flags.

### Trust boundaries

- Telegram Mini App передаёт серверу исходный `initData`; `initDataUnsafe` не
  является доверенным источником.
- `TelegramMiniAppAuthAdapter` проверяет подпись, допустимый возраст и поля
  proof до выдачи внутренней сессии.
- Subject `ActorContext` — внутренний `member_id`. Provider, session identity и
  время authentication используются только как metadata для аудита и политики
  свежести.
- Role, member status, permissions и ownership не доверяются клиенту или
  session claims. Каждый защищённый use case читает их актуальное состояние из
  PostgreSQL.
- Mini App proof связывается только с существующим member. Будущий browser auth
  adapter обязан получить тот же internal subject и не создаёт публичную
  регистрацию автоматически.
- `start_param`, query string и прямой URL являются недоверенными navigation
  hints. API повторно проверяет идентификатор, видимость, роль и ownership.

### Идемпотентность

Изменяющая команда имеет operation identity:

```text
transport_namespace
actor_id
external_key
command_name
canonical_payload_fingerprint
```

Receipt уникален в scope
`(transport_namespace, actor_id, external_key)` и хранит command, fingerprint,
outcome и время обработки.

- exact replay возвращает прежний outcome без нового эффекта;
- тот же scoped key с другим command или payload возвращает conflict;
- receipt, domain state, ledger, audit и outbox коммитятся одной транзакцией;
- Telegram `update_id` и HTTP idempotency key имеют разные namespaces;
- cross-transport гонки дополнительно останавливают state transitions, unique
  constraints и locks доменной модели.

### Rollout и восстановление

- Release 1 фиксируется только после acceptance: tag `v1.0.0`, GitHub Release,
  commit SHA, immutable image digest и Alembic revision.
- Постоянная `release/1.x` не создаётся до реальной необходимости независимых
  patch-релизов.
- Отсутствующая, повреждённая или недоступная feature-flag configuration означает
  `disabled`. Прямой API/URL не обходит gate.
- PostgreSQL не публикуется наружу. Public HTTPS edge, TLS, DNS и topology
  принимаются отдельно в CB-56.
- Bot fallback и выключение R2 flag являются первым способом отката интерфейса;
  schema downgrade автоматически не выполняется.

## IMPLEMENTATION CONTRACT

### Actors

| Actor | Что получает в R2 | Ограничение |
|---|---|---|
| Приглашённый кандидат | Регистрация через существующий bot flow | Mini App session до появления member не выдаётся |
| Активный участник | Основной Mini App и bot fallback | Только собственные и разрешённые общие данные |
| Автор задания | Создание, публикация, проверка и отмена | Права и резерв проверяет сервер |
| Исполнитель | Принятие, версии результата, спор и согласие на отмену | Переходы проверяет сервер |
| Модератор | Разрешённые модерационные сценарии | Нет owner/admin полномочий и raw karma |
| Администратор | Регистрации, каталоги и административные представления | Нет `superadministrator`, если право не выдано |
| Суперадминистратор | Владелец административной области | Значимые операции подтверждаются и аудируются |
| Оператор | Deploy, health, rollout и rollback | Не правит доменное состояние ручным SQL |

### Surfaces

#### Telegram-бот

- `/start`, приглашение, правила и первичная регистрация;
- уведомления и deep links на конкретный экран Mini App;
- fallback для пользовательских и административных операций;
- Telegram-native ввод, когда он осознанно удобнее web-формы.

#### Telegram Mini App

- профиль, баланс, статистика, каталоги и история;
- транзакционный жизненный цикл заданий;
- карма, споры и доступные административные экраны;
- mobile-first интерфейс с Telegram theme, safe area и native controls через
  `PlatformBridge`.

#### Browser mode

- в R2 запускает тот же frontend только в безопасном unauthenticated режиме;
- не получает данные и не выполняет изменения без принятого browser auth;
- позднее подключается через отдельный auth adapter и существующий API.

### `ActorContext`

Минимальная семантика:

```text
member_id
auth_provider
session_id
authenticated_at
```

`role`, `status`, `permissions` и `ownership` не входят в доверенную часть
контекста. Application service разрешает их заново внутри защищённого use case.
Формат cookie/token, lifetime, CSRF и revocation определяет CB-52, не ослабляя
этот контракт.

### HTTP interface

- базовая versioned boundary: `/api/v1`;
- входы и ответы имеют явные Pydantic/OpenAPI schemas;
- изменяющий запрос содержит HTTP idempotency key;
- authorization и feature gate проверяются до use case;
- сервер внутренне различает invalid proof, expired session, forbidden,
  not-found, state conflict, idempotency conflict и retryable failure для
  безопасной наблюдаемости;
- во всех privacy-sensitive сценариях внешний ответ для скрытого,
  отсутствующего и недоступного ресурса одинаков и не подтверждает наличие
  записи; это распространяется на поддельный callback, прямой UUID и stale
  cursor независимо от внутренней причины отказа;
- приватные payload, `initData`, cookies и токены не попадают в логи.

Точные endpoints и representation выбираются contract-first в CB-52.

### `PlatformBridge`

Единственная frontend-граница Telegram WebApp SDK предоставляет:

- capability detection;
- theme и theme change events;
- viewport и safe-area updates;
- back и close behavior;
- haptics;
- Telegram links;
- недоверенный start parameter.

Операции возвращают явный результат `supported|unsupported`, если no-op может
создать ложное подтверждение. Bridge не хранит business state, не авторизует
пользователя и не объявляет server operation успешной.

### Frontend и дизайн

- один React + TypeScript + Vite SPA;
- router поддерживает прямые URL без зависимости от истории Telegram chat;
- Telegram и browser adapters используют одни feature modules и semantic
  design tokens;
- mobile-first не означает mobile-only: layout предусматривает будущий desktop;
- дизайн-направление и доступные light/dark tokens фиксируются в CB-58 до CB-53;
- референс владельца задаёт dark neon язык, но не landing-page композицию.

### States и transitions

R2 не вводит новых доменных состояний. UI отображает и вызывает переходы из
канонических MVP-документов. При stale state API возвращает актуальный conflict,
frontend обновляет объект и не имитирует успех.

Полное сопоставление находится в [parity-матрице](PARITY_MATRIX.md).

### Data implications

Последующие задачи могут добавить:

- внутренние sessions и auth audit metadata;
- HTTP operation receipts;
- server-side feature flags/cohort assignments;
- versioned API schemas.

Новые таблицы не заменяют member, task, assignment, ledger, audit и outbox.
Точная schema принадлежит CB-51, CB-52 и CB-56.

### Observability и операторский контракт

- bot, worker и API публикуют release-matched heartbeat/readiness;
- метрики различают transport, command family, outcome и latency без identity и
  приватного payload;
- security events фиксируют invalid/expired proof, forbidden, idempotency
  conflict и rate limiting без сохранения секретного входа;
- rollout можно отключить feature flag без ручного SQL;
- release acceptance включает API, браузерный E2E и живой Telegram Mini App.

### Definition of parity

Для одного исходного доменного состояния и одной разрешённой команды bot и API
должны давать одинаковые:

- доменный transition;
- ledger entries;
- audit facts;
- outbox effects;
- authorization result;
- idempotency result.

Текст и композиция ответа могут различаться между интерфейсами.

## NON-GOALS

- новая экономика, уровни, роли, карма или состояния;
- платежи и подписки;
- публичная регистрация;
- новые направления и сервисы платформы;
- выпуск authenticated browser UI;
- отдельный browser backend или копия frontend business logic;
- микросервисы, Redis, Celery, Kubernetes или LLM в доменных решениях;
- webhook для Telegram-бота без отдельной измеримой причины;
- application object storage и новая политика доказательств выполнения;
- финальная дизайн-система внутри CB-49.

## OPEN QUESTIONS

Они не блокируют начало следующей задачи, но блокируют соответствующий этап:

| Вопрос | Jira-владелец | Блокирует |
|---|---|---|
| Session representation, lifetime, CSRF и revocation | CB-52 | выдачу production session |
| Production domain, TLS terminator и edge topology | CB-56 | public HTTPS rollout |
| Feature-flag storage и cohort management | CB-56 | ограниченное включение R2 |
| Browser auth provider | будущая задача | authenticated browser mode |
| Light/dark tokens, typography и component preview | CB-58 | полноценную работу CB-53 |
| Необходимость `release/1.x` | отдельное решение при patch lifecycle | независимую поддержку R1 |
| Webhook для бота | отдельная измеримая причина | только смену bot transport |

## HANDOFF

Capability готов к реализации по отдельным задачам эпика CB-48:

1. CB-50 фиксирует Release 1.
2. CB-51 создаёт transport-neutral actor и operation boundary.
3. CB-52 добавляет API и Telegram Mini App auth.
4. CB-58 фиксирует дизайн-систему до frontend shell.
5. CB-53 реализует shell и read-only surfaces.
6. CB-54 и CB-55 добавляют пользовательские и административные mutations.
7. CB-56 готовит HTTPS runtime и rollout.
8. CB-57 подтверждает parity и выпускает `v2.0.0`.

Планировочная цена browser readiness сейчас — `10–15%` foundation R2.
Authenticated browser mode с той же функциональностью позднее оценивается в
`20–35%` поверх Mini App. Это не оценка публичного продукта с SEO, платежами,
публичной регистрацией или multi-community.
