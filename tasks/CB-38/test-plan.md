# CB-38 - план проверки

## Статические и локальные контракты

- `.github/workflows/ci.yml` запускает полный контур только на PR и создает checks
  `Quality`, `PostgreSQL and Alembic`, `Verified merge tree`.
- Артефакт `verified-merge-tree` содержит repository, PR number, base/head SHA,
  synthetic merge SHA/tree SHA и CI workflow/run identity.
- Release запускается только на push в `main`, требует ровно один merged PR для exact
  merge SHA и ровно один непросроченный provenance artifact успешного CI run, связанный
  с этим PR/head SHA. Base/head должны совпасть с parents merge commit, все поля и tree
  SHA должны совпасть; любое отсутствие или неоднозначность завершает работу до build.
- Release публикует linux/arm64 image по immutable digest и передает deploy job только
  run number/attempt, commit SHA и digest; job защищен Environment `production`.
- Forced-command entrypoint принимает только точный контракт
  `deploy <run_number> <run_attempt> <40 hex> ghcr.io/alexgoodman53/community_bot@sha256:<64 hex>`.
- Негативные тесты отклоняют mutable tag, иной repository, лишний аргумент, перевод
  строки, `;`, `&&`, command substitution, нечисловую или устаревшую пару run
  number/attempt.
- Entrypoint использует фиксированный `PATH`, не использует `eval`, берет команду только
  из `SSH_ORIGINAL_COMMAND`, сериализует deploy через `flock` и обновляет marker только
  после успеха.
- Entrypoint запускает только `/opt/community-bot/shared/bin/deploy_self_hosted.sh` и
  отклоняет файл или родительский trusted directory не `root:root 0700`, включая `0777`.
- Deploy задает identity `<digest>.run<run_number>.<run_attempt>` и принудительно
  пересоздает worker/bot; readiness отклоняет несовпадающую identity и heartbeat старше
  отдельного наносекундного post-recreate порога процесса.
- `compose.production.yaml` передает один ожидаемый `RELEASE` в migrate, worker и bot.
- Процессные документы и `agents/workflow.yaml` одинаково описывают standing intent и
  его ограничения.

Команды:

- `bash -n ops/deploy_self_hosted.sh ops/github_deploy_entrypoint.sh`.
- `uv run pytest tests/unit/test_operations.py tests/unit/test_runtime_operations.py`.
- `uv run pytest tests/integration/test_notifications.py`.
- Целевые тесты workflow/deploy contracts.
- `uv run ruff format --check` и `uv run ruff check` измененных Python-файлов.
- `uv run ty check` при изменении Python.
- YAML parse всех измененных workflow/config файлов.
- `git diff --check` и diff secret scan.

## Настройка внешних gates

- Branch protection подтверждается через GitHub API: pull request required, strict
  status checks, `Quality`, `PostgreSQL and Alembic`, `Verified merge tree`, checks
  привязаны к GitHub Actions App, enforce admins, запрет force push/deletion и отсутствие
  bypass actors.
- Настройки merge подтверждают: merge commit включен, squash и rebase выключены.
- Deploy key новый и отдельный; GitHub secrets существуют, но значения не выводятся.
- Deploy secrets находятся в Environment `production`; required reviewer подтверждает
  только привилегированный deploy job после публикации проверенного digest.
- Workflow подключается пользователем `root` с `StrictHostKeyChecking=yes` и pinned
  `known_hosts`; в workflow отсутствует `ssh-keyscan`.
- На сервере public key находится в `/root/.ssh/authorized_keys` и имеет
  `restrict,command=...`; entrypoint принадлежит `root:root`, имеет mode `0700`;
  негативный SSH-вызов отклоняется без запуска deploy.

## Release acceptance

- PR получает три обязательных зеленых check.
- Merge выполняется merge commit; release доказывает равенство tested tree и main tree.
- Перед deploy workflow подтверждает, что commit остается текущим `main`.
- Более старая или равная пара run number/attempt отклоняется server-side.
- Production deploy завершает migration, product config, expected-release heartbeat,
  bot identity и failed-outbox gates.
- Фактический runtime digest совпадает с опубликованным release digest.

## Telegram acceptance

Preflight: `default` и `tg-test` отвечают на safe probe без чтения сообщений. В артефакт
попадают только ярлыки профилей и результат probe.

Сценарий 1:

1. `default` создает явно помеченное тестовое задание.
2. `tg-test` берет задание.
3. `default` отправляет запрос отмены.
4. `tg-test` отклоняет отмену.
5. Оба интерфейса подтверждают, что задание осталось активным и исполнитель сохранен.

Сценарий 2:

1. `default` создает второе тестовое задание и фиксирует доступный баланс через UI.
2. `tg-test` берет задание.
3. `default` отправляет запрос отмены.
4. `tg-test` подтверждает отмену.
5. Оба интерфейса подтверждают отмененный статус; баланс заказчика увеличился ровно на
   размер резерва один раз.
6. Повторный callback не меняет статус и баланс.

Cleanup: оба тестовых задания удаляются или отменяются штатным интерфейсом; проверяется,
что активных тестовых заданий не осталось. В Jira и git фиксируются только роли,
результаты шагов, release digest и время проверки без Telegram payload и идентификаторов.
