# Community Bot

Telegram-бот закрытого сообщества взаимной помощи с заданиями, внутренней экономикой, прогрессом и репутацией. В репозитории создан инфраструктурный каркас модульного монолита; продуктовые функции будут добавляться отдельными Jira-задачами.

## Язык проекта

Русский язык является каноническим для документации, Jira, планов, отчётов и проверок. Код, технические идентификаторы, ключи конфигурации, логи и сообщения об ошибках во время выполнения пишутся на английском.

## Текущее состояние

- Подключена Jira `CB` через Atlassian Rovo MCP с доступом на чтение и запись.
- Создан отдельный MemPalace проекта.
- Зафиксированы инженерные принципы, агентские роли и процесс разработки.
- Сформирован пакет требований и план разработки MVP в `docs/mvp/`.
- Утверждён стек Python 3.13, aiogram 3.x, PostgreSQL 18 и SQLAlchemy 2 async.
- Создан этап 0: Python-пакет, границы слоёв, PostgreSQL 18, Alembic, тесты и CI.

## Требования к окружению

- [uv](https://docs.astral.sh/uv/) 0.12.3 или совместимая версия;
- управляемый uv Python 3.13;
- Docker с Compose — только для PostgreSQL и миграционных проверок.

Установка окружения из зафиксированного lock-файла:

```powershell
uv python install 3.13
uv sync --locked --all-groups
uv run python --version
```

## Безопасные точки запуска

На этапе 0 процессы не обращаются к Telegram и не требуют Bot API token. Режим проверки загружает конфигурацию, настраивает структурированное логирование и завершается успешно:

```powershell
uv run community-bot --check
uv run community-worker --check
```

Запуск без `--check` намеренно возвращает код 2 и событие `runtime_not_implemented`, пока runtime не будет реализован отдельной задачей.

## Конфигурация

Скопируйте `.env.example` в локальный `.env` и при необходимости измените только development-значения. `.env` игнорируется Git. Для миграций обязательна переменная `DATABASE_URL`; bootstrap-проверки используют безопасные значения по умолчанию.

## PostgreSQL и миграции

```powershell
docker compose config
docker compose up -d --wait postgres
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
uv run pytest -m integration --no-cov
docker compose down -v
```

Начальная миграция пуста и не создаёт продуктовые таблицы: она проверяет только работоспособность инфраструктурного контура.

## Проверки качества

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check src tests
uv run pytest -m "not integration"
```

Полный `uv run pytest` локально явно пропускает PostgreSQL-тест, если `DATABASE_URL` не задан. В GitHub Actions этот тест обязателен в отдельном job с PostgreSQL 18.

## Архитектурные границы

Исходный код расположен в `src/community_bot/`:

- `domain` не зависит от фреймворков и внешних слоёв;
- `application` может зависеть от `domain`, но не от адаптеров;
- `transport` и `infrastructure` содержат внешние адаптеры;
- `bootstrap` собирает процесс bot;
- `worker` предоставляет отдельную точку запуска из той же кодовой базы.

Направления импортов проверяются AST-тестом в `tests/architecture/`.

## Навигация

- `docs/PROJECT_CONTEXT.md` — цели, границы и открытые продуктовые вопросы.
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` — обязательные правила проекта.
- `docs/DEVELOPMENT_PRINCIPLES.md` — канонические инженерные принципы.
- `docs/AGENT_WORKFLOW.md` — процесс от Jira-задачи до передачи результата.
- `docs/JIRA_WORKFLOW.md` — настройки и правила Jira `CB`.
- `docs/ARCHITECTURE.md` — исходные архитектурные границы.
- `docs/mvp/README.md` — требования, доменные правила, сценарии и план MVP.
- `docs/mvp/TECH_STACK.md` — утверждённый технологический стек.
- `docs/adr/` — архитектурные решения (ADR).
- `agents/` — инструкции и конфигурация ролей агентов.
- `tasks/` — рабочие артефакты Jira-задач.
- `src/` — будущий исходный код.
- `tests/` — автоматизированные тесты.

## Telegram

Для разрешённых операций с пользовательским Telegram-аккаунтом используется общий инструмент:

```powershell
& 'C:\Users\User\.codex\tools\telegram.ps1' probe
```

Сессии и ключи находятся вне репозитория.

## MemPalace

Выделенное хранилище: `C:\Users\User\.mempalace\palaces\community_bot`.

Документация репозитория остаётся источником истины, а MemPalace используется как поисковый индекс.
