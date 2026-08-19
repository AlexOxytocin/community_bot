# План CB-83

## Цель и уровень процесса

Дать создателю увидеть собственные опубликованные задания, lifecycle status, заполнение слотов и состояния исполнителей в уже существующем экране «Созданные мной». Уровень 2: небольшой read-only Web slice без новых доменных правил, данных, схемы или интеграций.

## Read-only mapping текущего Mini App

| Пользовательский путь | Web API | Существующий application owner | Фактический разрыв |
|---|---|---|---|
| Каталог, карточка и принятие задания | `GET /api/v1/tasks`, `POST /api/v1/tasks/{id}/assignments` | `TaskService.list_available`, `AssignmentService.accept_with_task` | Основной путь есть |
| Free-form личное/групповое задание | `GET/POST /api/v1/task-creation` | `TaskService.web_state`, `start`, `save_web_draft`, `preview`, `publish` | Создание есть |
| Собственные созданные задания | Нет | `TaskService.list_owned_cards` → `list_owned_task_cards` | Ключевой разрыв: UI «Созданные мной» показывает только ожидающие review результаты и пуст до первой сдачи |
| Активные назначения, сдача результата | `GET /api/v1/assignments...`, submission draft endpoints | `AssignmentService.active_cards`, `active_card`, `begin_submission`, `save_submission_draft`, `confirm_submission_draft` | Есть |
| Проверка результата создателем | `GET/POST /api/v1/assignment-reviews...` | `AssignmentService.creator_review_cards`, `decide` | Есть, путь нужно сохранить в том же экране |
| Свой профиль, баланс и уровень | `GET /api/v1/me`, `PUT /api/v1/me/profile` | `RegistrationService.own_profile`, `update_own_profile_field` | Есть |
| Поиск/профиль участника, карма | `GET /api/v1/members...`, karma vote endpoint | `ReputationService.members`, `profile`, karma draft commands | Есть |
| Рейтинг и надёжность | `GET /api/v1/leaderboard` | `ReputationService.leaderboard` | Есть |
| Первичный спор/модерация | moderation endpoints | `ModerationService.queue`, `detail`, `resolve` | Есть; CB-76—CB-80 исключены |
| Templates/community publication | Нет полного Web пути | Существующие catalog/task commands | Не выбран: требует дополнительных состояний и более широкого UI |

## Выбранный 80/20 путь

После публикации создатель сейчас не может увидеть своё задание до появления результата на проверку. Это разрывает основной цикл сразу после уже работающего создания. Существующий `OwnedTaskCard` уже содержит задание, assignees и cancellation status, а repository query уже задаёт ownership/test-run/query semantics.

Тонкий actor-native seam в `TaskService` только:

- получает server-issued `ActorContext`;
- разрешает существующего active member через `_active_context_actor`;
- вызывает существующий `list_owned_task_cards` с `creator_id=actor.member_id` и существующим `creator_only=True`;
- не принимает client identity и не добавляет правил или query semantics.

Pagination отклонена как самостоятельная продуктовая задача: дешёвый diff не закрывает основной пользовательский разрыв. Mutation, detail screen, cancellation, templates/community workflow и CB-76—CB-80 не входят.

## Изменения

1. `src/community_bot/application/tasks.py`: один actor-native read seam над существующим owner/query, без нового service или repository.
2. `src/community_bot/transport/web.py`: один read-only endpoint и компактные DTO для existing `OwnedTaskCard`; owner берётся только из Web session.
3. `src/community_bot/transport/static/app.js`: текущий экран «Созданные мной» загружает owned cards и существующие assignment reviews, показывает две небольшие секции и сохраняет текущий review action.
4. `tests/integration/test_web_api.py`: один API oracle доказывает creator-only scope, server-owned actor, отсутствие foreign/reviewer-only rows и точную проекцию assignees/status.
5. `tests/browser/test_mini_app.py`: один happy path доказывает, что до первой сдачи собственное задание видно, а существующий переход к review остаётся доступен.
6. `tests/unit/test_web_auth.py`: закрытый allowlist Web routes принимает ровно новый `GET /api/v1/owned-tasks` и сохраняет fail-closed контракт.

## Проверка и stop gate

- targeted integration API oracle и один browser happy path;
- `ruff format --check`, `ruff check`, `ty check` для области;
- `git diff --check`, secret scan и контрольный повтор тестов;
- Ponytail review: допустим только описанный thin read method в существующем `TaskService`; без нового service/class, domain/schema/model/repository/query-semantics/dependency/framework/CSS changes и без второго экрана.

Production file count: **3**. Production/test file count: **6**. Ожидаемый net diff: **189–230 additions**, до 30 deletions. Шесть файлов независимо подтверждены ceiling review: seam, HTTP adapter и UI являются тремя разными production owners; поручение отдельно требует backend/API oracle и browser oracle; шестой файл — обязательный закрытый route allowlist, который нельзя ослаблять или обходить через семантически чужой endpoint. Если реализация потребует седьмой production/test файл, более 250 net additions или изменение существующих query semantics, работа останавливается до нового review.

## Delivery

После fresh independent plan `Status: approved`: ветка `task/CB-83`, реализация, implementation report, independent final review, commit/push/PR/green CI/merge, новый immutable release, production activation, public smoke экрана «Созданные мной» и только затем Jira `Done`.
