# CB-46 — implementation report

## Что изменено

- Пункт `Участники` переведён с пачки отдельных карточек на один compact catalog в Telegram-сообщении.
- Каждая строка каталога показывает `+`/`-`, публичный `@telegram_username`, если он есть, анкетное имя, уровень и агрегированную карму.
- Раскрытие строки редактирует то же сообщение и показывает детали safe profile и действия `Профиль`/`Оценить`.
- Административные действия в раскрытой строке появляются только после актуальной проверки `moderation`/`foundation`.
- Добавлен `/members <ник или имя>` с минимальной длиной 3 символа после удаления пробелов и ведущего `@`.
- Поиск выполняется на сервере по публичным полям `telegram_username` и `display_name`; Telegram `first_name`/`last_name` не используются.
- Cursor-пагинация сохранена на уровне БД; callback хранит только cursor member UUID и номер строки, чтобы не превышать лимит Telegram `callback_data`.
- Документация MVP и пользовательская инструкция обновлены под новый сценарий.

## Изменённые области

- Application: `ReputationService.members`, нормализация поискового запроса, safe profile projection.
- Infrastructure: SQL-фильтр active catalog по `display_name`/`telegram_username`, восстановление cursor по member UUID.
- Telegram transport: compact renderer, open/close/page/search/reset callback-и, действия в раскрытой строке.
- Tests: unit/output-driven проверки нового экрана, SQL-поиск, privacy-фильтр non-active, production dispatcher smoke.

## Проверки

- `uv run ruff check .` — успешно.
- `uv run ruff format --check .` — успешно.
- `uv run ty check src tests ops\verify_release_provenance.py` — успешно.
- `git diff --check` — успешно.
- `uv run pytest --no-cov tests\unit\test_reputation_transport.py tests\integration\test_reputation.py tests\integration\test_output_driven_flows.py::test_karma_sanction_and_alert_use_only_visible_outputs tests\integration\test_registration.py::test_concurrent_moderation_creates_one_grant_and_active_profile tests\integration\test_initial_admin.py::test_real_cli_then_production_dispatcher_creates_invitation_and_registration tests\integration\test_navigation.py::test_production_navigation_requires_no_user_supplied_uuid -q` — `24 passed`.
- `uv run pytest -q` — `495 passed, 1 skipped`, coverage `80.38%`.

## Не закрыто этим изменением

- Live Telegram/deploy acceptance не выполнялся. По правилам проекта это локальная готовность к PR, а не подтверждение рабочего экземпляра.
- Отдельный индекс под поиск не добавлялся: для заявленного сценария 500+ участников достаточно серверного фильтра и keyset-пагинации; при росте на порядок стоит вынести индекс в отдельную задачу.
