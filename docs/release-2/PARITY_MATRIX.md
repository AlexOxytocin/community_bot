# Release 2 — матрица функционального паритета

**Статус:** Начальная карта приёмки

**Дата:** 2026-08-16

**Capability:** [Release 2](README.md)

**Архитектура:** [ADR-0014](../adr/0014-multi-interface-release-2.md)

## Назначение

Матрица переводит действующие сценарии Release 1 в проверяемый план Release 2.
Она не обещает новый продуктовый функционал: каждая строка должна сохранить те
же доменные состояния, экономические проводки, аудит, outbox и права, которые
уже действуют в Telegram-боте.

Статусы поверхностей:

- `bot-only` — сценарий намеренно остаётся только в боте в Release 2;
- `planned` — Mini App путь запланирован, но ещё не реализован;
- `shared` — сценарий использует общий application/API contract;
- `release-gate` — доказательство обязательно для выпуска `v2.0.0`.

Источники сценариев: [user flows](../mvp/03_USER_FLOWS.md),
[bot interface](../mvp/05_BOT_INTERFACE.md),
[domain rules](../mvp/02_DOMAIN_RULES.md) и
[moderation](../mvp/08_MODERATION_AND_ABUSE.md).

## Вход и участники

| Сценарий Release 1 | Бот в R2 | Mini App | Задача | Доказательство паритета |
|---|---|---|---|---|
| `/start`, invite, правила и первичная анкета | `bot-only` | Не выпускается | CB-50, CB-57 | Live bot acceptance; Mini App не выдаёт session до появления member |
| Возобновление незавершённой регистрации | `bot-only` | Не выпускается | CB-50, CB-57 | Повторный `/start` продолжает существующий flow без дубликата member |
| Рассмотрение заявки администратором | Fallback | `planned` | CB-55 | Одинаковый статус member, audit и уведомление при approve/reject |
| Профиль участника и его видимые поля | Fallback | `planned` | CB-53 | API и bot применяют одинаковую политику видимости и свежие права из БД |
| Каталог участников и просмотр разрешённого профиля | Fallback | `planned` | CB-53 | Совпадают фильтры active/status/privacy; прямой URL не обходит authorization |

## Экономика, прогресс и статистика

| Сценарий Release 1 | Бот в R2 | Mini App | Задача | Доказательство паритета |
|---|---|---|---|---|
| Баланс и журнал операций | Fallback | `planned` | CB-53 | Баланс и ledger читаются из одного источника, без вычислений во frontend |
| Уровень, опыт и прогресс | Fallback | `planned` | CB-53 | Совпадают активная product config, XP и пороги уровней |
| Статистика созданных и выполненных заданий | Fallback | `planned` | CB-53 | Одинаковые агрегаты и правила включения terminal states |
| Рейтинг участников | Fallback | `planned` | CB-53 | Одинаковые сортировка, tie-break и privacy rules |

## Каталог и создание заданий

| Сценарий Release 1 | Бот в R2 | Mini App | Задача | Доказательство паритета |
|---|---|---|---|---|
| Фильтры каталога, список и полная карточка | Fallback | `planned` | CB-53 | Одинаковая видимость, статусы, категории и pagination semantics |
| Свободный черновик задания | Fallback | `planned` | CB-54 | Один application draft; повтор операции не создаёт второй черновик |
| Выбор `solo|group`, категории, размера и награды | Fallback | `planned` | CB-54 | Сервер применяет D-032 и одинаковые ограничения независимо от клиента |
| Число исполнителей и полный резерв group task | Fallback | `planned` | CB-54 | Резерв рассчитан и проверен сервером перед publish и при повторе команды |
| Название, описание, критерии, материалы, срок и формат | Fallback | `planned` | CB-54 | Совпадают обязательность, лимиты и normalization полей |
| Предпросмотр, изменение полей и публикация | Fallback | `planned` | CB-54 | Exact replay publish возвращает прежний outcome без второй проводки/outbox |
| Возобновление, редактирование и удаление черновика | Fallback | `planned` | CB-54 | Совпадают ownership, допустимые transitions и audit |
| «Мои задания»: активные, последние завершённые и архив | Fallback | `planned` | CB-53 | Сохраняются D-031, лимит 10 и pagination архива |

## Выполнение и приёмка результата

