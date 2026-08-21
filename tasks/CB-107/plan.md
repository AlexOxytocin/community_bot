# CB-107 — план профиля участника и публичных ссылок

## Результат

Заменить действующий экран профиля Mini App на один согласованный сценарий из
11 экранов/состояний по трём каноническим доскам CB-107. Свой профиль показывает
Telegram username, город, уровень, кредиты, опыт, карму, описание, навыки и до
пяти публичных ссылок. Чужой профиль показывает только безопасные публичные
поля, опыт, уровень, агрегированную карму и разрешённое действие оценки кармы;
кредиты и редактирование недоступны.

Работа имеет уровень риска `3`: меняются auth projection, публичный DTO,
идемпотентная mutation, схема PostgreSQL и связанная browser-навигация. План
должен получить независимый `plan-review.md` со `Status: approved` до начала
реализации.

## Жёсткие границы

1. Каноничны только три изображения, перечисленные с SHA-256 в
   `plan-source-context.md`. Более ранние profile boards не задают поведение.
2. Реализуются ровно 11 экранов/состояний: заполненный свой профиль, чужой
   профиль, частично заполненный свой профиль; редакторы имени, города,
   описания и навыков; список, создание, редактирование и подтверждение удаления
   ссылки.
3. Не создаются profile hub, универсальный inline-editor, preview, отдельная
   кнопка `Отмена` или второй способ редактирования. Назад отбрасывает локальный
   черновик; `Сохранить` — единственная обычная mutation-кнопка. Удаление
   выполняется только большой кнопкой `Удалить` после явного подтверждения.
4. Один и тот же карандаш открывает редактор своего конкретного блока. В строке
   ссылки остаётся компактная красная корзина; на больших разрушительных
   кнопках и в подтверждении написано `Удалить`.
5. Legacy profile frontend удаляется, а не сохраняется как fallback: старые
   handlers, state, selectors, routes, строки и CSS-классы не сосуществуют с
   новой реализацией. Shell, нижняя навигация и общий back control сохраняются.
6. Пустой блок своего профиля показывает контекстный CTA. Пустое публичное поле
   чужого профиля отсутствует целиком. Статистика созданных/завершённых заданий
   в профиле больше не отображается.
7. Надёжность удаляется только из активного представления Mini App: свой и
   чужой профиль, список/карточка/деталь участника и UI helpers. Не меняются
   reliability domain, события, writers, corrections, вычисления, DTO/API,
   leaderboard ordering, БД, миграции надёжности, тесты её инвариантов и
   документация. `own_statistics` и `MeDto.statistics` сохраняются для
   rollback-совместимости, но frontend их не рисует.
8. Не добавляются dependency, service, repository, framework, generic form
   engine или новый endpoint. Используются текущие FastAPI/Pydantic,
   SQLAlchemy/Alembic, native HTML/CSS/ES modules и существующая receipt-схема.
9. Внешние URL открываются только после серверной валидации. Клиент не определяет
   права, ownership, допустимость кармы или профильную видимость.
10. В этой задаче не меняются другие продуктовые экраны, экономика, задания,
    модерация, уведомления, release topology или канонические продуктовые docs.

## Контракт данных и API

### Публичная ссылка

Сервер хранит упорядоченный JSON-массив в `members.profile_links_json`:

```json
[
  {
    "id": "server-generated-uuid",
    "label": "LinkedIn",
    "url": "https://linkedin.com/in/alex"
  }
]
```

- максимум пять объектов, порядок массива является порядком отображения;
- `id` создаётся сервером при первом успешном `create`, стабилен при edit и не
  принимается от клиента для создания;
- `label` после схлопывания пробелов содержит `1..32` символа;
- `url` содержит не более 2048 символов, является абсолютным `https://` URL с
  непустым hostname, без credentials и управляющих символов; fragment и path
  допустимы, если весь URL проходит эти правила;
- повтор label или URL разрешён: задача не задаёт ложную уникальность;
- неизвестные ключи, неверный UUID, update/delete отсутствующей ссылки и шестая
  ссылка отклоняются до записи;
- API никогда не возвращает Telegram user ID, raw auth proof, private karma,
  reliability history или административные данные.

`PUT /api/v1/me/profile` остаётся единственной mutation-границей профиля.
Текущий текстовый command сохраняется для `display_name`, `city`, `short_bio` и
`skill_tags`. Для `profile_links` добавляется строго типизированное значение с
`action=create|update|delete`, `link_id` только для update/delete и полями
`label`/`url` только там, где они нужны. Pydantic запрещает лишние комбинации.
Route продолжает строить fingerprint из validated command и числовой
`update_id` из actor/resource/command/`Idempotency-Key` в namespace
`profile-update-v1`.

