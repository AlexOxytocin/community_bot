# CB-49 — финальное ревью

Status: approved

## Проверенная область

- актуальные Jira-задачи CB-49 и CB-48, связь с CB-24 и блокирование CB-51,
  критерии приёмки и комментарии 10158–10160;
- `tasks/CB-49/plan.md`, `plan-source-context.md`, approved `plan-review.md` и
  обновлённый `implementation-report.md`;
- принятый `docs/adr/0014-multi-interface-release-2.md`, capability-контракт
  `docs/release-2/README.md`, исправленная
  `docs/release-2/PARITY_MATRIX.md` и обновлённые канонические документы MVP;
- действующие правила проекта, workflow уровня 3, релевантные ADR, полный
  текущий scope изменённых и новых файлов, состояние ветки и diff;
- оба замечания первого final review и заявленные после исправлений проверки.

## Уровень процесса и условные барьеры

| Барьер | Требуется | Результат | Доказательство |
|---|---|---|---|
| План уровня 3 | Да | Пройден | Полные `plan.md` и `plan-source-context.md` |
| Независимое plan-review | Да | Пройден | `tasks/CB-49/plan-review.md`: `Status: approved` |
| Явное принятие ADR владельцем после plan-review | Да | Пройден | Jira-комментарий 10159 фиксирует approved review при статусе ADR `Предложено`; более поздний комментарий владельца 10160 принимает точную post-review редакцию; ADR-0014 имеет статус `Принято` |
| Test plan | Нет | Не применимо | Scope содержит только Markdown-документацию и артефакты задачи; runtime, схема, зависимости, configuration и deployment не изменены |
| Live Telegram gate | Нет | Не применимо | Пользовательское и production-поведение не менялось и не объявлено изменённым |
| Финальное ревью уровня 3 | Да | Пройден | Повторная независимая проверка не выявила обязательных исправлений |

## Критические замечания

Критических замечаний нет.

## Существенные замечания

Существенных замечаний нет.

Оба замечания первого final review закрыты:

1. `docs/release-2/PARITY_MATRIX.md` теперь закрепляет не более одной текущей
   оценки на направленную пару `автор → получатель`, eligibility после первой
   ненулевой полной или частичной выплаты по member-origin assignment между
   парой в любом направлении и его вечное сохранение как исторического факта.
   Это соответствует `docs/mvp/02_DOMAIN_RULES.md` и D-020.
2. `docs/release-2/README.md` теперь разделяет внутреннюю классификацию причин
   отказа для безопасной наблюдаемости и одинаковый внешний privacy-safe ответ
   для скрытого, отсутствующего и недоступного ресурса, включая поддельный
   callback, прямой UUID и stale cursor. Это соответствует
   `docs/mvp/07_SECURITY_AND_PRIVACY.md` и D-022.

## Незначительные замечания

Незначительных замечаний нет.

## Критерии приёмки

| Критерий CB-49 | Результат | Доказательство |
|---|---|---|
| Capability содержит обещание, ограничения, implementation contract, non-goals, открытые вопросы и handoff | Пройден | Все шесть разделов присутствуют в `docs/release-2/README.md` |
| ADR фиксирует границы, альтернативы и последствия | Пройден | ADR-0014 принят владельцем отдельным шагом после approved plan-review |
| Определены `ActorContext`, внутренняя сессия и сменяемые auth adapters | Пройден | Subject — internal `member_id`; provider/session — metadata; role/status/permissions/ownership заново читаются из PostgreSQL каждым защищённым use case |
| Идемпотентность отделена от transport | Пройден | Operation identity содержит namespace, actor, external key, command и canonical payload fingerprint; scoped receipt хранит outcome; exact replay, conflict и атомарность state/ledger/audit/outbox определены |
| Определены `PlatformBridge` и поведение вне Telegram | Пройден | Capability detection, нормализованные события, `supported|unsupported`, browser primitives/fallback описаны; business state и authorization из bridge исключены |
| Недоверенная навигация не обходит права | Пройден | `start_param`, query string и прямой URL являются только navigation hints; API повторно проверяет объект, статус, permissions и ownership |
| Rollout закрыт server-side fail-closed flags | Пройден | Missing/invalid/unavailable configuration означает `disabled`; прямой URL и HTTP-вызов не обходят gate |
| Описана цена будущего browser UI и переиспользование | Пройден | Оценки 10–15% и 20–35% ограничены той же функциональностью; публичный browser product, SEO, платежи и multi-community исключены |
| Зафиксированы `v1.0.0` и выпускаемый `main` | Пройден | Immutable tag/release после acceptance, releasable `main`, отсутствие постоянной `release/2`; фактический tag отнесён к CB-50 |
| Сохранена продуктовая логика и полнота паритета Release 1 | Пройден | Матрица покрывает вход, участников, экономику, каталог, задания, карму, споры, администрирование, уведомления и эксплуатационные gates; исправленная карма соответствует канону |
| Документация не объявляет незакрытые решения реализованными | Пройден | API, frontend, auth/session, schema, deployment, browser auth и дизайн прямо оставлены последующим задачам |
| Markdown/YAML и независимая diff-проверка успешны | Пройден | 13 Markdown-файлов без битых локальных ссылок; YAML-gate `NOT_APPLICABLE`; `git diff --check` успешен |

