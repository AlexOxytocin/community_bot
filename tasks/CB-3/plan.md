# CB-3 — план каркаса модульного монолита и базового CI

## Цель

Создать минимальный воспроизводимый Python-проект этапа 0, который фиксирует утверждённые архитектурные границы, запускаемые безопасные точки `bot`/`worker`, PostgreSQL 18, Alembic и обязательный quality gate. Продуктовые функции не реализуются.

## Уровень процесса

Уровень 3 по ADR-0004: задача структурная, интеграционная и насыщенная источниками. Требуются `plan-source-context.md`, `test-plan.md`, независимый `plan-review.md` со `Status: approved`, доказательства CI и независимый `final-review.md`. Новый ADR не нужен: план реализует уже принятое решение ADR-0005 и не меняет его.

## Готовность

- цель, область, критерии Jira и родительский эпик прочитаны;
- входящих блокирующих связей нет;
- отдельного Jira-статуса планирования нет, поэтому до одобрения плана фактический статус остаётся `К выполнению`;
- локальный `main` чист и синхронизирован с `origin/main`;
- локально отсутствуют uv, Python 3.13 и Docker; способы проверки без снижения критериев описаны ниже.

## Выбранный подход

### Python и зависимости

- установить uv официальным способом и использовать управляемый CPython 3.13;
- инициализировать application package с `uv_build`, `requires-python = ">=3.13,<3.14"` и `.python-version`;
- runtime-зависимости добавлять только через `uv add`: aiogram 3.x, SQLAlchemy 2 async, asyncpg, Alembic, Pydantic 2, pydantic-settings и structlog;
- Ruff и ty поместить в dependency group `lint`; pytest, pytest-asyncio, pytest-cov, Hypothesis и Testcontainers — в group `test`;
- зафиксировать `uv.lock` и проверять `uv sync --locked --all-groups`.

Полный cookiecutter не используется: структура уже утверждена ADR-0005, а генератор добавил бы несогласованные файлы и решения. Ручное редактирование списков зависимостей в `pyproject.toml` не используется; конфигурационные секции инструментов редактируются после `uv add`.

### Модульные границы

Создать пакет:

```text
src/community_bot/
  bootstrap/
  transport/telegram/
  application/
  domain/
  infrastructure/db/
  infrastructure/outbox/
  infrastructure/observability/
  worker/
```

- `domain` не импортирует aiogram, SQLAlchemy или внешние слои;
- `application` зависит от `domain`, но не от transport, infrastructure, bootstrap и worker;
- transport и infrastructure реализуют внешние адаптеры;
- bootstrap собирает зависимости;
- worker является отдельной точкой запуска из той же кодовой базы;
- pytest-тест на основе AST проверяет запрещённые направления импортов без дополнительного runtime-инструмента.

### Точки запуска и конфигурация

- добавить console scripts `community-bot` и `community-worker`;
- обе точки поддерживают `--check`: загружают минимальную конфигурацию, инициализируют структурированное логирование и завершаются с кодом 0 без Bot API token, БД и внешней отправки;
- запуск без `--check` до появления runtime-реализации завершается безопасной английской ошибкой и не имитирует работающий сервис;
- добавить `.env.example` с placeholders и Pydantic Settings; реальные секреты не коммитятся.

### PostgreSQL и Alembic

- добавить `compose.yaml` только с PostgreSQL 18, health check и именованным volume;
- значения локального пользователя, базы и пароля приходят из `.env`, а пример содержит только development placeholders;
- Alembic читает `DATABASE_URL`, использует async SQLAlchemy environment и содержит пустую начальную migration;
- миграция не создаёт продуктовые таблицы и служит проверкой инфраструктурного контура;
- database smoke test выполняет `SELECT 1` на PostgreSQL 18.

### Quality gate и CI

- Ruff: `target-version = "py313"`, `select = ["ALL"]`, документированные конфликты форматтера исключены, тестовые исключения ограничены;
- public Python APIs и entry points получают английские docstrings; blanket-ignore для docstrings не используется;
- ty: Python 3.13 и warnings as errors;
- pytest: strict markers/config, warnings as errors, branch coverage не ниже 80%;
- GitHub Actions использует `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` и `astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9`;
- отдельные jobs проверяют качество и PostgreSQL/Alembic через `compose.yaml`;
- CI запускается на pull request и push в `main`.

