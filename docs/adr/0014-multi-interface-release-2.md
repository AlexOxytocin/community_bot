# ADR-0014 — Multi-interface архитектура Release 2

**Статус:** Частично заменено ADR-0016 в части bot fallback и parity

**Дата:** 2026-08-16

**Принято владельцем:** 2026-08-16 после независимого повторного ревью плана
CB-49 с `Status: approved`. Владелец явно принял точную редакцию ADR-0014.

## Контекст

Release 1 реализован как Telegram-бот в модульном Python-монолите. Домен,
application services, PostgreSQL, ledger, audit и outbox уже отделены от
aiogram импортами, но значительная часть application-контрактов принимает
`telegram_user_id` и `update_id`.

Владелец решил сделать Telegram Mini App основным визуальным интерфейсом
Release 2, сохранив существующую продуктовую логику. В будущем может появиться
полноценный браузерный интерфейс. Если связать API и frontend напрямую с
Telegram WebView, browser UI потребует повторной реализации authentication,
навигации и части application orchestration.

MVP сознательно не имел публичного HTTP ingress, FastAPI и web frontend.
Появление Mini App является подтверждённой причиной пересмотреть эту границу,
не переходя к микросервисам и не меняя доменную модель.

## Решение

1. **Сохранить один модульный монолит и одну PostgreSQL.** Telegram-бот,
   HTTPS API и worker являются процессами одной кодовой базы и вызывают общие
   application services. Новый интерфейс не получает собственные правила,
   ledger, audit или базу.
2. **Добавить versioned HTTP transport на FastAPI.** Плановая граница API —
   `/api/v1`. Конкретные endpoints и схемы фиксируются contract-first в CB-52.
   FastAPI не импортируется в `domain` и `application`.
3. **Ввести transport-neutral identity boundary.** Каждый transport сначала
   проверяет внешний proof и разрешает его во внутренний `ActorContext`.
   Subject контекста — внутренний `member_id`. Provider, session identity и
   время authentication допустимы только как metadata для аудита и политики
   свежести. Role, member status, permissions и ownership из клиента либо
   session claims не считаются актуальными: каждый защищённый application use
   case повторно загружает их из PostgreSQL. Application-команды не принимают
   Telegram `initData`, cookies или framework request.
4. **Разделить proof и session.** `TelegramMiniAppAuthAdapter` валидирует
   исходный `initData`, подпись, допустимый возраст и необходимые поля. После
   проверки session service выдаёт краткоживущую внутреннюю сессию только для
   существующего member. Будущий browser auth adapter обязан разрешить proof в
   тот же internal `member_id`, не меняя domain/application и не создавая
   автоматическую публичную регистрацию. Точный формат session, lifetime, CSRF
   и revocation выбираются в CB-52 после security review; этот выбор не может
   заменить свежую server-side authorization кэшированными permission claims.
5. **Обобщить идемпотентность на границе application.** Operation identity
   содержит стабильный `transport_namespace`, внутренний `actor_id`, внешний
   key, `command_name` и fingerprint канонически нормализованного payload.
   Receipt уникален в scope
   `(transport_namespace, actor_id, external_key)` и хранит command,
   fingerprint, детерминированный outcome и время обработки.
   Exact replay с теми же actor/command/fingerprint возвращает сохранённый
   outcome без нового эффекта. Тот же scoped key с другим command или
   fingerprint отклоняется как idempotency conflict. Receipt, domain state,
   ledger, audit и outbox фиксируются одной PostgreSQL-транзакцией. Telegram
   `update_id` использует namespace конкретного bot transport, HTTP key —
   отдельный API namespace и не имитирует числовой `update_id`.
   Cross-transport гонки не считаются одним receipt и дополнительно блокируются
   доменными state transitions, unique constraints и locks.
6. **Использовать React + TypeScript + Vite для frontend.** Это один SPA-код для
   Mini App и будущего browser mode. SSR и SEO не являются требованиями
   закрытого рабочего интерфейса.
7. **Изолировать платформу через `PlatformBridge`.** Только adapter может
   обращаться к Telegram WebApp SDK. Контракт предоставляет capability
   detection и нормализованные интерфейсы для theme и её change events,
   viewport/safe-area updates, back/close, haptics, Telegram links и start
   parameter. Операции, для которых молчаливый no-op может создать ложное
   подтверждение, возвращают явный discriminated result
   `supported|unsupported` и описанный fallback. Browser adapter использует
   browser primitives либо возвращает `unsupported`; bridge не хранит business
   state, не решает authorization и не подтверждает выполнение use case.
   `start_param` и прямой browser URL являются только недоверенными navigation
   hints: они могут выбрать экран/идентификатор для запроса, но API заново
   проверяет формат, существование объекта, actor status, permissions и
   ownership до чтения или изменения.
8. **Не открывать browser access преждевременно.** Пока browser authentication
   не выбран, запуск вне Telegram показывает ограниченный unauthenticated режим
   без пользовательских данных и изменяющих операций.
9. **Сохранить один release contract.** Собранные frontend assets входят в тот
   же reviewed application release, что API, bot и worker. Public HTTPS edge,
   DNS, TLS и Compose topology уточняются в CB-56. PostgreSQL остаётся
   непубличной.
