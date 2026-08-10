# CB-9 — целевой план проверки

## Контур

- PostgreSQL 18 в существующем Compose/Testcontainers окружении;
- отдельная временная database на integration test;
- активная product-config version для level-aware сценариев;
- synthetic aiogram updates без сетевого Bot API.

## Сценарии

| № | Сценарий | Обязательный результат |
|---:|---|---|
| 1 | Upgrade пустой БД до head | Ровно 8 категорий и 8 template v1; UUID/code/version и schema воспроизводимы |
| 2 | `0004→0005→0004→0005` | Цикл проходит, seed восстанавливается без дублей |
| 3 | Проверка manifest и обеих Schema | Draft 2020-12 schemas валидны, обязательные поля и safety copy присутствуют |
| 4 | Level 1 и level 2 с намеренно stale cache | Каждый видит только active templates с `minimum_level <=` актуальному resolver |
| 5 | Category/format filters | Возвращаются только выбранная категория и совместимые `online/offline/any` |
| 6 | Keyset pages 2–3 элементов; между страницами публикуется новая version уже показанного code, а перенос code в другую категорию отклоняется | Логический template не повторяется, ещё не показанные code не пропускаются; category identity и cursor tampering защищены |
| 7 | Отключение/включение категории | Новая выдача скрыта/возвращена, category/template/history rows не удалены |
| 8 | Отключение/включение template code | Активна не более одна последняя версия, старые версии остаются читаемы по ID |
| 9 | Изменение reward | Создана v2, v1 неизменна, активна v2, будущий task reference может удерживать v1 |
| 10 | Два concurrent exact retry одного admin update | Update gate пропускает одного writer; второй возвращает сохранённый outcome до catalog gate, version/audit/receipt не дублируются |
| 11 | Два разных concurrent version writers | Catalog gate завершает оба без deadlock, номера последовательны, активна ровно последняя версия |
| 12 | Member/moderator/paused admin мутируют каталог | Permission denied до изменений, audit и receipt отсутствуют |
| 13 | Невалидный template draft/schema | Ошибка до INSERT/deactivation; прежняя активная версия сохраняется |
| 14 | Input payload без required/с неверным type | Structured validation error до вызова downstream domain-command spy |
| 15 | Валидные input/result payload | Возвращаются без потери данных; неизвестные поля запрещены |
| 16 | Direct SQL UPDATE content/DELETE | DB отклоняет изменение; допускается только сервисное переключение `is_active` |
| 17 | `/catalog` + page callback | Карточки и следующая страница отображаются; callback не превышает 64 bytes |
| 18 | Telegram admin commands/replay/invalid args | Только active admin меняет состояние; ошибки не создают частичных эффектов |
| 19 | Контроль готового diff | Targeted pytest, Ruff, ty, diff-check и secret scan дают exit 0 |

## Соответствие Jira

- active и доступные шаблоны: 4, 5, 7, 8, 17;
- пагинация: 6, 17;
- новая стоимость — новая версия: 9–11, 16;
- inactive category без удаления истории: 7, 16;
- обязательные поля до доменной команды: 3, 13–15;
- воспроизводимые seed и миграции: 1–3.

## Ограничение

Полный `uv run pytest` продукта не является барьером CB-9 и остаётся в CB-16.
Из существующего контура запускаются только прямо затронутые tests для database
UoW, product config level resolver, architecture boundaries и settings. Баги,
найденные до завершения CB-9, исправляются в этой ветке без отдельных Jira-задач.
