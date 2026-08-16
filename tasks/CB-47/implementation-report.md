# CB-47 — отчёт реализации

## Статус

Локальная реализация завершена. Каталог участников теперь показывает каждого
участника отдельной inline-кнопкой, а текст сообщения не дублирует весь список.
Production gate остаётся отдельным шагом после merge, release и deploy.

## Изменения

- В `src/community_bot/transport/telegram/reputation.py` строки каталога
  перенесены из body text в inline-клавиатуру: одна кнопка — один участник.
- Нажатие на строку-кнопку открывает профиль через прежний `mc:o:<cursor>:<index>`,
  повторное нажатие на раскрытую строку закрывает его через
  `mc:x:<cursor>:<index>`.
- Body text оставляет только заголовок `Участники`, строку поиска и детали
  раскрытого профиля.
- Action-кнопки `Профиль`, `Оценить`, административные действия, поиск, сброс и
  cursor-пагинация сохранены.
- Добавлено ограничение длины текста кнопки до 64 символов с сохранением
  краткой safe projection.
- Обновлены unit/output-driven/integration тесты и MVP-документация.

## Матрица приёмки

| Критерий | Доказательство |
|---|---|
| Нет сопоставления текстовой строки с отдельной кнопкой `+ NN` | Список больше не рендерится в body text; каждая строка создаётся в inline keyboard. |
| Каждая видимая строка участника — отдельная inline-кнопка | `test_members_command_renders_searchable_compact_catalog_and_expands_row`, `test_members_catalog_paginates_resets_and_prompts_for_search`. |
| Нажатие раскрывает только одного участника | `present_member_catalog` показывает детали только `expanded_member_id`; output-driven helper открывает row button. |
| Повторное нажатие сворачивает детали | Unit-тест проверяет callback `mc:x` и возврат body text к заголовку/поиску без деталей. |
| Детали и action-кнопки сохраняют правила прав и safe projection | Callback prefixes и `_member_catalog_action_rows` не менялись; тесты проверяют `Профиль`, `Оценить` и admin action callbacks. |
| Поиск, сброс и cursor-пагинация работают без смены callback policy | Callback data остались `mc:o`, `mc:x`, `mc:p`, `mc:s`, `mc:r`; тесты покрывают поиск, `Ещё` и `Сбросить поиск`. |
| Целевые Telegram presentation/output-driven тесты обновлены | Обновлены `tests/unit/test_reputation_transport.py`, `tests/integration/test_output_driven_flows.py`, `tests/integration/test_initial_admin.py`. |
| Документация MVP описывает новый формат | Обновлены `docs/mvp/03_USER_FLOWS.md`, `docs/mvp/05_BOT_INTERFACE.md`, `docs/mvp/10_TEST_PLAN.md`. |

## Проверки

- `uv run pytest tests/unit/test_reputation_transport.py --no-cov -q` —
  `6 passed in 3.63s`.
- `uv run pytest tests/integration/test_output_driven_flows.py -k karma_sanction_and_alert_use_only_visible_outputs --no-cov -q` —
  `1 passed, 19 deselected in 36.00s`.
- `uv run pytest tests/integration/test_initial_admin.py::test_real_cli_then_production_dispatcher_creates_invitation_and_registration --no-cov -q` —
  `1 passed in 8.34s`.
- `uv run pytest tests/integration/test_member_foundation.py::test_fault_between_member_save_and_outbox_enqueue_rolls_back_member_and_allows_retry --no-cov -q` —
  `1 passed in 7.78s`.
- `uv run ruff format --check .` — `459 files already formatted`.
- `uv run ruff check .` — `All checks passed!`.
- `uv run ty check src tests ops\verify_release_provenance.py` —
  `All checks passed!`.
- `git diff --check` — успешно.
- `uv run pytest -q` — `495 passed, 1 skipped in 388.13s`, coverage `80.39%`.

Первый точечный запуск `uv run pytest tests/unit/test_reputation_transport.py -q`
завершился из-за общего coverage fail-under при узком наборе тестов; после этого
целевой тест был повторён с `--no-cov`, а полная регрессия прошла успешно.

## Остаточный риск

Живой Telegram-интерфейс на production ещё нужно подтвердить после merge,
публикации release и deploy по `docs/operations/PILOT_RUNBOOK.md`.
