# CB-49 — план реализации

## Цель

Зафиксировать согласованный контракт Release 2 до начала runtime-разработки:
Telegram Mini App становится первым визуальным клиентом общей платформы, бот
сохраняется как вход, уведомления и fallback, а будущий браузерный интерфейс
может подключиться к тем же API и application-сценариям без копирования домена.

Задача имеет уровень 3 по ADR-0004: она меняет форму приложения, добавляет
будущую публичную HTTPS-границу и затрагивает authentication, authorization,
идемпотентность и release lifecycle.

## Область изменений

- создать канонический capability-контракт Release 2;
- создать начальную parity-матрицу сценариев Release 1;
- предложить и после независимой проверки принять ADR multi-interface
  архитектуры;
- зафиксировать границы `ActorContext`, внутренней сессии, auth adapters,
  operation identity и frontend `PlatformBridge`;
- зафиксировать React + TypeScript + Vite и FastAPI как стек Release 2 при
  сохранении Python-монолита и одной PostgreSQL;
- описать стратегию `v1.0.0`, выпускаемого `main`, feature flags и отсутствие
  постоянной `release/1.x` до отдельной необходимости;
- отразить новое решение в карте MVP, технологическом стеке, журнале решений и
  индексе ADR;
- связать документацию с Jira-эпиком CB-48 и задачами CB-50 — CB-58.

## Вне области изменений

- реализация HTTP API, frontend, auth/session, миграций и deployment;
- создание Git tag `v1.0.0` и GitHub Release — это CB-50;
- финальный дизайн и design tokens — это CB-58;
- изменение экономики, ролей, состояний, кармы, правил заданий и модерации;
- выбор browser auth provider;
- выбор TLS terminator и production domain;
- платежи, публичная регистрация и новые направления платформы.

## Текущее состояние

- Release 1 — модульный Python 3.13 монолит с процессами `bot` и `worker`, одной
  PostgreSQL, outbox и Telegram long polling.
- `domain` и `application` защищены архитектурными тестами от импортов aiogram и
  SQLAlchemy, но application-контракты местами принимают `telegram_user_id` и
  `update_id`.
- production release принимает только актуальный merge commit `main` и один
  immutable GHCR digest.
- FastAPI, публичный HTTP API и веб-приложение сознательно не входили в MVP.
- CB-24 изменена решением владельца от 2026-08-16: parity-разработка R2 может
  идти параллельно пилоту, но новые продуктовые правила остаются зависимыми от
  его данных.
- На момент планирования package version равна `0.1.0`, Git tags отсутствуют, а
  точка Release 1 ещё не зафиксирована.

## Предлагаемое решение

1. Сохранить модульный монолит и одну доменную модель.
2. Добавить в R2 второй inbound transport: versioned HTTPS API на FastAPI.
3. Telegram transport и HTTP transport разрешают внешнюю identity во внутренний
   `ActorContext` до вызова application-сценария. Его subject — только
   внутренний `member_id`; provider, session identity и время authentication
   допустимы как metadata для аудита. Клиентские или сохранённые session claims
   о role, status, permissions и ownership не являются доверенными. Каждый
   защищённый use case заново читает текущее членство, статус, права и владение
   объектом из PostgreSQL.
4. Auth adapter проверяет provider-specific proof. Telegram Mini App adapter
   валидирует исходный `initData`, его подпись и срок, затем создаёт
   краткоживущую внутреннюю сессию. Application не принимает `initData`.
5. Изменяющие команды получают transport-neutral operation identity:
   `transport_namespace`, внутренний `actor_id`, внешний key, `command_name` и
   fingerprint нормализованного payload. Receipt уникален в scope
   `(transport_namespace, actor_id, external_key)` и хранит command,
   fingerprint и outcome. Exact replay возвращает outcome; повтор scoped key с
   другим command или fingerprint отклоняется как conflict. Receipt, domain,
   ledger, audit и outbox коммитятся одной транзакцией. Cross-transport гонки
   дополнительно ограничиваются существующими state/unique invariants.
6. Frontend реализуется как React + TypeScript + Vite SPA. Доступ к Telegram SDK
   разрешён только через `PlatformBridge`. Контракт сообщает capabilities и
   возвращает явный результат `supported|unsupported` для действий, где
   молчаливый no-op может создать ложное подтверждение. Он нормализует theme и
   viewport events, safe area, back/close, haptics, Telegram links и start
   parameter, но не хранит business state и не выполняет authorization.
   `start_param` и прямой URL являются недоверенными navigation hints; доступ к
   объекту всегда повторно проверяет API.
7. До появления browser authentication обычный браузер запускает UI только в
   явно ограниченном режиме и не получает пользовательские данные.
8. Один frontend и один HTTP contract обслуживают Mini App и будущий браузер;
   отдельный browser backend запрещён без нового решения.
9. `main` остаётся выпускаемым. Незавершённый R2 закрывается server-side
   fail-closed feature flags: отсутствие или ошибка конфигурации означает
   `disabled`, а прямой URL/API не может обойти выключенный UI. Release 1
   фиксируется immutable tag, release metadata и image digest.
10. Public HTTPS, edge, rollout и rollback детализируются в CB-56, не
    придумываются этой документационной задачей.

## Ключевые решения и альтернативы

- **Выбрано:** общие application services и API. **Отклонено:** копирование
  логики в Mini App или будущий browser backend.
- **Выбрано:** внутренняя сессия после сменяемого auth adapter. **Отклонено:**
  передавать Telegram `initData` в каждый use case либо делать Telegram
  обязательным для будущего browser UI.
