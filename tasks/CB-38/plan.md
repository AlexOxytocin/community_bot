# CB-38 - план ускорения приемки

## Уровень риска

Уровень 3. Изменение затрагивает GitHub branch protection, CI, публикацию image,
production deployment и правила внешних действий агента.

## Цель

Убрать повторные ожидания из малых багфиксов, сохранив один полный CI-контур,
immutable release, readiness/migration/outbox gates и живую Telegram-приемку.

## Изменения

1. Завершить процессный fast lane `1B`: compact bugfix note ведется в задаче, но не
   останавливает реализацию; отдельные план, отчет, тяжелое final review и полная
   локальная регрессия для `1B` не создаются.
2. Синхронно закрепить в guardrails, Jira workflow, agent workflow и машинной
   конфигурации постоянное намерение владельца: прямое поручение исправить или
   реализовать задачу разрешает стандартную недеструктивную цепочку Jira -> branch ->
   PR -> merge после обязательных checks -> release -> deploy. Остановка обязательна
   при конфликте, повышении риска, неуспешном gate, разрушительном действии или прямой
   команде владельца остановиться. Разрешение не распространяется на произвольное
   чтение/отправку Telegram-сообщений и финальный `Done` без production acceptance.
3. Выполнять полный CI только на `pull_request`. Добавить итоговый check
   `Verified merge tree`, который после `Quality` и `PostgreSQL and Alembic` сохраняет
   repository, PR number, base SHA, head SHA, synthetic merge SHA и tree SHA проверенного
   synthetic merge commit, а также identity CI workflow/run без пользовательских данных.
4. До отключения CI на `main` включить branch protection: pull request обязателен,
   ветка должна быть актуальна, обязательны `Quality`, `PostgreSQL and Alembic` и
   `Verified merge tree`, каждый check привязан к GitHub Actions App, правила действуют
   для администраторов, force push, deletion и bypass запрещены. В репозитории оставить
   только merge commits.
5. Перевести release на `push` защищенного `main`. Workflow требует ровно один merged PR,
   у которого `merge_commit_sha == github.sha`, `base.ref == main`, а parents фактического
   merge commit точно равны сохраненным base/head SHA. Среди успешных CI runs этого PR и
   head SHA допускается ровно один непросроченный provenance artifact, все поля которого
   совпадают; отсутствие, неоднозначность, старая версия PR или несовпадение tree SHA
   fail-closed запрещают build. Только после этого собирается linux/arm64 image actual
   merge commit и публикуется immutable digest.
6. Перед deploy повторно подтвердить, что `github.sha` остается текущим `main`.
   Deploy job использует защищенное Environment `production` с подтверждением владельца,
   затем подключается как `root` с `StrictHostKeyChecking=yes` и отдельным заранее
   доверенным pinned `known_hosts`; динамический `ssh-keyscan` запрещен. Forced-command
   entrypoint получает только `deploy <run_number> <run_attempt> <commit_sha> <image>`.
7. Создать отдельный deploy key и установить public key только в
   `/root/.ssh/authorized_keys`. Server-owned entrypoint размещается по фиксированному
   пути с владельцем `root:root`, режимом `0700`, фиксированным `PATH`, без `eval` и с
   точной проверкой `SSH_ORIGINAL_COMMAND`. `authorized_keys` использует
   `restrict,command=...`. Допускаются только числовые run number/attempt, 40-символьный
   commit SHA и digest репозитория `ghcr.io/alexgoodman53/community_bot`; дополнительные
   аргументы, теги, другой репозиторий, переносы строк и shell-разделители отклоняются.
8. Server entrypoint сериализует deployment через `flock` и сравнивает лексикографическую
   пару `(GITHUB_RUN_NUMBER, GITHUB_RUN_ATTEMPT)` одного неизменяемого workflow
   `.github/workflows/release.yml` с marker последнего успешного deploy. Меньшая или
   равная пара отклоняется, marker обновляется только после успеха. Это не дает старому
   workflow или старому rerun затереть более новый release.
9. Передавать в migrate, worker и bot уникальную deployment identity
   `<digest>.run<run_number>.<run_attempt>`. Deploy принудительно пересоздает worker и bot
   и отдельно фиксирует наносекундный порог после остановки прежнего экземпляра каждого
   сервиса. Readiness требует эту identity и heartbeat не старше порога, поэтому прежний
   контейнер или запуск того же digest не закрывает gate.
10. Добавить безопасный preflight двух Telegram-профилей без чтения сообщений и
    сохранения приватных идентификаторов. После production deploy выполнить два
    сценария отмены задания между профилями `default` и `tg-test` и удалить тестовые
    задания штатным интерфейсом.
11. Обновить runbook, тесты операционных контрактов и инструкции первичной настройки.

## Границы безопасности

- GitHub Actions не получает существующий пользовательский/root SSH key; новый ключ
  ограничен forced command, а server host проверяется по заранее pinned host key.
- Workflow передает только immutable image ожидаемого GHCR repository.
- Неуспешный deploy виден и не переводит Jira в `Done`.
- Обновление server-owned entrypoint выполняется отдельной контролируемой установкой.
- Telegram session strings, телефоны, Telegram ID, списки чатов и тексты сообщений не
  сохраняются в git, Jira или CI artifacts.
- Автоматический rollback не выполняется при несовместимой схеме; остается штатный
  ручной rollback по runbook.

## Проверка

- YAML parse, shell syntax и целевые unit/integration-тесты операционных контрактов.
- Положительные и отрицательные тесты forced-command parser и монотонности пары
  run number/attempt.
- `ruff`, `ty`, targeted pytest, `git diff --check` и secret scan.
- Независимая проверка плана и финальная проверка уровня 3.
- Реальная branch protection до отключения `push main` CI.
- PR CI и однозначное доказательство PR/base/head/merge/tree provenance.
- Release run, immutable digest, approval защищенного Environment и production deploy.
- Production health подтверждает database, migration, product config, expected-release
  heartbeat и отсутствие terminal failed outbox.
- Safe probe профилей `default` и `tg-test`, затем живые сценарии после deploy:
  исполнитель отклоняет запрос отмены и задание остается активным; в отдельном задании
  исполнитель подтверждает отмену, задание отменяется, а резерв возвращается один раз.

## Не входит

- Автоматизация произвольных сообщений или чтения личных чатов.
- Ослабление проверок экономики, миграций, прав, приватности, outbox и конкурентных
  операций.
- Автоматический rollback при несовместимой схеме.