10. **Сохранить выпускаемый `main`.** Незавершённые R2 surfaces закрываются
    server-side fail-closed feature flags. Отсутствующая, некорректная или
    недоступная конфигурация означает `disabled`; проверка применяется к API до
    выполнения use case, поэтому прямой URL или ручной HTTP-вызов не обходят
    выключенную navigation. Конкретное storage/cohort управление фиксируется в
    CB-56. Release 1 фиксируется аннотированным tag
    `v1.0.0`, GitHub Release и immutable image digest после acceptance. Длинная
    `release/2` не создаётся. `release/1.x` потребует отдельного решения, если
    реально появится независимый patch lifecycle.
11. **Ограничить R2 parity.** Пилот Release 1 продолжается параллельно. До его
    результатов R2 не добавляет новую экономику, монетизацию, публичную
    регистрацию и новые продуктовые направления.

## Контракт готовности к браузерному интерфейсу

Готовность означает только следующее:

- domain/application не знают о Telegram WebView;
- API авторизует внутреннюю сессию, а не Telegram payload в каждом запросе;
- каждый защищённый use case читает актуальные status, role, permissions и
  ownership из PostgreSQL, а не доверяет session/client claims;
- frontend не обращается к Telegram SDK вне `PlatformBridge`;
- `PlatformBridge` сообщает capabilities и явные unsupported/fallback results;
- router поддерживает прямые URL независимо от истории Telegram chat;
- `start_param` и прямой URL остаются недоверенными navigation hints;
- responsive components и semantic design tokens не зависят от одного
  viewport или принудительной dark theme;
- browser mode может получить новый auth adapter без отдельного backend.

Готовность не означает создание универсального plugin framework, публичной
регистрации, SEO-сайта или browser UI в Release 2.

Планировочная оценка при сохранении той же функциональности:

- цена такой готовности сейчас — примерно `10–15%` foundation-работ R2 на
  auth/session boundary, `PlatformBridge`, routing и дополнительные contract
  tests;
- подключение полноценного authenticated browser mode позднее — примерно
  `20–35%` поверх готового Mini App frontend на browser auth, desktop layout,
  прямые URL, browser security и альтернативные уведомления;
- публичный продукт с новой регистрацией, SEO, платежами или несколькими
  сообществами является новым продуктовым срезом и этой оценкой не покрывается.

Оценки являются диапазонами планирования, а не обязательством по срокам.

## Рассмотренные альтернативы

### Переписать бот как отдельное Mini App приложение

Отклонено: появятся две реализации переходов, прав и экономики, а bot fallback
начнёт расходиться с frontend.

### Использовать только `Telegram.WebApp.sendData`

Отклонено как основной transport: строковый обмен с ботом подходит для малых
форм, но не даёт удобного versioned API для каталогов, конкурентных изменений,
истории и будущего browser UI.

### Передавать `initData` в каждый application use case

Отклонено: Telegram становится частью application contract, а будущий browser
auth вынуждает менять бизнес-логику.

### Python-rendered UI или HTMX

Подход мог бы сократить отдельный frontend toolchain, но хуже соответствует
насыщенному app-like интерфейсу, offline/loading состояниям и platform adapters.

### Next.js и SSR

Отклонено до появления требований SEO или серверного рендеринга. Для закрытого
Mini App SPA добавляет runtime и deployment сложность без подтверждённой пользы.

### Микросервисы и отдельная база для API

Отклонено: транзакционная экономика и текущая нагрузка выигрывают от локальных
транзакций одной PostgreSQL. Transport boundary достаточно для независимого
развития интерфейсов.

### Длинная интеграционная ветка Release 2

Отклонено: текущий protected release строится из `main`, а feature flags
позволяют сохранять его выпускаемым без накопления большого отдельного merge.

## Последствия

Положительные:

- бот, Mini App и будущий браузер используют одни правила и данные;
- browser UI добавляется через auth/platform adapters, а не новый backend;
- текущие транзакции, outbox, аудит и rollback discipline сохраняются;
- frontend можно тестировать в обычном браузере без эмуляции всего Telegram SDK;
- R2 можно включать постепенно, сохраняя bot fallback.

Ограничения и стоимость:

- появляется Node/frontend toolchain и новая публичная HTTPS attack surface;
- auth/session, CSRF, CSP, CORS/same-origin, rate limiting и safe logging требуют
  отдельной security-приёмки;
- production runtime получает новый процесс `api` и TLS edge;
- transport-neutral refactoring нужен до массового переноса экранов;
- часть Telegram-native действий в браузере будет отсутствовать или иметь
  другой UX;
- browser authentication и внешние уведомления остаются отдельными решениями.

## Связанные материалы

- [Capability Release 2](../release-2/README.md)
- [Parity-матрица Release 2](../release-2/PARITY_MATRIX.md)
- [ADR-0005 — Технологический стек MVP](0005-mvp-technology-stack.md)
- [ADR-0006 — Транзакционная граница Telegram updates](0006-telegram-update-transaction-boundary.md)
- [ADR-0009 — Самостоятельное размещение пилота](0009-self-hosted-pilot-runtime.md)
- [ADR-0011 — Защищённый release](0011-protected-single-ci-release.md)
- [Заменяющее решение ADR-0016](0016-mini-app-only-runtime.md)
- [Telegram Mini Apps](https://core.telegram.org/bots/webapps)
