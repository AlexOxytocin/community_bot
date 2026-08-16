# CB-59 — контекст и источники плана

## Jira

- **CB-59:** «Подготовить воспроизводимый release-кандидат Community Bot
  1.0.0», статус `В работе`, тип `Задание`, родитель CB-48.
- **Причина CB-59:** CB-50 plan review обнаружил blocking drift между
  production/repository head `0020`, hardcoded restore expectation `0019` и
  package version `0.1.0`.
- **Связь:** CB-59 блокирует CB-50. CB-50, в свою очередь, должен завершить
  production/recovery/Telegram acceptance, tag и GitHub Release до допуска
  CB-51.
- **CB-50:** «Зафиксировать и выпустить Community Bot Release 1», статус
  `В работе`; release candidate может быть выбран только после merge CB-59.
- **CB-48:** эпик Release 2. CB-59 является подготовительным blocker и не
  реализует Mini App/runtime R2.
- **Решение владельца:** выполнять согласованную параллельную программу и
  доводить задачи через проверки, PR и merge. Оно не расширяет CB-59 до deploy,
  tag или Telegram live действий.

## Жизненный цикл независимого ревью CB-50

Исторический первый verdict CB-50 имел `Status: changes_requested`. Именно он
обнаружил циклический порядок release acceptance и выделил version/restore
подготовку в самостоятельную блокирующую CB-59. Его относящиеся к CB-59
замечания были:

- version/restore preparation нужно вынести в отдельную complete workflow
  задачу до release acceptance CB-50;
- expected head должен извлекаться из того же immutable image;
- обязательны отдельные случаи zero/multiple image heads;
- production и restored `alembic_version` должны раздельно проверять zero,
  multiple, wrong и exact-one expected rows;
- ledger mismatch, restore error, cleanup error и фактическое отсутствие drill
  DB должны иметь наблюдаемое fail-closed доказательство;
- simple update `0019 → 0020` недостаточен.

После консолидированного исправления CB-50 прошла повторное ревью. Актуальный
файл
`C:/Users/User/community_bot-worktrees/CB-50/tasks/CB-50/plan-review.md`
полностью прочитан и сейчас имеет точный `Status: approved`. Он подтверждает,
что пять замечаний первого verdict закрыты, CB-59 является фактическим blocker
для CB-50 и единолично владеет package version, single-head restore contract,
operational docs, тестами и собственным PR/CI/merge. Актуальный approved verdict
не снимает dependency: CB-50 запрещено выбирать candidate и выполнять release
acceptance до завершения и merge CB-59.

CB-50 plan review также фиксирует внешний факт: release run 64 успешно
развёрнул commit `c605b566a5f5e1fb799224bf4eb406f67fd05449`, migration gate
`0020` и healthy `postgres`/`worker`/`bot`. Этот факт используется только как
source context; CB-59 не повторяет production inspection.

## Канонические правила процесса

- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` — Jira-first, одна ветка на задачу,
  русские артефакты, immutable secrets boundary, уровень риска и обязательный
  маршрут PR/CI/review/merge.
- `docs/AGENT_WORKFLOW.md` — для уровня 3 нужны `plan.md`,
  `plan-source-context.md`, независимое plan review, test plan при
  недостаточности automated coverage, `implementation-report.md` и
  `final-review.md`.
- `docs/JIRA_WORKFLOW.md` — CB-59 является самостоятельным инфраструктурным
  blocker с собственной приёмкой; финальный `Done` не следует автоматически из
  merge.
- `agents/README.md` — роли `developer`, независимые `plan-reviewer` и
  `final-review`, точные значения verdict status.

## Продуктовые и технические источники

- `docs/mvp/README.md` — Release 1 остаётся каноническим MVP.
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md` — атомарность и идемпотентность
  финансово-подобных операций.
- `docs/mvp/02_DOMAIN_RULES.md` — immutable ledger является источником истины;
  cached balances обязаны ему соответствовать.
- `docs/mvp/TECH_STACK.md` — PostgreSQL 18, Alembic, Python ops scripts, один
  immutable image, expand-only release migrations и отсутствие автоматического
  schema downgrade.
- `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md`, D-025 и D-029 — self-hosted
  runtime, local logical backup, restore drill и Python operational path.
- `docs/adr/0009-self-hosted-pilot-runtime.md` — отдельная временная БД,
  revision/table checks, RPO/RTO и принятый риск same-host backup.
- `docs/adr/0011-protected-single-ci-release.md` — release использует exact
  reviewed merge/image digest; rollback сохраняет schema и не делает downgrade.
- `docs/operations/PILOT_RUNBOOK.md` — текущие deployment, backup, restore,
  preflight, cleanup и incident boundaries.
- `docs/operations/PILOT_CHECKLIST.md` — ежедневная фиксация release,
  revision, ledger mismatch, backup age и restore duration.

## Применённый migration-контракт

Полностью прочитан skill `database-migrations`. Для CB-59 применимы правила:

- выпущенные migrations неизменяемы;
- production migrations forward-only;
- schema downgrade не используется как rollback приложения;
- drift закрывается проверяемым контрактом release image ↔ DB, а не ручным SQL;
- schema и data migration не смешиваются.

