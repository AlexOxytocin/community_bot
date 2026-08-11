# CB-25 — отчёт о реализации

## Результат

Редактирование собственной карточки снова достижимо из обеих пользовательских
точек входа. Presentation и восемь edit actions вынесены в общий transport-модуль.

## Изменения

- `src/community_bot/transport/telegram/profile.py` — единая полная карточка и
  edit keyboard.
- `registration.py` — exact `/profile` показывает editable own profile.
- `navigation.py` — `Моя карточка` использует тот же presentation.
- `reputation.py` — обрабатывает только `/profile <member_uuid>` и больше не
  конкурирует за exact `/profile`.
- Production-composed navigation test проверяет administrator/member, восемь
  actions и фактическое сохранение города без изменения имени.

## Критерии Jira

1. `/profile` и `Моя карточка` используют один presentation — выполнено.
2. Active owner видит восемь edit actions — выполнено прямыми assertions.
3. Выбранное поле сохраняется из следующего текста — выполнено для города;
   существующие registration tests проверяют полный набор полей.
4. Чужой, pending и inactive профиль не редактируется — сохранены application
   guards и существующие negative tests.
5. Второго конкурирующего exact `/profile` нет — reputation handler требует UUID.
6. Production-composed Dispatcher проверен для administrator и active member —
   выполнено в `test_production_navigation_requires_no_user_supplied_uuid`.
7. Targeted tests, Ruff и ty — выполнено.

## Проверки

- `uv run pytest -q --no-cov tests/unit/test_reputation_transport.py tests/integration/test_registration.py tests/integration/test_navigation.py`
  — `16 passed`.
- Ruff format/check — успешно.
- `uv run ty check` — успешно.
- `git diff --check` — выполняется перед заморозкой final-review snapshot.

Полная регрессия MVP не запускалась: это targeted production Bug после CB-16.