## Тесты и проверка ключевого сценария

- независимый scan локальных Markdown-ссылок — 13 файлов, 0 битых ссылок;
- повторная семантическая проверка ключевых контрактов — замечаний нет; заявленные
  18/18 assertions подтверждаются содержанием ADR, capability, parity-матрицы и
  канонических правил;
- YAML-gate — `NOT_APPLICABLE`, изменённых или новых `.yml`/`.yaml` нет;
- `git diff --check` — пройдено;
- `uv run ruff format --check .` — пройдено, 472 файла отформатированы;
- `uv run ruff check .` — пройдено;
- независимый scan типовых secret-like паттернов — 13 файлов, совпадений нет;
- аудит ложных runtime-утверждений — пройден: документы описывают контракт и
  будущую реализацию, а не выдают API, frontend или deployment за готовые.

Runtime-тесты, browser E2E и live Telegram acceptance для CB-49 не требуются:
задача не меняет исполняемое поведение. Эти gates корректно закреплены за
задачами реализации и release acceptance CB-51–CB-57.

## Документация и язык

Смысловые артефакты написаны на русском; английский используется для
идентификаторов, полей API и точных технических терминов. Локальные ссылки между
capability, ADR, MVP, parity matrix и handoff разрешаются. Обновления ADR index,
карты MVP, технологического стека, журнала решений и handoff согласованы между
собой. Browser readiness не объявлена самостоятельным browser product.

## Секреты и безопасность

Секреты, токены, cookies, session strings, телефоны, Telegram ID и приватные
payload не обнаружены. Trust boundary для Telegram `initData`, внутренней
session, `ActorContext`, свежей server-side authorization и недоверенной
навигации определён. Исправленный HTTP-контракт сохраняет защиту от enumeration,
а наблюдаемость не требует логировать identity или приватный payload.

## Процесс Git/Jira

- текущая ветка: `task/CB-49`;
- `HEAD`, `origin/main` и merge-base совпадают:
  `1f2bfd766ea9e9511585a4666470edc8d993d375`;
- полный текущий scope состоит из 13 Markdown-файлов документации и артефактов
  CB-49; runtime, зависимости, миграции, deployment и несвязанные файлы не
  изменены;
- CB-49 находится в статусе `В работе`, имеет родителя CB-48 и блокирует CB-51;
- CB-48 связан с CB-24 и разрешает архитектурную/parity-подготовку R2
  параллельно пилоту без новой экономики, монетизации, публичной регистрации и
  новых продуктовых направлений;
- принятие ADR владельцем произошло после approved plan-review и до фиксации
  capability-пакета;
- commit, push, PR, merge, Jira-комментарии и переходы в рамках final review не
  выполнялись.

## Обязательные действия

Обязательных исправлений по результатам финального ревью нет.

## Остаточные риски

- Формат browser session, CSRF/revocation и browser auth provider остаются
  отдельными решениями CB-52 и будущей browser-задачи.
- TLS edge, production domain, storage/cohort feature flags и rollback должны
  быть конкретизированы и проверены в CB-56.
- Оценки стоимости browser UI являются архитектурным ориентиром, а не сметой;
  новые продуктовые поверхности потребуют отдельной оценки.
- Полный runtime-паритет будет доказан только задачами CB-51–CB-57, включая
  автоматические проверки и live Mini App acceptance после server deploy.
