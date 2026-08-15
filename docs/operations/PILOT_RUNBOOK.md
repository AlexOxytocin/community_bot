# Эксплуатация пилота Community Bot

## Назначение

Runbook описывает выпуск одного проверенного image на собственный сервер,
проверку `bot`/`worker`, rollback и восстановление PostgreSQL из локального
logical backup. External backup, R2, application object storage и webhook в MVP
не используются.

## Компоненты и пути

- `/opt/community-bot/current` — текущий deployment-пакет без секретов;
- `/opt/community-bot/shared/.env` — root-owned секреты и конфигурация `0600`;
- `/opt/community-bot/shared/releases` — текущая и предыдущая image identity;
- `/opt/community-bot/shared/bin/github_deploy_entrypoint.sh` — root-owned forced-command entrypoint `0700`;
- `/opt/community-bot/shared/bin/deploy_self_hosted.sh` — root-owned trusted deploy runner `0700`;
- `/var/backups/community-bot` — root-only backup с хранением семь суток;
- Compose services: `postgres`, `migrate`, `worker`, `bot`;
- systemd timer: `community-bot-backup.timer`.

Ни один контейнер Community Bot не публикует сетевой порт. Telegram работает
через исходящий long polling. Значения секретов не копируются в Jira, git, логи
или команды отчёта.

## Первый запуск

1. Убедиться, что Docker и Compose работают, а `/opt/community-bot` ещё не
   принадлежит другому приложению.
2. Создать `current`, `shared/releases` и `/var/backups/community-bot`; доступ к
   `shared` и backup разрешить только root.
3. Скопировать deployment-пакет в `current`. Создать `shared/.env` с
   `POSTGRES_DB`, `POSTGRES_USER`, случайным `POSTGRES_PASSWORD`, внутренним
   `DATABASE_URL`, `BOT_TOKEN`, случайным `INVITE_TOKEN_SECRET`, `ENVIRONMENT`
   и необязательным `SENTRY_DSN`. Штатный deploy переопределяет `RELEASE` уникальной
   identity `<digest>.run<run_number>.<run_attempt>`.
4. Для штатного release выполнить
   `ops/deploy_self_hosted.sh GHCR_IMAGE@sha256:DIGEST`. Для первого запуска пустой
   базы передать вторым аргументом Telegram user ID первого администратора:
   `ops/deploy_self_hosted.sh GHCR_IMAGE@sha256:DIGEST TELEGRAM_ID`. Скрипт после
   migrations создаст administrator, идемпотентно активирует packaged product config
   и только затем запустит worker/bot. Для первого bootstrap
   допустимо безопасно загрузить проверенный image archive и передать его точный
   локальный `sha256:IMAGE_ID`. Mutable tag production script отклоняет.
5. Скрипт последовательно запускает PostgreSQL, `community-migrate`, optional
   `community-bootstrap-admin`, обязательный `community-bootstrap-product-config`,
   `worker`, проверяет его readiness, затем запускает `bot` и проверяет readiness.
6. Code `0` bootstrap-команд означает создание либо точный идемпотентный повтор.
   Code `2` означает конфликт состояния или невалидный ввод: остановиться, проверить
   administrator/config/audit, не выполнять ручной SQL. Code `1` означает техническую
   ошибку; после устранения причины команду можно безопасно повторить. Затем
   администратор открывает `/admin` и создаёт
   одноразовую ссылку кнопкой `Создать приглашение`; `/invite_create` остаётся резервной
   командой.
   Если bootstrap administrator сохранил нейтральное либо повреждённое отображаемое имя,
   исправить его без ручного SQL, передав Telegram ID и новое имя двумя строками через stdin:
   `printf '%s\n%s\n' "$TELEGRAM_ID" "$DISPLAY_NAME" | docker compose run --rm -T migrate community-repair-bootstrap-admin-profile`.
   Приватные значения не попадают в process argv и Sentry `ArgvIntegration`. Команда применима только к единственному active
   administrator с bootstrap provenance, не меняет остальные поля и безопасна при повторе.
   Значение имени и Telegram ID не записываются в runtime logs и audit payload.
