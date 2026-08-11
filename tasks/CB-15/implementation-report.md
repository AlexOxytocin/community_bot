# CB-15 — отчёт о реализации

## Результат

Полная область CB-15 реализована и развёрнута на выбранном владельцем собственном
сервере. В отдельном production Compose project работают PostgreSQL 18, `worker`
и Telegram `bot`; оба процесса проходят readiness, миграция находится на `0010`,
новые публичные порты не открыты. Настоящий Bot API token хранится только в
root-owned environment file с правами `0600`.

Реальный backup создан на сервере, а его восстановление в отдельную временную БД
прошло за одну секунду. Ежедневный systemd timer включён; локальные dump-файлы
хранятся семь суток. External backup, R2, application object storage и webhook по
решению владельца не добавлялись.

## Реализованное поведение

- миграция `0010` расширяет `outbox_events` и создаёт `notifications` и
  `process_heartbeats` с DB constraints и due indexes;
- два worker используют `FOR UPDATE SKIP LOCKED`, получают непересекающиеся claim
  и завершают работу только по актуальному lease token;
- временная ошибка использует детерминированный bounded backoff, permanent error
  и пятая попытка дают terminal `failed`;
- событие без активного получателя корректно становится `materialized` с нулём
  notifications и не создаёт ложный poison;
- deadline reminder адресуется исполнителю, review reminders 24h/48h — автору
  member-task либо независимым активным администраторам community-task;
- terminal assignment/task повторно проверяется перед claim, поэтому устаревший
  reminder сохраняется как `notification_obsolete`, но не отправляется;
- participant-local окно по умолчанию `[09:00,21:00)` использует IANA timezone,
  учитывает DST и не переносит reminder позже доменного deadline;
- payload строится по allowlist; recursive scrubber удаляет credential-shaped
  строки, секреты, материалы, комментарии и evidence, а Sentry дополнительно не
  экспортирует request/user/message/exception value и breadcrumb text;
- `community-bot`, `community-worker`, `community-migrate` и `community-health`
  являются рабочими entrypoint;
- production release использует один immutable `linux/arm64` image под архитектуру
  пилотного сервера и порядок `migration → worker readiness → bot readiness`;
- PostgreSQL доступен только во внутренней Compose-сети, а `bot` и `worker`
  получают отдельный egress без входящего HTTP;
- deployment принимает GHCR digest штатного release либо точный локальный image
  ID для первоначальной загрузки и fail-closed отклоняет mutable tags;
- backup и restore scripts проверяют root ownership, режим `0600`, image identity
  и восстанавливают собственный Compose context без интерактивного shell.

## Фактическое развёртывание

- production host: Ubuntu 24.04, Docker 29 / Compose 5, архитектура `arm64`;
- immutable bootstrap image:
  `sha256:7ece0a3f3ad3cddbda72b75feb30b723d756a5e3d16ea30f16c2482c01ea8c99`;
- PostgreSQL 18 healthy, migration gate `0010` успешен;
- `community-worker` и `community-bot` healthy, restart count после успешного
  запуска равен нулю; в runtime-логах нет error/exception/traceback markers;
- Telegram `getMe` прошёл успешно для настроенного бота;
- backup `community_bot-20260811T123521Z.dump`: root-owned `0600`, 146626 bytes;
- isolated restore drill: `2026-08-11T12:35:32Z` — `12:35:33Z`, одна секунда,
  revision `0010`, обязательные таблицы прочитаны, временная БД удалена;
- `community-bot-backup.timer` enabled/active, следующий запуск назначен на
  `2026-08-12 03:29:14 UTC`;
- фактические цели: `RPO <= 24h`, `RTO <= 4h`; первый измеренный RTO — одна
  секунда для текущего пустого пилотного набора.

Первая неуспешная инициализация выявила две инфраструктурные несовместимости,
которые исправлены внутри реализации CB-15: PostgreSQL 18 требует mount
`/var/lib/postgresql`, а фактический сервер использует `arm64`. Созданные только
этой попыткой пустые container/volume были удалены и пересозданы; существующие
приложения, reverse proxy и firewall сервера не менялись.

## GitHub

- репозиторий `alexgoodman53/community_bot` подключён к аккаунту владельца;
- GitHub Actions разрешены, а browser-настройка «требовать полный commit SHA для
  actions» включена; все `uses:` уже закреплены полными SHA;
- release workflow после зелёного CI в `main` публикует `linux/arm64` image в GHCR
  через scoped `GITHUB_TOKEN` с `packages: write` и сохраняет immutable digest в
  artifact на 30 суток;
- глобальные workflow permissions оставлены read-only; конкретный release получает
  только явно описанные в YAML `contents: read` и `packages: write`;
- первоначальный deploy не зависит от персонального package token: точный ARM64
  image ID был безопасно загружен непосредственно на host. Следующие штатные
  releases используют GHCR digest из GitHub Actions.

## Документация

- принят ADR-0009, заменяющий hosting/release/backup часть ADR-0008;
- `docs/mvp/06_DATA_MODEL.md` синхронизирован с migration `0010`;
- `README.md` описывает рабочие runtime entrypoint и notification state;
- `docs/operations/PILOT_RUNBOOK.md` фиксирует первый запуск, обычный выпуск,
  partial rollback, readiness, backup и isolated restore drill;
- `.env.example` содержит только безопасные пустые/default настройки.

## Выполненные проверки

- Ruff format/check и `ty check src tests` — успешно;
- базовый целевой unit/smoke/integration контур CB-15 — `48 passed`, без
  skip/deselect; после final-review усиленный privacy-контур — `4 passed`;
- PostgreSQL 18 migration cycle и Testcontainers notification-контур — успешно;
- `uv build`, четыре runtime entrypoint и production Compose contract — успешно;
- production migration, worker readiness, bot readiness, Telegram API, backup и
  restore выполнены на реальном сервере;
- `git diff --check`, link scan и secret scan — успешно;
- полная продуктовая регрессия намеренно остаётся отдельной задачей CB-16.

## Соответствие Jira

| Критерий | Результат | Доказательство |
|---|---|---|
| AC1: временная ошибка | Готово | bounded DB retry и targeted tests |
| AC2: сохранённый успех не повторяется | Готово | due predicate и restart test |
| AC3: два worker | Готово | PostgreSQL `SKIP LOCKED` concurrency test |
| AC4: timezone | Готово | boundary, DST и deadline tests |
| AC5: restart | Готово | fresh/expired lease и stale-token tests |
| AC6: health | Готово | реальные worker/bot readiness на host |
| AC7: backup restore | Готово | реальный dump и isolated restore за 1 секунду |
| AC8: безопасные логи/errors | Готово | scrubber/Sentry tests и чистые runtime markers |

## Следующий шаг

После независимого final review: commit, pull request, CI, merge в `main` и перевод
CB-15 в `Готово`. Полная продуктовая регрессия выполняется затем строго в CB-16.
