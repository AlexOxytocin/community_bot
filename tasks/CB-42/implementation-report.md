# CB-42 — отчёт о реализации

## Результат

Раздел заданий переведён на свободное пользовательское создание без выбора
шаблона в основном Telegram-сценарии. Автор последовательно выбирает тип,
категорию, размер по времени, число исполнителей для группового задания,
награду за исполнителя, название, описание, критерии, материалы, срок и формат.
Перед публикацией показывается карточка предпросмотра с редактированием каждого
пункта и повторной проверкой полного резерва кредитов.

Утверждённая шкала размеров и наград реализована в домене:

- `⚡ XS` — до 15 минут, 1 или 2 кредита;
- `⭐ S` — 15-40 минут, 2, 3 или 4 кредита;
- `💎 M` — 40-75 минут, 4, 5, 6 или 7 кредитов;
- `🏆 L` — 75-120 минут, 6-10 кредитов;
- `👑 XL` — больше 120 минут, любое целое число больше 10.

Категории добавлены как настраиваемый DB-справочник для свободного создания:
`Продвижение`, `Оценка и тестирование`, `Коммуникация`,
`Обучение и разбор`, `Практическая помощь`, `Другое` и админская
`Развитие комьюнити`.

## Реализация

- Добавлены доменные типы `TaskKind`, `TaskTimeSize`, валидаторы награды,
  количества исполнителей, текстовых лимитов, материалов и результата.
- `task_creation_drafts` и `tasks` поддерживают nullable `template_id`,
  свободные поля карточки, `time_size` и статус `closed_for_new_performers`.
- Миграция `0020_freeform_task_creation.py` обновляет constraints и seed-ит
  новые freeform-категории, не удаляя исторические шаблонные категории.
- `TaskService.start/advance/preview/publish` поддерживает свободный wizard,
  legacy template-путь и idempotent publish replay.
- Telegram-интерфейс показывает inline-выборы, подсказки с лимитами, preview,
  edit-кнопки и карточки с категорией, типом, размером и полным резервом.
- Result validation для свободных заданий использует стандартный текстовый
  payload, а старые template-задания продолжают проверяться по schema шаблона.
- `Завершить набор` закрывает задание от новых исполнителей, возвращает
  свободные слоты, отправляет активным исполнителям выбор `Согласен отменить`
  или `Сдать результат` и корректно финализирует задание, когда активных
  исполнителей не осталось.
- Документация MVP и журнал решений синхронизированы с новой моделью заданий.

## Проверки

```text
ruff format --check                         passed
ruff check                                  passed
ty check src tests ops/verify_release_provenance.py
                                            passed
python -m compileall src tests              passed
git diff --check                            passed
pytest                                     478 passed, 1 skipped,
                                            coverage 80.11%
pytest --no-cov tests/unit/test_task_card.py tests/unit/test_task_transport.py tests/unit/test_tasks_domain.py
                                            26 passed
```

Целевые проверки дополнительно прогонялись отдельно:

```text
pytest --no-cov tests/integration/test_task_creation.py
                                            12 passed
pytest --no-cov tests/integration/test_output_driven_flows.py
                                            18 passed
pytest --no-cov tests/integration/test_catalog.py
                                            6 passed
pytest --no-cov tests/integration/test_pilot_readiness.py
                                            5 passed
```

Единственный skip в полном наборе существующий: `tests/unit/test_operations.py`
требует `bash` и `flock`. Порог покрытия 80% закрыт локально.

Production deploy и живая Telegram-проверка остаются отдельным release
acceptance после PR/merge, по правилам проекта.