Создание server UUID выполняется внутри существующей заблокированной
транзакции только после проверки отсутствия receipt. Exact replay того же
actor/key/command/fingerprint возвращает прежний успешный эффект без второго
UUID, второй ссылки, audit или receipt; конфликтующий payload с тем же key даёт
`409`. Перед реализацией добавляется characterization test этого поведения.
Если текущая receipt-граница не может доказать exact replay create/edit/delete,
реализация останавливается: новая idempotency-подсистема в CB-107 не строится.

`MeDto` и `MemberDto` получают `profile_links`; `MeDto` также получает свой
`telegram_username`. Detail-only `MemberDetailDto.can_rate_karma=true` тогда и
только тогда, когда один snapshot проходит тот же predicate, что `begin_vote`:
actor не target, оба effective `active`, historical pair eligibility существует.
Mutation повторно авторизуется; `/members` не получает поле или per-row query.
Reliability и `MeDto.statistics` не меняются. `SafeProfile`/own projection
возвращают immutable links, не ORM JSON list.

### Синхронизация Telegram username

`validate_telegram_init_data` после HMAC/age/shape возвращает trusted ID и username
по `^[A-Za-z0-9_]{5,32}$` либо `None` при signed absence; malformed отклоняет auth.
`initDataUnsafe`, query, form и claims не используются.

Existing session transaction берёт identity advisory gate и member row lock.
Неизвестный ID даёт `401` без member/audit/session effects. Signed absence означает
`NULL`: равное stored значение — no-op без audit; смена/очистка пишет member и один
allowlisted `telegram_username_changed` audit (`reason=updated|cleared`) без
proof/username. Session, member change и audit коммитятся вместе; injected failure
откатывает все три, exact repeat и concurrent update/clear сериализуются без новой подсистемы.

## Миграция `0022`

Файл `migrations/versions/0022_profile_links.py`:

- `revision = "0022"`, `down_revision = "0021"`;
- `upgrade()` добавляет `members.profile_links_json JSONB NOT NULL` с
  `server_default='[]'::jsonb`;
- DB checks требуют JSON array и `jsonb_array_length(profile_links_json) <= 5`;
- существующие строки после upgrade получают `[]`, без backfill и без изменения
  других колонок;
- `downgrade()` удаляет только новый check и колонку;
- исторические revisions `0001..0021` не редактируются.

Schema test выполняет реальный цикл `0021 → 0022`, проверяет default/NOT NULL/
checks и downgrade обратно до `0021` на изолированной БД. После первой реальной
записи ссылок production rollback использует предыдущий совместимый image на
схеме `0022`; destructive downgrade, теряющий ссылки, не выполняется без нового
явного решения владельца.

## Контракт 11 экранов и переходов

| № | Экран/состояние | Содержимое и действия | Назад, reload, focus |
|---:|---|---|---|
| 1 | Заполненный свой профиль `#/profile` | `@username`, город, уровень; кредиты/опыт/карма; bio, skills, links; одинаковые карандаши у identity/города/bio/skills/links | Root bottom-nav без back. Reload повторно читает authoritative API. После возврата focus на исходный карандаш/строку |
| 2 | Чужой профиль `#/members/:member_id` | Валидный server-normalized `@username ↗` открывает `https://t.me/<username>`; город, уровень, опыт, карма, непустые bio/skills/links; без credits/edit/reliability; карма только при `can_rate_karma` | Back возвращает в список/leaderboard; deep-link back имеет fallback в участников. Focus на заголовок/первое действие; own username всегда plain text |
| 3 | Частично заполненный свой профиль `#/profile` | Заполненные блоки как №1; вместо пустых bio/skills/links — отдельные CTA `Добавить описание`, `Добавить навыки`, `Добавить ссылки` | Те же правила root/reload/focus; пустые блоки чужого профиля не создаются |
| 4 | Имя `#/profile/edit/name` | Поле `Имя`, лимит `2..80`, counter, одна кнопка `Сохранить` | Back/popstate отбрасывает draft без request. Reload загружает authoritative имя. Initial focus в input; возврат — identity pencil |
| 5 | Город `#/profile/edit/city` | Поле `Город`, лимит `2..80`, одна кнопка `Сохранить` | Как №4; возврат — city pencil |
| 6 | О себе `#/profile/edit/bio` | Textarea `Описание`, лимит `10..500`, counter, одна кнопка `Сохранить` | Как №4; возврат — bio pencil/CTA |
| 7 | Навыки `#/profile/edit/skills` | Добавление по одному, удаление `×`, case-insensitive duplicate error, максимум 20, каждый `1..50`; сохраняется весь ordered list | Back отбрасывает draft. Reload читает список. Focus в поле нового навыка; возврат — skills pencil/CTA |
| 8 | Мои ссылки `#/profile/links` | Ordered rows; карандаш edit, compact red trash открывает №11; `+ Добавить ссылку` до лимита, counter `N / 5` | Back → own profile, focus на links pencil/CTA. Reload сохраняет порядок. После удаления focus на следующую строку либо Add |
| 9 | Новая ссылка `#/profile/links/new` | `Название`, `Ссылка`, presets как подсказки без скрытой mutation; одна кнопка `Сохранить` | Back отбрасывает draft → №8. Reload начинает пустой draft. Initial focus на label |
| 10 | Изменить ссылку `#/profile/links/:link_id` | Текущие label/URL; `Сохранить`; большая `Удалить` только открывает №11 | Back отбрасывает draft → №8. Неизвестный/deleted ID закрывается безопасной ошибкой без утечки. Focus на label |
| 11 | Подтверждение удаления `#/profile/links/:link_id/delete` | Фон недоступен; dialog/bottom sheet `Удалить <label>?`; единственная destructive кнопка `Удалить` | Из list Back → №8/focus trash этой строки; из edit → №10/focus большой `Удалить`; direct или reload → №8/focus pencil строки, при её исчезновении Add. Ни один Back не мутирует; confirm → №8/focus следующая pencil либо Add |