7. Установить unit/timer из `ops/systemd`, выполнить `systemctl daemon-reload`,
   `systemctl enable --now community-bot-backup.timer`.
8. Создать первый backup и выполнить restore drill до допуска участников.

При clean recovery на заново созданной пустой схеме перед запуском deploy установить
`COMMUNITY_BOT_BOOTSTRAP_REASON=clean_recovery` и передать Telegram ID вторым аргументом.
После обычного восстановления backup, где active administrator и active config уже
существуют, второй аргумент не передаётся; config bootstrap возвращает идемпотентный
success. Конфликт — защитная остановка, а не повод обходить guard.

## Обычный выпуск

1. Дождаться трёх обязательных PR checks: `Quality`, `PostgreSQL and Alembic` и
   `Verified merge tree`.
2. После merge workflow `Release image` доказывает совпадение PR/base/head/tree и
   собирает linux/arm64 image actual merge commit. Привилегированный deploy job ожидает
   подтверждения владельца в Environment `production`, затем передает immutable digest
   forced-command entrypoint. Ручной SSH для штатного выпуска не требуется.
3. Убедиться, что `docker compose ps` показывает healthy `postgres`, `worker` и
   `bot`, а `migrate` завершился с code 0.
4. Проверить, что worker и bot были принудительно пересозданы, а `community-health`
   принял heartbeat каждого процесса с release текущего digest и временем не раньше
   его post-recreate порога.
5. Проверить свежие логи каждого процесса и отсутствие terminal `failed` в
   outbox. Логи не должны содержать токены, connection string, Telegram payload,
   comments, evidence или materials.

## Первичная настройка GitHub deployment

Это отдельное контролируемое операционное событие. Оно выполняется один раз и при
ротации ключа; приватный ключ и host key не выводятся в Jira, git или отчёт.

1. Создать отдельную пару SSH-ключей только для GitHub Actions. Не использовать личный
   ключ оператора.
2. Установить `ops/github_deploy_entrypoint.sh` и `ops/deploy_self_hosted.sh` как
   `/opt/community-bot/shared/bin/github_deploy_entrypoint.sh` и
   `/opt/community-bot/shared/bin/deploy_self_hosted.sh`. Каталоги `shared`/`shared/bin`
   и оба файла должны принадлежать `root:root`, иметь mode `0700` и не быть symlink.
   `/opt/community-bot` должен принадлежать root и не иметь group/other write. Forced
   entrypoint fail-closed перепроверяет этот контракт перед каждым deploy.
3. Добавить public key в `/root/.ssh/authorized_keys` одной строкой с префиксом
   `restrict,command="/opt/community-bot/shared/bin/github_deploy_entrypoint.sh"`.
4. Локально проверить, что точная parser-only команда принимается, а mutable tag,
   другой repository, лишний аргумент, перенос строки и shell-разделитель отклоняются.
5. Создать защищенное Environment `production` с владельцем как required reviewer. В его
   secrets записать `PRODUCTION_HOST`, новый
   `PRODUCTION_SSH_PRIVATE_KEY` и заранее проверенную строку
   `PRODUCTION_KNOWN_HOSTS`. Workflow использует `StrictHostKeyChecking=yes`; получать
   host key динамическим `ssh-keyscan` внутри release запрещено.
6. `CODEOWNERS` делает изменения privileged release surfaces видимыми владельцу;
   независимую runtime-границу обеспечивает обязательное Environment approval.
7. Включить protection `main`: PR обязателен, strict checks актуальной базы, три checks
   привязаны к GitHub Actions App, enforce administrators, запрет bypass/force push/
   deletion. Оставить только merge commits; squash и rebase выключить.
8. Только после подтверждения protection удалить повторный полный CI на `push main`.

Forced command принимает только:

```text
deploy RUN_NUMBER RUN_ATTEMPT COMMIT_SHA ghcr.io/alexgoodman53/community_bot@sha256:DIGEST
```

