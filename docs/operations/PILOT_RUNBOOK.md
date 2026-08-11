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
   `DATABASE_URL`, `BOT_TOKEN`, случайным `INVITE_TOKEN_SECRET`, `ENVIRONMENT`,
   `RELEASE` и необязательным `SENTRY_DSN`.
4. Для штатного release выполнить
   `ops/deploy_self_hosted.sh GHCR_IMAGE@sha256:DIGEST`. Для первого bootstrap
   допустимо безопасно загрузить проверенный image archive и передать его точный
   локальный `sha256:IMAGE_ID`. Mutable tag production script отклоняет.
5. Скрипт последовательно запускает PostgreSQL, `community-migrate`, `worker`,
   проверяет его readiness, затем запускает `bot` и проверяет его readiness.
6. На действительно пустой базе создать первого администратора без ручного SQL:

   ```bash
   cd /opt/community-bot/current
   read -r -p "Telegram user ID первого администратора: " BOOTSTRAP_TELEGRAM_ID
   export COMMUNITY_BOT_IMAGE="$(</opt/community-bot/shared/releases/current-image)"
   export COMMUNITY_BOT_ENV_FILE=/opt/community-bot/shared/.env
   docker compose --project-directory /opt/community-bot/current \
     --env-file /opt/community-bot/shared/.env \
     -f compose.production.yaml run --rm migrate \
     community-bootstrap-admin \
     --telegram-user-id "${BOOTSTRAP_TELEGRAM_ID}" \
     --reason initial_install
   unset BOOTSTRAP_TELEGRAM_ID COMMUNITY_BOT_IMAGE COMMUNITY_BOT_ENV_FILE
   ```

   Code `0` означает создание либо точный идемпотентный повтор. Code `2` означает конфликт
   состояния или невалидный ввод: остановиться, проверить наличие администратора и audit, не
   выполнять ручной SQL. Code `1` означает техническую ошибку; после устранения причины команду
   можно безопасно повторить. Затем этот администратор открывает `/admin` и создаёт
   одноразовую ссылку кнопкой `Создать приглашение`; `/invite_create` остаётся резервной
   командой.
7. Установить unit/timer из `ops/systemd`, выполнить `systemctl daemon-reload`,
   `systemctl enable --now community-bot-backup.timer`.
8. Создать первый backup и выполнить restore drill до допуска участников.

При clean recovery на заново созданной пустой схеме используется та же команда с
`--reason clean_recovery`. После обычного восстановления backup, где active administrator уже
существует, bootstrap не запускается. Конфликт — это защитная остановка, а не повод обходить guard.

## Обычный выпуск

1. Дождаться зелёного CI на `main` и взять image reference из release artifact.
   Штатная identity имеет вид `ghcr.io/...@sha256:...`.
2. Выполнить `ops/deploy_self_hosted.sh IMAGE_REFERENCE` на сервере.
3. Убедиться, что `docker compose ps` показывает healthy `postgres`, `worker` и
   `bot`, а `migrate` завершился с code 0.
4. Проверить свежие логи каждого процесса и отсутствие terminal `failed` в
   outbox. Логи не должны содержать токены, connection string, Telegram payload,
   comments, evidence или materials.

## Частичный rollback

1. Прочитать предыдущую identity из
   `/opt/community-bot/shared/releases/previous-image`.
2. Запустить `ops/deploy_self_hosted.sh PREVIOUS_IMAGE`.
3. Не выполнять автоматический Alembic downgrade. Release-миграции обязаны быть
   совместимы с предыдущим image.
4. Если предыдущий image несовместим с текущей схемой, остановить rollback и
   исправить схему новой forward migration.

## Backup и restore drill

Timer ежедневно запускает `ops/backup_postgres.sh`. Скрипт создаёт custom-format
`pg_dump` через временный файл, атомарно переименовывает готовый dump и удаляет
локальные backup старше семи суток. Каталог и файлы доступны только root.

Для drill выбрать свежий файл и выполнить:

```bash
/opt/community-bot/current/ops/restore_drill.sh \
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
- `migration_mismatch` — image и схема имеют разные Alembic revision;
- `outbox_failed` — событие исчерпало пять попыток; исправить причину и только
  затем документированно вернуть запись в `pending`;
- `telegram_temporarily_unavailable` — worker повторит с bounded backoff;
- `telegram_recipient_unavailable` — notification останется terminal `failed`.

Ручная правка доменного состояния запрещена. Перед повторным deploy или restore
нужно проверить текущее состояние и исключить частично выполненную операцию.