Save блокируется на время request. Retryable network/5xx сохраняет тот же
operation key и draft; изменение draft после ошибки создаёт новый key.
Validation/`409` показывает русскую ошибку рядом с полем, не применяет optimistic
state. Успешный ответ заменяет cached own projection и возвращает в экран-
источник. Поздний response предыдущего `screenRevision` не меняет новый экран.

## Внешние ссылки

`platform.js` получает один safe opener. Public link использует server-validated
URL; foreign-only username — только server-normalized value и фиксированный
`https://t.me/<username>`. Для Telegram destination приоритетен native
`openTelegramLink`, затем `openLink`; public URL использует `openLink`; общий
fallback — `window.open(url, "_blank", "noopener,noreferrer")` с явным failure.
Own/absent/malformed username не action; строки keyboard-accessible, только `textContent`, без `opener` и broad bridge refactor.

## Срезы реализации и владельцы файлов

### Срез 1 — storage, validation и exact mutation

- `migrations/versions/0022_profile_links.py` — новая колонка и reversible DDL;
- `src/community_bot/infrastructure/db/models.py` — mapping JSONB;
- `src/community_bot/domain/registration.py` — link command/value validation и
  лимиты рядом с существующими profile rules;
- `src/community_bot/application/registration.py` — immutable link projection,
  owner authorization, lock/receipt/audit/commit через существующий profile
  mutation path;
- `src/community_bot/infrastructure/db/registration.py` — чтение ordered links,
  server UUID create, replace/delete без отдельного repository;
- `src/community_bot/infrastructure/db/database.py` — только существующие UoW/
  session делегаты, нужные этому пути.

### Срез 2 — auth и privacy-safe HTTP contract

- `src/community_bot/transport/web.py` — strict request DTO, trusted signed
  username projection/sync, `MeDto`/`MemberDto` links, detail-only
  `can_rate_karma` и mapping; reliability и statistics DTO остаются
  byte-for-byte по смыслу;
- `src/community_bot/application/reputation.py` и
  `src/community_bot/infrastructure/db/reputation.py` — только добавление
  публичных links в уже существующий `SafeProfile`; reliability code и ordering
  не редактируются.

### Срез 3 — hard replacement frontend

- `src/community_bot/transport/static/app.js` — новые routes/state/renderers,
  11 состояний, back/reload/focus, mutation retries, links и удаление legacy
  profile/reliability presentation;
- `src/community_bot/transport/static/styles.css` — стили новых profile cards,
  field editors, empty CTA, link rows и confirm sheet; удалить legacy
  `.profile-field-*`, indicator и reliability presentation selectors;
- `src/community_bot/transport/static/platform.js` — только native openLink +
  secure browser fallback;
- `src/community_bot/transport/static/index.html` — не менять, если trace не
  выявит невозможность сохранить действующий shell/back/nav.

### Срез 4 — пропорциональные тесты

- `tests/unit/test_registration_domain.py` — table-driven link normalization и
  URL/limit rejects рядом с текущими profile cases;
- `tests/unit/test_web_auth.py` — signed username/absence, strict DTO/privacy и
  session sync failure boundary;