Entrypoint сериализует deploy через `flock` и принимает только возрастающую пару
`RUN_NUMBER/RUN_ATTEMPT` одного workflow. Marker обновляется после успешного deploy.

## Release acceptance в Telegram

Для заявления «исправлено на рабочем экземпляре» после deployment выполнить
живую проверку через опубликованный `bot`. Если сценарий требует двух
пользователей, использовать локальные профили `default` и `tg-test`.

Сначала проверить доступность сессий без чтения сообщений:

```powershell
& 'C:\Users\User\.codex\tools\telegram.ps1' probe
& 'C:\Users\User\.codex\tools\telegram.ps1' -Profile tg-test probe
```

В отчёте фиксировать только дату, ярлык профиля и факт
`ok/authorized/dialogsProbeOk`. Не фиксировать session string, телефон,
Telegram ID, список чатов, тексты сообщений, callback payload, invite-коды,
evidence или медиа. Чтение чата с ботом, нажатие live-кнопок и отправка
сообщений выполняются только по явному запросу пользователя на конкретный
release acceptance сценарий.

До начала реальной эксплуатации владелец разрешил полный live smoke через
профили `default` и `tg-test`. Перед действиями открыть изолированный scope:

```powershell
uv run python ops/smoke_production.py `
  --server USER@HOST `
  begin TEST-RELEASE-UNIQUE01
```

После сценариев отменить пользовательские тестовые сущности через интерфейс, затем
автоматически закрыть свободные community-карточки и проверить блокеры:

```powershell
uv run python ops/smoke_production.py --server USER@HOST cleanup TEST-RELEASE-UNIQUE01
uv run python ops/smoke_production.py --server USER@HOST status TEST-RELEASE-UNIQUE01
uv run python ops/smoke_production.py --server USER@HOST finish TEST-RELEASE-UNIQUE01
```

`cleanup` отменяет только опубликованные community-карточки без активных назначений.
Черновики и активные назначения остаются блокерами: их нужно завершить или отменить
через проверяемый пользовательский сценарий.

После этого участники scope видят только карточки текущего запуска, а остальные
пользователи не видят их и не получают уведомления. Все создаваемые карточки
имеют видимый маркер `ТЕСТ`. Smoke вправе создавать, принимать, подтверждать,
отменять и закрывать карточки, если это требуется критериями release.

Незавершённые черновики удалить через `/cancel` или `/task_cancel`. Опубликованные
tasks и assignments привести в терминальные состояния штатными callback и
командами. Затем закрыть scope:

```powershell
uv run python ops/smoke_production.py `
  --server USER@HOST `
  finish TEST-RELEASE-UNIQUE01
```

`finish` обязан завершиться ошибкой, если остались nonterminal drafts, tasks или
assignments. В таком случае smoke считается непройденным до штатной очистки.
Telegram ID, session string, сообщения и callback payload в отчёт не включать.

## Частичный rollback

1. Прочитать предыдущую identity из
   `/opt/community-bot/shared/releases/previous-image`.
2. Запустить
   `python3 /opt/community-bot/current/ops/deploy_self_hosted.py PREVIOUS_IMAGE`.
3. Не выполнять автоматический Alembic downgrade. Release-миграции обязаны быть
   совместимы с предыдущим image.
4. Если предыдущий image несовместим с текущей схемой, остановить rollback и
   исправить схему новой forward migration.

## Backup и restore drill

Timer ежедневно запускает `ops/backup_postgres.py`. Скрипт создаёт custom-format
`pg_dump` через временный файл, атомарно переименовывает готовый dump и удаляет
локальные backup старше семи суток. Каталог и файлы доступны только root.

Для drill выбрать свежий файл и выполнить:

```bash
python3 /opt/community-bot/current/ops/restore_drill.py \
  /var/backups/community-bot/community_bot-YYYYMMDDTHHMMSSZ.dump
```

