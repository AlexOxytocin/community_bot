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
| `alembic upgrade head` проходит на PostgreSQL | частично, обязательный CI-барьер | локальная offline-компиляция `upgrade head --sql` прошла; реальный `upgrade/downgrade/upgrade` и `SELECT 1` настроены в job `PostgreSQL and Alembic`, но локальный Docker отсутствует |
| Ruff, ty и pytest проходят | выполнено локально | formatter, Ruff `ALL`, ty и оба режима pytest зелёные; CI повторяет команды на pull request и push в `main` |
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
- `uv run pytest` — 17 passed, 1 skipped с явной причиной отсутствия `DATABASE_URL`, coverage 90,91%;
- прямые `community-bot --check` и `community-worker --check` — успешно;
- `DATABASE_URL=... uv run alembic upgrade head --sql` — успешно;
- `uv build` — успешно, созданы sdist и wheel в ignored-каталоге `dist/`;
- TOML и YAML (`pyproject.toml`, workflow, Compose) — успешно разобраны;
- поиск секретов, Jira-ключа в runtime и кириллицы в коде — совпадений нет;
- `git diff --check` — успешно для отслеживаемой разницы.

## documentation_updates

README обновлён с фактическими командами этапа 0. Новое структурное решение не вводилось: реализация следует принятому ADR-0005. Для PostgreSQL 18 volume направлен в `/var/lib/postgresql` в соответствии с актуальным изменением официального образа.

## review_status

План: `Status: approved`. Первая независимая финальная проверка: `Status: blocked`. Найденный ею дефект AST-проверки исправлен и закрыт регрессионными тестами; оставшийся барьер требует реального запуска GitHub Actions с PostgreSQL 18 на опубликованном commit и повторного независимого финального ревью.

## external_mutations_performed

- создана локальная ветка `task/CB-3` от `origin/main` (`c13f2d8`);
- Jira `CB-2` и `CB-3` переведены в `В работе` точным доступным переходом;
- в `CB-3` добавлен русскоязычный комментарий о начале реализации;
- Telegram, production-инфраструктура и реальные внешние отправки не изменялись.

## remaining_risks

- локальный Docker недоступен, поэтому реальный PostgreSQL 18, миграционный цикл и `SELECT 1` должны пройти в GitHub Actions на публикуемом commit до merge;
- workflow ещё не исполнялся в GitHub и не считается доказанным только по локальному YAML-разбору;
- первая финальная проверка требует GitHub Actions на точном опубликованном commit; ветка и PR будут опубликованы только для получения этого доказательства, без merge и финального перехода Jira до повторного `Status: approved`.

## next_action

Создать контрольный commit, push и PR без merge, дождаться зелёных jobs `Quality` и `PostgreSQL and Alembic`, затем обновить доказательства и повторить независимый final-review. Merge и финальный переход Jira разрешены только после `Status: approved` и зелёного CI на актуальном commit.
