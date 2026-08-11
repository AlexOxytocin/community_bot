# CB-26 — отчёт о реализации

## Результат

Технический вопрос про IANA timezone удалён из обычного пути регистрации. После
ввода однозначного города бот атомарно сохраняет и город, и canonical timezone,
после чего сразу спрашивает краткое описание. Уже начатые анкеты на шаге
timezone принимают обычное название крупного города.

## Причина production-дефекта

- Доменная валидация принимала только точный IANA identifier.
- Unit, integration и E2E проверки использовали один и тот же технический
  happy path `Europe/Moscow`.
- Негативная проверка использовала только искусственный `Mars/Olympus` и не
  воспроизводила человеческий ввод `Buenos Aires`.
- Поэтому зелёный тестовый контур подтверждал внутренний формат, но не
  пользовательский сценарий регистрации.

## Изменения

- Добавлен детерминированный resolver города без внешнего API. Он нормализует
  регистр, пробелы, дефисы, подчёркивания и диакритику, использует pinned tzdata
  и не выбирает timezone при нескольких динамических совпадениях.
- Для основных городов пилота добавлены русские aliases; `Москва`,
  `Буэнос-Айрес` и `Buenos Aires` получают canonical timezone.
- Ответ `city` сохраняет timezone в той же транзакции и пропускает ручной шаг,
  когда результат однозначен.
- Fallback принимает обычный крупный город либо точный IANA identifier и выдаёт
  конкретную пользовательскую подсказку.
- Обновлены пользовательский flow, интерфейс и прежние синтетические E2E,
  которые больше не подставляют технический timezone вместо пользователя.

## Критерии Jira

| Критерий | Статус | Доказательство |
|---|---|---|
| `Москва` → `Europe/Moscow` без ручного шага | Выполнено | Unit resolver, application flow и полный pilot exchange |
| `Буэнос-Айрес`/`Buenos Aires` → canonical Argentina timezone | Выполнено | Параметризованный unit test и production-composed Telegram registration |
| Существующий timezone draft принимает `Buenos Aires` | Выполнено | PostgreSQL + production Dispatcher test с exact replay чтением результата |
| Неизвестный город сохраняется и включает понятный fallback | Выполнено | Integration state assertion и новый Telegram prompt |
| Exact IANA identifier остаётся допустимым | Выполнено | Unit normalization для `Europe/Moscow` |
| Resolver детерминирован и не требует внешнего API | Выполнено | Только stdlib `zoneinfo`, pinned tzdata и явная canonical-карта; сетевых вызовов и offset-эвристик нет |
| Replay/stale-step/idempotency не регрессируют | Выполнено | Exact replay существующего draft и targeted stale-step test |
| Targeted tests, Ruff, ty и final review | В процессе | Автоматические проверки зелёные; independent final review выполняется после заморозки diff |

## Проверки

- Targeted registration + production-composed Telegram + full exchange: успешно,
  без skip и deselect.
- Ruff format/check — успешно.
- `uv run ty check` затронутых production-модулей — успешно.
- `git diff --check` — успешно.
- Полная регрессия MVP не повторяется: CB-26 — отдельный production Bug после
  общей регрессии, а проверяемая область закрыта целевым пользовательским
  контуром.

## Оставшийся риск

Свободное название любого населённого пункта мира нельзя надёжно превратить в
timezone без географического справочника. Resolver поэтому не угадывает
неоднозначный результат, а переводит пользователя в понятный fallback. Это
сознательная граница MVP, не скрытый отказ.