Скрипт создаёт отдельную `community_bot_restore_drill`, восстанавливает backup,
проверяет `alembic_version` и доступность ключевых таблиц, затем удаляет только
временную БД. Рабочая БД и контейнеры не переключаются.

В несекретном операционном отчёте фиксируются UTC-время backup, начало и конец
restore, Alembic revision и результат проверок. Цели логического восстановления:
`RPO <= 24h`, `RTO <= 4h`. Backup находится на том же сервере и не защищает от
полной потери хоста; этот риск принят для MVP.

## Диагностика

- `heartbeat_stale` — процесс не обновлялся дольше настроенного предела;
- `heartbeat_release_mismatch` — heartbeat принадлежит другому image release;
- `heartbeat_before_deploy` — heartbeat создан до начала текущего deployment;
- `migration_mismatch` — image и схема имеют разные Alembic revision;
- `outbox_failed` — событие исчерпало пять попыток; исправить причину и только
  затем документированно вернуть запись в `pending`;
- `telegram_temporarily_unavailable` — worker повторит с bounded backoff;
- `telegram_recipient_unavailable` — notification останется terminal `failed`.

Ручная правка доменного состояния запрещена. Перед повторным deploy или restore
нужно проверить текущее состояние и исключить частично выполненную операцию.

## Preflight допуска когорты

1. Зафиксировать reviewed commit и immutable image digest текущего release.
2. Подтвердить `0019`, healthy `postgres`, `community-worker` и `community-bot`,
   отсутствие terminal `failed` outbox и свежие heartbeat.
3. Создать свежий backup, выполнить isolated restore drill и получить
   `ledger_mismatch_count = 0`; возраст backup должен быть не более 24 часов, а
   длительность восстановления — менее 4 часов.
4. Получить агрегированный отчёт за выбранный UTC-период командой
   `community-pilot-report --from ... --to ...`. Отчёт не содержит имён,
   Telegram ID, UUID участников или приватных текстов.
5. Проверить, что JQL по label `cb16-regression` не содержит открытых critical
   или high дефектов, блокирующих пилот.
6. Не добавлять участников, пока любой пункт выше не подтверждён.

## Ежедневный контроль

Использовать [PILOT_CHECKLIST.md](PILOT_CHECKLIST.md). Проверка выполняется один
раз в рабочий день владельца и после инцидента. Фиксируются только агрегаты и
технические коды без пользовательских payload, комментариев и доказательств.

Нормальное решение — `continue`. `pause` означает временно не приглашать новых
участников и не публиковать задания сообщества до разбора. `stop` останавливает
bot/worker после сохранения backup и снимка несекретных доказательств; PostgreSQL
не удаляется и Alembic downgrade не выполняется.

## Условия немедленной остановки

- потеря или некорректное удвоение кредитов;
- раскрытие raw-кармы или приватных административных данных;
- получение чужих административных прав;
- массовый фарм, который нельзя локализовать действующими правилами;
- необратимая потеря заданий или результатов;
- backup не восстанавливается либо restored ledger расходится с кэшами.

При остановке: запретить новые входы, сохранить свежий logical backup, записать
release и UTC-время, открыть Jira Bug, оценить необходимость rollback на
`previous-image`. Возобновление требует закрытого blocker, успешного targeted
gate, нового restore drill и явного решения владельца.

## Еженедельные метрики и завершение пилота

Недельные отчёты используют соседние UTC-полуинтервалы без пересечения. Через
4–6 недель заполнить [PILOT_RETROSPECTIVE.md](PILOT_RETROSPECTIVE.md), сравнить
`task_fill_rate >= 0.7000`, `assignment_completion_rate >= 0.7500` и
`repeat_action_rate >= 0.6000`, перечислить инциденты и принять решение
`continue|change|stop`. Шаблон не заполняется прогнозами до появления фактов.

После завершения когорты остановить новые приглашения, выгрузить последний
агрегированный отчёт, закрыть ручные решения и алерты, выполнить backup/restore
drill и сохранить только несекретную ретроспективу. Доменные журналы не
редактируются и не удаляются ради «чистого» отчёта.