- **Выбрано:** SPA React/TypeScript/Vite. **Отклонено:** SSR/Next.js без
  требований SEO и Python-rendered UI, усложняющий app-like state и platform
  adapters.
- **Выбрано:** существующий модульный монолит. **Отклонено:** микросервисы,
  Redis и новый брокер без измеримой нагрузки.
- **Выбрано:** tag `v1.0.0` и выпускаемый `main`. **Отклонено:** длинная ветка
  `release/2`; `release/1.x` откладывается до реальной потребности в независимых
  patch-релизах.

## Шаги реализации

1. Создать плановый пакет и ADR-0014 со статусом `Предложено`.
2. Получить независимое ревью полного планового пакета.
3. После одобренного повторного review показать владельцу точную редакцию
   ADR-0014 и получить отдельное явное принятие. Только затем изменить статус
   ADR-0014 на `Принято` и продолжить реализацию capability-документов.
4. Создать `docs/release-2/README.md` в формате capability contract.
5. Создать `docs/release-2/PARITY_MATRIX.md` с полной картой поверхностей R1 и
   владельцами будущих доказательств.
6. Обновить индекс ADR, карту MVP, `TECH_STACK.md`, `HANDOFF.md` и журнал
   решений.
7. Создать `implementation-report.md`, выполнить проверки документации и
   независимое финальное ревью.
8. После `Status: approved` выполнить commit, push, PR, CI/review и merge.
9. Зафиксировать в Jira ветку, commit, PR, проверки и оставшиеся runtime-gates.

## Риски и меры снижения

- **Разрастание R2 в новую платформу.** Non-goals запрещают новые сервисы,
  платежи и правила до данных пилота; задачи эпика построены вокруг parity.
- **Telegram coupling останется в application.** ADR задаёт обязательный
  `ActorContext`; CB-51 имеет отдельную приёмку архитектурных границ.
- **Слишком абстрактная готовность к браузеру.** Фиксируются только два реальных
  extension points — auth adapter и `PlatformBridge`; универсальный framework
  плагинов не создаётся.
- **Security drift между Mini App и браузером.** Оба клиента используют
  внутреннюю сессию и server-side authorization; browser auth остаётся закрытым
  до отдельного решения.
- **Отозванное право продолжит жить в сессии.** `ActorContext` не доверяет
  role/status/permission claims; защищённый use case загружает текущее состояние
  и ownership из PostgreSQL.
- **Повтор idempotency key выполнит другой запрос.** Receipt хранит command и
  fingerprint; несовпадение возвращает conflict без доменного эффекта.
- **Прямой URL обойдёт rollout.** Feature gate применяется server-side и
  fail-closed до authorization/use case, а не только скрывает navigation.
- **Незавершённый R2 нарушит production.** `main` остаётся releasable, новые
  поверхности закрываются feature flags, миграции будущих задач только
  expand-only.
- **Дизайн лендинга снизит удобство ежедневного UI.** В CB-58 палитра отделена
  от композиции: выразительные эффекты ограничиваются акцентами, а рабочие
  экраны остаются плотными и сканируемыми.

## Проверки

- все внутренние Markdown links разрешаются в существующие файлы;
- ADR-0014 присутствует в индексе и имеет согласованный статус;
- D-033 не противоречит D-025, CB-24 и границам MVP;
- capability содержит все разделы `product-capability`;
- parity-матрица покрывает регистрацию, каталоги, задания, экономику, профиль,
  карму, модерацию, администрирование и уведомления;
- семантическая проверка подтверждает, что `ActorContext` содержит internal
  `member_id`, а актуальные role/status/permissions/ownership читаются
  server-side для каждого защищённого use case;
- operation protocol явно содержит namespace/scope/fingerprint/outcome,
  возвращает сохранённый outcome для exact replay и conflict для другого
  payload без повторного доменного эффекта;
- `PlatformBridge` имеет capability detection, нормализованные события, явный
  unsupported/fallback и маркирует `start_param`/direct URL как недоверенную
  навигацию без authorization semantics;
- выключенный или некорректно настроенный server-side feature flag блокирует
  прямой API и URL, а не только скрывает UI;
- поиск подтверждает отсутствие утверждений о уже реализованных API/frontend;
- YAML-критерий для CB-49 — `not applicable`, если
  `git diff --name-only -- '*.yml' '*.yaml'` пуст; при появлении YAML diff задача
  обязана добавить явный parse gate до final review;
- `git diff --check`;
- `uv run ruff format --check .` и `uv run ruff check .` как базовый repository
  smoke, если документационные изменения не требуют более широкого прогона;
- secret-like scan по добавленным файлам без вывода содержимого секретов;
- независимый `final-review` уровня 3.

Ручной `test-plan.md` не требуется: задача не меняет runtime и не заявляет
пользовательский сценарий реализованным. Live Telegram gate остаётся в CB-50 и
задачах реализации R2.

## Критерии готовности

- закрыты все критерии CB-49 с конкретными ссылками и доказательствами;
- `plan-review.md` содержит точный `Status: approved`;
- точная post-review редакция ADR-0014 отдельно принята владельцем и не
  маскирует открытые решения;
- capability и parity-матрица являются каноническими входами для CB-51 — CB-58;
- `implementation-report.md` и `final-review.md` подтверждают отсутствие
  runtime-изменений, секретов и незакрытых документационных конфликтов;
- ветка `task/CB-49` прошла PR и CI до merge в `main`.
