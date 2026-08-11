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
6. Установить unit/timer из `ops/systemd`, выполнить `systemctl daemon-reload`,
   `systemctl enable --now community-bot-backup.timer`.
7. Создать первый backup и выполнить restore drill до допуска участников.

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

## Preflight допуска когорты

1. Зафиксировать reviewed commit и immutable image digest текущего release.
2. Подтвердить `0010`, healthy `postgres`, `community-worker` и `community-bot`,
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