## Изменяемые файлы

- `pyproject.toml`, `uv.lock`, `.python-version`;
- `.env.example`, `compose.yaml`, `alembic.ini`;
- `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/*_initial_schema.py`;
- `.github/workflows/ci.yml`;
- `src/community_bot/**` по описанным границам;
- `tests/unit/`, `tests/architecture/`, `tests/integration/`, `tests/smoke/`;
- `README.md` и при необходимости `.gitignore`;
- `tasks/CB-3/implementation-report.md` и `tasks/CB-3/final-review.md` после реализации;
- удалить `src/.gitkeep` и `tests/.gitkeep` после появления реальных файлов.

## Матрица приёмки

| Критерий Jira | Реализация | Проверка |
|---|---|---|
| `uv sync --locked` воспроизводим | `pyproject.toml`, `uv.lock`, `.python-version`, dependency groups | чистое повторное `uv sync --locked --all-groups`, Python 3.13.x, неизменный lock |
| `bot` и `worker` проходят smoke без токена | console scripts и безопасный `--check` | pytest smoke tests и прямой запуск обеих команд |
| `alembic upgrade head` проходит на PostgreSQL | `compose.yaml`, async Alembic environment, initial migration | CI: compose health, upgrade/downgrade/upgrade и `SELECT 1` |
| Ruff, ty и pytest проходят локально и в CI | конфигурация инструментов и pinned workflow | команды из `test-plan.md`, зелёные обязательные CI jobs |
| границы импортов проверяются | AST architecture test | положительные и отрицательные fixtures/test cases |
| README содержит точные команды | обновлённые разделы разработки и запуска | ручная проверка команд в чистом окружении и финальное ревью |

## Риски и меры

- **uv отсутствует локально:** установить официальным способом; все дальнейшие зависимости менять только через uv.
- **системный Python 3.14 вместо 3.13:** использовать uv-managed Python 3.13 и жёсткую project constraint `<3.14`.
- **Docker отсутствует локально:** не заявлять локальное прохождение PostgreSQL; сделать Docker/Alembic job обязательным в GitHub Actions и дождаться зелёного результата до merge.
- **нестабильные latest tags Actions:** использовать полные commit SHA, зафиксированные по официальным release tags на дату планирования.
- **скрытое добавление продуктовой логики:** entry points работают только как проверяемый bootstrap, migration остаётся пустой, тест области запрещает доменные модели следующих этапов.
- **секреты в примере окружения:** использовать только placeholders; `.env` остаётся ignored; выполнить отдельный secret scan.
- **слишком мягкие статические правила:** включить Ruff `ALL`, ty warnings as errors и architecture tests с точным списком запрещённых зависимостей.

## Не входит в задачу

- регистрация, приглашения, роли и модель участника;
- каталог, задания, ledger, опыт, уровни, карма и модерация;
- production Bot API token и реальные Telegram-операции;
- outbox processing, retries и рабочие уведомления;
- выбор провайдера размещения, error reporting и backup policy;
- Redis, Celery, FastAPI, webhook, Kubernetes и микросервисы.

## Последовательность выполнения

1. Получить независимый `plan-review.md` со `Status: approved`.
2. Показать план владельцу и получить одобрение начала реализации.
3. От актуального `origin/main` создать `task/CB-3`.
4. Получить актуальные переходы Jira и перевести `CB-3` и эпик `CB-2` в `В работе` только перед первым изменением реализации.
5. Установить uv, инициализировать проект и добавить зависимости через `uv add`.
6. Реализовать структуру, entry points, Alembic, Compose, тесты, CI и документацию.
7. Выполнить локальные проверки и создать `implementation-report.md`.
8. Получить независимый `final-review.md` со `Status: approved`.
9. Commit, push, PR, CI, merge и изменения Jira выполнять последовательно по ясному намерению пользователя; merge запрещён до зелёных обязательных CI jobs.
