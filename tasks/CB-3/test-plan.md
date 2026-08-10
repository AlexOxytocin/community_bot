# CB-3 — план проверок

## 1. Воспроизводимость Python-окружения

1. Проверить версию uv.
2. Выполнить `uv python install 3.13` либо подтвердить автоматическую установку управляемого Python 3.13.
3. Выполнить `uv sync --locked --all-groups` в чистом окружении.
4. Проверить, что `uv run python --version` сообщает Python 3.13.x.
5. Удалить локальную `.venv`, повторить `uv sync --locked --all-groups` и убедиться, что lock-файл не изменился.

## 2. Статические проверки

- `uv run ruff format --check .`;
- `uv run ruff check .`;
- `uv run ty check src tests`;
- тест границ импортов подтверждает, что `domain` не зависит от aiogram, SQLAlchemy и внешних слоёв, а `application` не зависит от transport/infrastructure/bootstrap/worker.

## 3. Тесты и покрытие

- `uv run pytest` выполняет unit, smoke и доступные integration tests;
- entry points `community-bot --check` и `community-worker --check` завершаются с кодом 0 без токена и внешней отправки;
- проверяется безопасное поведение точек запуска без `--check` до появления runtime-реализации;
- coverage не ниже 80% для созданного Python-кода;
- warnings и неизвестные pytest markers считаются ошибками.

## 4. PostgreSQL и миграции

Локальный Docker на момент планирования недоступен, поэтому этот барьер обязателен в GitHub Actions:

1. `docker compose config` проходит.
2. `docker compose up -d --wait postgres` поднимает PostgreSQL 18.
3. `uv run alembic upgrade head` проходит на пустой базе.
4. `uv run alembic downgrade base` и повторный `upgrade head` проходят.
5. Integration smoke test устанавливает асинхронное соединение и выполняет `SELECT 1`.
6. После теста выполняется `docker compose down -v`.

## 5. CI

- workflow использует закреплённые полные SHA для `actions/checkout` и `astral-sh/setup-uv`;
- workflow запускается для pull request и push в `main`;
- quality job выполняет locked sync, Ruff, ty и pytest;
- PostgreSQL job проверяет `compose.yaml`, Alembic и database smoke test;
- pull request нельзя считать готовым к merge до зелёных обязательных jobs.

## 6. Документация, язык и секреты

- README содержит точные команды установки, запуска, миграций и проверок;
- `.env.example` содержит только безопасные placeholders, `.env` остаётся игнорируемым;
- код, идентификаторы, docstrings, комментарии, логи и runtime errors написаны на английском;
- смысловая документация и Jira-артефакты написаны на русском;
- поиск не обнаруживает токены, реальные пароли, session data и приватные идентификаторы;
- `git diff --check` проходит для полной разницы.

## 7. Область и регрессия

- `.gitkeep` удалены только после появления реальных файлов в `src/` и `tests/`;
- отсутствуют модели участников, задания, ledger, karma и другие функции следующих этапов;
- относительные Markdown-ссылки остаются рабочими;
- полный доступный набор тестов репозитория проходит;
- независимый `final-review` повторно проверяет фактический PR и результаты CI.

## Критерий прохождения

Все локально доступные проверки проходят; Docker-зависимые сценарии подтверждены зелёным CI на публикуемом commit. Каждый критерий Jira имеет доказательство в `implementation-report.md`, а `final-review.md` содержит точный `Status: approved` до merge.
