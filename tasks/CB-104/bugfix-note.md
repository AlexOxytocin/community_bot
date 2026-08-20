# CB-104 — compact package note

## Симптом

Основной Mini App имел связанный набор блокеров: Karma не начиналась после
старого `profile_edit`; владелец не видел уже поддерживаемую отмену задания;
«Созданные мной» и редактор профиля открывались отдельными разреженными
экранами; форма создания не фиксировала personal slots, показывала город для
Online и вела через лишнее подтверждение preview. Task detail был разрежен, а
root-раздел назывался «Каталог» вместо «Задания».

## Причина

- actor-native Karma входила в общий text-flow owner до освобождения orphaned
  legacy/web `profile_edit`, а UI отображал любой HTTP 409 как stale revision;
- web projection не передавала существующий cancellation action, а owned list
  и P07 оставались отдельными presentation states;
- form UI не отражал уже существующие `TaskKind`/`TaskFormat` invariants, а
  Offline city не имел authoritative справочника;
- preview дублировал catalog card и добавлял T07 поверх существующей
  `TaskService.publish` команды.

## Правка

- `ReputationService.begin_vote` освобождает только actor-owned `profile_edit`;
  другие active flows по-прежнему fail-closed. Каждая Karma-команда использует
  exact server draft/revision, а публичные ошибки не раскрывают внутренние
  термины.
- `TaskService.request_cancellation` и существующая cancellation transaction
  проецируются в owned detail; root «Мои задания» хранит active tab/scroll и
  показывает compact owned cards.
- В Profile восемь полей существующего `PUT /me/profile` редактируются inline;
  metrics и domain/API contract не менялись.
- Personal всегда отправляет один slot, Group использует существующий минимум
  два. Новый web draft получает Online; city отсутствует в Online DOM/payload и
  очищается существующим whole-form revision owner. Offline использует один
  authenticated bounded lookup и exact server validation.
- `Предварительный просмотр` вызывает существующий `save_web`/preview; карточка
  переиспользует task-list presentation, а единственная CTA `Опубликовать`
  вызывает существующую idempotent `publish` без T07.
- Task detail получил compact metadata grid без изменения DTO/actions;
  пользовательские/a11y labels root-раздела заменены на «Задания», внутренние
  routes/API/cache identifiers сохранены.

Новых schema, migration, repository, framework или state/service layers нет.

## Проверка

- combined focused API/browser set после narrowing: `8 passed in 29.34s`;
- отдельный повтор cancellation checkpoint: `2 passed in 20.96s`;
- Ruff changed files, `node --check`, `git diff --check`: green;
- short independent diff review: `Status: approved`; Ponytail — approved;
- CI выполняет полную regression suite.

## Dependency и риск

`geonamescache==3.0.2` выбран как единственный offline world-city dataset:
MIT, Python `>=3.10`, без runtime HTTP/API key; официальный wheel около 32 MB.
Данные поставляет dependency, собственный giant JSON в репозиторий не добавлен.
Это осознанная цена полного мирового списка; lookup ограничен auth, `q<=80` и
`limit<=10`, DTO не содержит координат/ID.
Точные дубликаты library records схлопываются детерминированно до search и
validation: `33 884` canonical labels равны `33 884` unique labels; collision
oracle для `Dondo` green.

Риск умеренный UI/integration без миграции данных. Non-owner/test-run scopes,
stale revisions и повторные mutations остаются fail-closed и идемпотентными.
