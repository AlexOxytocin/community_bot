# CB-3 — отчёт о реализации каркаса и базового CI

`community_bot.developer.handoff.v1`

## issue_key

`CB-3`

## scope_summary

Реализован этап 0 без продуктовых функций: воспроизводимый Python-проект, границы модульного монолита, безопасные процессы bot/worker, PostgreSQL 18, асинхронный Alembic, статические проверки, тесты и GitHub Actions.

Регистрация, роли, каталог, задания, экономика, карма, модерация, реальные Telegram-операции и обработка outbox не добавлялись.

## changed_files

- окружение и зависимости: `.python-version`, `pyproject.toml`, `uv.lock`;
- конфигурация: `.env.example`, `.gitignore`, `compose.yaml`, `alembic.ini`;
- миграции: `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001_initial_schema.py`;
- процессы и слои: `src/community_bot/**`;
- проверки: `tests/unit/**`, `tests/smoke/**`, `tests/architecture/**`, `tests/integration/**`;
- CI: `.github/workflows/ci.yml`;
- документация: `README.md`, пакет планирования и этот отчёт.

## acceptance_evidence

| Критерий Jira | Результат | Доказательство |
|---|---|---|
| `uv sync --locked` воспроизводим | выполнено локально | `uv venv --clear --python 3.13` и повторный `uv sync --locked --all-groups`; SHA-256 `uv.lock` не изменился; `uv run python --version` → `Python 3.13.15` |
| bot и worker проходят smoke без токена | выполнено локально | `uv run community-bot --check` и `uv run community-worker --check` → код 0 и `bootstrap_check_passed`; pytest также проверяет безопасный код 2 без `--check` |
| `alembic upgrade head` проходит на PostgreSQL | выполнено локально и в CI | PostgreSQL 18.4 поднят через Compose; реальный цикл `upgrade/downgrade/upgrade` и `SELECT 1` успешно выполнены локально и в job `PostgreSQL and Alembic` |
| Ruff, ty и pytest проходят | выполнено локально и в CI | formatter, Ruff `ALL`, ty и полный pytest зелёные; job `Quality` успешно прошёл в PR №2 |
| границы импортов проверяются | выполнено | AST-тест проверяет текущий пакет, абсолютные и относительные запрещённые импорты, форму `from .. import ...` и границы компонентов модульного имени |
| README содержит точные команды | выполнено | описаны установка, безопасный запуск, `.env`, Compose, Alembic, тесты и архитектурные границы |

## test_results

- `uv sync --locked --all-groups` — успешно;
- `uv lock --check` — успешно;
- повторное создание `.venv` через `uv venv --clear` — успешно, lock неизменен;
- `uv run ruff format --check .` — успешно, 91 файл;
- `uv run ruff check .` — успешно;
- `uv run ty check src tests` — успешно;
- `uv run pytest -m "not integration"` — 17 passed, 1 deselected, coverage 90,91%;
- `DATABASE_URL=... uv run pytest` — 18 passed без пропусков, coverage 100%;
- локальный PostgreSQL — версия 18.4, контейнер `postgres:18` здоров по Compose healthcheck;
- реальный `alembic upgrade head`, `alembic downgrade base`, повторный `alembic upgrade head` — успешно;
- прямые `community-bot --check` и `community-worker --check` — успешно;
- `DATABASE_URL=... uv run alembic upgrade head --sql` — успешно;
- `uv build` — успешно, созданы sdist и wheel в ignored-каталоге `dist/`;
- TOML и YAML (`pyproject.toml`, workflow, Compose) — успешно разобраны;
- поиск секретов, Jira-ключа в runtime и кириллицы в коде — совпадений нет;
- `git diff --check` — успешно для отслеживаемой разницы.

## documentation_updates

README обновлён с фактическими командами этапа 0. Новое структурное решение не вводилось: реализация следует принятому ADR-0005. Для PostgreSQL 18 volume направлен в `/var/lib/postgresql` в соответствии с актуальным изменением официального образа.

## review_status

План: `Status: approved`. Первая независимая финальная проверка: `Status: blocked`; найденный ею дефект AST-проверки исправлен и закрыт регрессионными тестами. Повторная независимая финальная проверка выполнена с нуля и завершена точным `Status: approved`: reviewer самостоятельно подтвердил локальный PostgreSQL 18.4, миграционный цикл, 18 тестов без skip, 100% coverage, оба CI job и состояние Jira.

## external_mutations_performed

- создана локальная ветка `task/CB-3` от `origin/main` (`c13f2d8`);
- Jira `CB-2` и `CB-3` переведены в `В работе` точным доступным переходом;
- в `CB-3` добавлен русскоязычный комментарий о начале реализации;
- установлены WSL 2.7.11 и Docker Desktop 4.85.0 для постоянного локального тестового контура;
- открыт PR №2; на commit `fe339e7` успешно прошли jobs `Quality` и `PostgreSQL and Alembic`;
- Telegram, production-инфраструктура и реальные внешние отправки не изменялись.

## remaining_risks

- блокирующих рисков по области CB-3 нет;
- после публикации финальных артефактов CI должен повторно пройти на точном merge-кандидате до слияния.

## next_action

Опубликовать финальные артефакты, дождаться зелёных jobs `Quality` и `PostgreSQL and Alembic` на точном merge-кандидате, затем слить PR №2 и перевести Jira CB-3 в `Готово`.