| Сценарий Release 1 | Бот в R2 | Mini App | Задача | Доказательство паритета |
|---|---|---|---|---|
| Принятие solo/group задания | Fallback | `planned` | CB-54 | Одна assignment, защита от гонки и одинаковое изменение доступных слотов |
| Отмена принятия исполнителем | Fallback | `planned` | CB-54 | Одинаковый transition, возврат слота/резерва и audit |
| Сохранение версий результата | Fallback | `planned` | CB-54 | Версии не теряются; ownership и terminal-state guards совпадают |
| Отправка результата автору | Fallback | `planned` | CB-54 | State, audit и durable notification коммитятся атомарно |
| Полное подтверждение результата | Fallback | `planned` | CB-54 | Совпадают credit/XP ledger, assignment/task state и outbox |
| Частичное подтверждение | Fallback | `planned` | CB-54 | Совпадают разрешённые суммы, проводки, опыт и итоговые состояния |
| Отклонение результата | Fallback | `planned` | CB-54 | Совпадают state, доступность спора, audit и уведомления |
| Завершение набора group task | Fallback | `planned` | CB-54 | D-032: свободный резерв возвращён, новые принятия блокируются |

## Отмена, карма и споры

| Сценарий Release 1 | Бот в R2 | Mini App | Задача | Доказательство паритета |
|---|---|---|---|---|
| Мгновенная отмена свободного задания | Fallback | `planned` | CB-54 | Одинаковые status, возврат резерва, audit и replay outcome |
| Согласованная отмена занятого задания | Fallback | `planned` | CB-54 | Отдельный durable response каждого исполнителя и атомарный итог |
| Оценка кармы после допустимого взаимодействия | Fallback | `planned` | CB-54 | Не более одной текущей оценки на направленную пару `автор → получатель`; eligibility возникает после первой ненулевой полной/частичной выплаты по member-origin assignment между парой в любом направлении и навсегда остаётся историческим фактом; видимость комментария и audit совпадают |
| Открытие спора | Fallback | `planned` | CB-54 | Один dispute на разрешённый исход; повтор не создаёт дубликат |
| Рассмотрение и решение спора | Fallback | `planned` | CB-55 | Совпадают права, ledger/state effects, обоснование и уведомления |
| Одна апелляция | Fallback | `planned` | CB-55 | Ограничение одной апелляции и история решений одинаковы |

## Администрирование и модерация

| Сценарий Release 1 | Бот в R2 | Mini App | Задача | Доказательство паритета |
|---|---|---|---|---|
| Категории и фиксированные шаблоны | Fallback | `planned` | CB-55 | Одинаковые active/version rules и audit изменений |
| Приглашения и регистрационные заявки | Fallback | `planned` | CB-55 | Нет публичной регистрации; права и одноразовость проверяет сервер |
| Черновик задания сообщества и подтверждение владельцем | Fallback | `planned` | CB-55 | Сохраняются D-028, reviewer/approver identity и audit |
| Алерты повторяющихся взаимодействий | Fallback | `planned` | CB-55 | Те же приватные risk signals и отсутствие автоматического наказания |
| Кейсы fraud/no-show и санкции | Fallback | `planned` | CB-55 | Права, evidence visibility, решение и audit совпадают |
| Назначение и снятие администратора | Fallback | `planned` | CB-55 | Только `superadministrator`; актуальное право читается из БД |
| Product config и административный аудит | Fallback | `planned` | CB-55 | Immutable/versioned config и доступ к audit не расширяются клиентом |

## Уведомления и эксплуатация

| Сценарий Release 1 | Бот в R2 | Mini App | Задача | Доказательство паритета |
|---|---|---|---|---|
| Durable Telegram notifications | `shared` | Deep link в экран | CB-54, CB-55 | Одно outbox event, retry без дубликата и безопасный navigation hint |
| Ошибки доставки и повтор worker | `shared` | Только отображение состояния | CB-56 | Существующая retry/dead-letter дисциплина и очищенные логи |
| Server-side feature flags | Fallback всегда доступен | `release-gate` | CB-56 | Missing/invalid config означает disabled; прямой API/URL заблокирован |
| HTTPS health/readiness и rollback | Не ухудшен | `release-gate` | CB-56 | Один immutable release, TLS edge, readiness и документированный rollback |
| Полная acceptance паритета | Live bot baseline | `release-gate` | CB-57 | Автотесты, browser runtime smoke и live Mini App после server deploy |

## Правило закрытия строки

Строка получает `shared` или `release-gate: passed` только когда одновременно:

1. реализованы API и frontend path либо явно подтверждён статус `bot-only`;
2. domain/application тесты показывают тот же результат, что и bot path;
3. mutation проверяет authentication, свежие server-side права и operation
   identity с exact replay/conflict;
4. state, ledger, audit и outbox подтверждены одной транзакционной проверкой;
5. frontend path прошёл smoke в обычном браузерном runtime;
6. для выпуска выполнена живая Mini App проверка после deployment актуального
   release на сервер.

Успешный HTTP `200` или нарисованный экран сами по себе паритетом не считаются.
Если состояние красивое, а ledger уехал в закат, это всё ещё дефект, просто уже
с хорошей типографикой.