CB-59 не меняет схему и не создаёт migration: она чинит проверку уже выпущенной
линейной graph. Поэтому checklist `UP/DOWN`, блокировки DDL и production-sized
backfill неприменимы; ключевой safety gate — отсутствие diff в
`migrations/versions`.

## Факты репозитория

- Worktree: `C:/Users/User/community_bot-worktrees/CB-59`.
- Ветка: `task/CB-59`, база `origin/main` =
  `cbb1807fe281f022cb46caef75e3adaeb9cbce9e`.
- На момент начала планирования дерево чистое.
- `uv run alembic heads` выводит ровно `0020 (head)`.
- `migrations/versions/0020_freeform_task_creation.py` имеет
  `down_revision = "0019"`; graph линейна до `0001`.
- Deployed migration files не редактируются, новая migration для этой задачи не
  нужна.
- `pyproject.toml`, root project entry в `uv.lock` и
  `src/community_bot/__init__.py` содержат version `0.1.0`.
- `Dockerfile` включает `pyproject.toml`, `uv.lock`, `src`, `migrations` и
  `alembic.ini` в один image; поэтому packaged CLI способен сообщить graph head
  именно этого image.
- `ops/_runtime.py::read_current_image()` принимает только GHCR digest либо
  локальный immutable Docker image ID.
- `compose.production.yaml` подставляет тот же `COMMUNITY_BOT_IMAGE` в
  `migrate`, `worker` и `bot`.
- `src/community_bot/bootstrap/migrate.py` уже использует packaged Alembic graph
  для migration gate, но scalar-чтение production revision не является
  достаточным контрактом для restore drill с explicit row cardinality.

## Фактический дефект текущего restore path

`ops/restore_drill.py` сейчас:

1. содержит SQL comparison с literal `0019`;
2. не получает expected head из current image;
3. не проверяет production `alembic_version`;
4. scalar/subquery semantics не описывают zero/multiple rows отдельно;
5. возвращает failure при restore/cleanup subprocess error, но тесты не
   доказывают полный порядок и отсутствие drill DB на каждом пути;
6. смешивает revision и ledger validation в одном статическом SQL block, что
   затрудняет точную fault matrix.

`tests/unit/test_operations.py` лишь ищет строки в файле, включая `0019`, и не
проверяет orchestration. Поэтому automated behavior coverage недостаточно и для
CB-59 создан отдельный `test-plan.md`.

## Проверка исполнимости quality-команд на baseline

До реализации локально проверен текущий toolchain:

- `uv run ty check ops/restore_drill.py` — `All checks passed!`; значит `ty`
  принимает точный path host-side ops script, а после реализации к этой команде
  можно добавить новые модули и тесты;
- `uv run coverage run --branch --source=ops.restore_drill -m
  ops.restore_drill --help` и последующий `coverage report` распознали
  `ops/restore_drill.py` как отдельный измеряемый source: baseline показал
  `44` statements, `2` branches и `37%`, что ожидаемо без поведенческих tests;
- установленный `pytest-cov 7.1.0` проверен командой с
  `-o addopts=`, `--cov=ops.deploy_from_git`, `--cov-branch`,
  `--cov-report=term-missing` и `--cov-fail-under`; аналогичный существующий
  `ops.deploy_from_git` был измерен успешно.

Точные post-implementation coverage-команды для `ops/restore_drill.py` и нового
image-head модуля записаны отдельно в `plan.md` и `test-plan.md`. Сейчас они не
могут быть выполнены буквально, потому что целевые test files и новый модуль
ещё не существуют; создавать их на фазе планирования запрещено.

## Trust и privacy boundaries

- Expected head доверяется только packaged Alembic graph exact image из
  `current-image`.
- `POSTGRES_USER`, `POSTGRES_DB`, password и connection strings не выводятся.
- Image-head command работает без network и production env.
- Production database получает только SELECT; DDL адресовано фиксированной
  временной базе.
- Backup content, participant rows, ledger entries и Telegram data не попадают
  в task artifacts.
- Разрешённые evidence: commit/image identity, expected/actual revision,
  aggregate counts, `ledger_mismatch_count`, UTC duration, exit/result codes и
  факт отсутствия drill DB.

## Ограничения и зависимости

- Не выполняются production deploy, Environment approval, server SSH, tag,
  GitHub Release или Telegram actions.
- RPO `<=24h`, RTO `<=4h`, retention семь суток и same-host backup risk не
  пересматриваются.
- Локальный operational smoke использует только disposable environment и
  искусственные данные.
- При недоступности локального Docker поведенческая fault matrix остаётся
  обязательной автоматической проверкой, а невозможный disposable smoke
  фиксируется как blocker final review, а не объявляется пройденным.
- После merge CB-59 CB-50 заново выбирает current `origin/main`; старые
  production/release evidence не переносятся на новый candidate автоматически.

## Открытые вопросы

Продуктовых вопросов, требующих решения владельца до реализации, нет.
Технический контракт для планирования определён: узкий packaged CLI и exact
image invocation. Если независимое plan review обнаружит, что этот CLI меняет
привилегированную release boundary либо требует Compose/YAML modification,
план возвращается на исправление до кода.