- `tests/integration/test_registration.py` — ordered storage и owner projection;
- `tests/integration/test_web_api.py` — create/edit/delete exact replay,
  conflicting replay, public/own DTO, concurrency limit и migration `0021↔0022`;
- `tests/browser/test_mini_app.py` — один connected profile journey на двух
  viewport, все 11 состояния, back/reload/focus/external open и единый
  zero-visible-reliability oracle.

Другие runtime/test/docs/migration files не входят в область. Расширение списка
останавливает implementation до доказанного trace и обновления одобренного
плана.

## Инвентарь удаления

Из `app.js` удаляются старые `editableProfileFields`, `profileValue`,
`profileFields`, `profileDetails`, `profileEdit`, route/state
`profile-settings`, inline `Отмена`, секция `Мои показатели`, строки статистики
заданий, `reliabilityText`, `reliabilityPercent` и все обращения к
`member.reliability` в active presentation. Из participant list/detail удаляется
текст/значение надёжности; карма и опыт сохраняются.

Из `styles.css` удаляются или полностью переназначаются только orphan selectors
старой профильной формы: `.profile-field-list`, `.profile-field-row`,
`.profile-field-editor`, `.profile-field-actions`, `.profile-field-status`,
`.indicator-list`, `.indicator-row`. Общие `.profile-dashboard`, `.primary`,
`.secondary.danger`, focus-visible, safe-area, shell и nav rules переиспользуются.

После замены static gate требует ноль legacy profile identifiers и ноль
UI-релевантных reliability identifiers в `app.js`; Git history остаётся
единственным rollback источником старого UI.

## Ponytail full

- `delete`: старый profile renderer/state/CSS удаляется вместо compatibility;
- `reuse`: один `PUT`, current operation key/fingerprint/receipt, current owner
  lock/audit/commit, current profile DTO и native shell;
- `native`: JSONB, UUID, `URL`/`window.open`, HTML controls и CSS; dependency не
  добавляется;
- `minimum code`: одна storage column, без link table/ordering column/repository,
  без form framework и без broad PlatformBridge;
- не упрощаются validation, privacy, ownership, accessibility, exact replay,
  focus и destructive confirmation.

## Gates и порядок

1. **Plan gate:** полный пакет из трёх файлов проходит независимый Level-3
   review. Публикация плана не запускает implementation.
2. **Replay/auth gate:** characterization доказывает exact link replay и trusted
   signed username/absence. Невозможность — stop без новой подсистемы.
3. **Schema gate:** isolated `0021 → 0022 → 0021` и повторный `→ 0022` проходят;
   существующие members получают `[]`, reliability tables/data не меняются.
4. **Contract gate:** targeted unit/integration tests подтверждают privacy,
   owner-only mutation, max five/order/stable UUID/URL validation и conflict.
5. **Browser gate:** один connected journey проходит при `375×812` и `430×932`,
   закрывает 11 состояний, back/reload/focus, empty/public rules и external open.
6. **Deletion gate:** zero-occurrence legacy profile и zero-visible reliability
   oracles зелёные; backend reliability diff отсутствует.
7. **Quality gate:** format/lint/type/node/diff/secret проверки из
   `test-plan.md` зелёные; затем `implementation-report.md` и независимый
   `final-review.md` получают `Status: approved`.
8. **Git/CI gate:** только после approval — commit, push, PR в `main`, успешные
   обязательные CI/review и merge. При изменении diff тесты/report/review
   повторяются.
9. **Deployment gate:** production acceptance разрешён только после deployment
   точного merged/reviewed commit новым web release, применения `0022`, health/
   readiness и безопасного rollback proof. До этого результат называется
   локально реализованным, не deployed/готовым.
10. **Live gate:** после deployment выполнить ровно Jira acceptance CB-107 на
    разрешённых test accounts без чтения чатов/медиа и без реальных сообщений.
    Скриншоты/логи не содержат auth proof, cookies, Telegram ID или PII.

## Stop conditions и остаточные риски

- receipt не гарантирует один server UUID/один audit на exact replay;
- auth username нельзя синхронизировать атомарно с созданием session без новой
  архитектурной подсистемы;
- публичный URL нельзя валидировать однозначно либо открыть без `opener`;
- links попадают в hidden/non-active projection или API раскрывает private
  поля;
- реализация требует изменить reliability backend/API/DB/ordering/tests/docs;
- migration затрагивает исторические revisions или требует destructive data
  rewrite;
- 11-state browser journey не воспроизводится после deep-link/reload/back;
- deployed commit/schema не совпадают с approved/merged результатом.

В каждом случае работа останавливается и возвращается владельцу с точным
конфликтом. Открытых продуктовых вопросов для начала реализации нет.
