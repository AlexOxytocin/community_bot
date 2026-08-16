# CB-47 — план реализации

## Цель

Сделать каталог участников более прямым: пользователь нажимает на саму строку участника в inline-клавиатуре, а не сопоставляет строку текста с отдельной кнопкой `+ NN`.

## Область

- Изменить Telegram presentation каталога участников в `src/community_bot/transport/telegram/reputation.py`.
- Оставить существующие callback prefix, cursor payload, поиск, сброс, пагинацию и проверки прав.
- В тексте сообщения показывать заголовок, строку поиска и детали только выбранного участника.
- В inline-клавиатуре показывать каждую строку участника отдельной кнопкой с краткой safe projection.
- Обновить unit/output-driven тесты и документацию MVP.

## Вне области

- Не менять БД, application-service, storage и правила видимости.
- Не добавлять WebApp или внешнюю таблицу.
- Не менять поиск по скрытым Telegram `first_name`/`last_name`.
- Не менять админские действия и eligibility кармы.

## Риск

Низкий-средний: правка находится в Telegram transport, но затрагивает живой пользовательский интерфейс и callback-достижимость действий. Основной риск — слишком длинные labels кнопок и потеря состояния поиска при redraw.

## Проверка

- `uv run pytest tests/unit/test_reputation_transport.py -q`
- `uv run pytest tests/integration/test_output_driven_flows.py -k karma_sanction_and_alert_use_only_visible_outputs --no-cov -q`
- `uv run ruff check src tests`
- `uv run ty check src tests ops\verify_release_provenance.py`
- `git diff --check`

После merge и deploy нужна короткая live Telegram acceptance: `/members`, нажатие row-кнопки, сворачивание, поиск и сброс.
