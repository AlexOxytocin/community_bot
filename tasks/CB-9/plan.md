# CB-9 — план реализации каталога и версионируемых шаблонов

## Цель

Дать активному участнику проверяемый каталог только доступных ему шаблонов и
подготовить устойчивый контракт для CB-10: выбранная версия неизменяема,
обязательные данные проверяются до доменной команды, а административные
изменения не переписывают историю.

## Уровень процесса

Уровень 3: новая схема данных, seed, JSON Schema, конкурентные
административные изменения и публичная граница для следующих задач. Нужны
`plan-source-context.md`, независимый plan review, целевые unit/PostgreSQL/
Telegram smoke-проверки, `implementation-report.md` и один final review
полностью готового staged diff. Нового ADR не требуется: структура прямо
следует D-007, D-011, ADR-0005 и канонической модели каталога.

## Область

- доменные значения и проверки категории, формата, версии, награды, времени,
  уровня, схем и безопасного шаблона;
- application API просмотра, keyset-пагинации, получения версии для создания
  задания, проверки input/result payload и административных мутаций;
- PostgreSQL-модели, миграция `0005`, seed v1, ограничения, аудит,
  идемпотентность и защита от конкурентных изменений;
- Telegram `/catalog`, callback пагинации и минимальные admin-команды включения,
  отключения и выпуска новой версии с другой наградой;
- синхронизация документации каталога, интерфейса, модели данных и тест-плана.

## Вне области

- создание/публикация экземпляра задания и резерв — CB-10;
- принятие, выполнение и расчёт — CB-11/CB-12;
- community-card, споры, алерты и outbox;
- произвольный редактор JSON Schema через Telegram;
- полная регрессия продукта — CB-16.

## Данные и неизменяемость

### `task_categories`

UUID, уникальный `code`, русские name/description, icon, sort_order и
`is_active`. Прямой SQL может менять только `is_active`; удаление и изменение
идентичности/копирайта запрещает trigger. Административный сервис выполняет
изменение под общим catalog mutation gate и пишет audit.

### `task_templates`

UUID, category FK, `code`, `version`, русские name/description/instructions/
completion criteria, JSONB input/result schemas, reward, minutes, format,
minimum level, maximum performers, moderation flag, `is_active`, timestamps и
`UNIQUE(code, version)`.

Trigger запрещает DELETE и изменение любого поля, кроме `is_active`. Partial
unique index гарантирует не более одной активной версии одного `code`.
Публикация версии в одной транзакции:

1. Telegram update gate;
2. exact update receipt и немедленный replay без catalog/member locks;
3. catalog mutation advisory gate;
4. actor member lock и проверка active administrator;
5. блокировка версий `code`;
6. полная проверка новой версии и обеих JSON Schema;
7. деактивация текущей версии, INSERT `version = max + 1`, audit и receipt;
8. один commit.

Все изменяющие catalog handlers используют этот общий порядок. Retry одного
update сериализуется на update gate и возвращает сохранённый результат до
catalog gate. Два разных конкурентных изменения сериализуются catalog gate и
создают последовательные версии; последняя становится единственной активной.
Старые строки и будущие FK заданий остаются неизменными.

### Seed

`migrations/data/task_catalog_v1.json` содержит восемь категорий и восемь
шаблонов из таблицы контекста. Миграция `0005` проверяет форму manifest,
вставляет фиксированные UUID/version 1 и создаёт ограничения до seed. Повторный
`upgrade head` безэффектен; downgrade удаляет только таблицы этой миграции.
Manifest после публикации миграции не редактируется: новый seed выпускается
новой миграцией и новой версией шаблонов.

## JSON Schema и граница CB-10

Добавляется `jsonschema` с Draft 2020-12. Разрешается корневая object-схема с
явными `properties`, `required` и `additionalProperties: false`; удалённые `$ref`,
исполняемый код и сетевые обращения не используются. При создании версии обе
схемы проходят `check_schema` и локальные ограничения размера/глубины.

Публичный `CatalogService.template_for_creation(...)` возвращает точную
активную версию только active member с достаточным актуальным уровнем и активной
категорией. `validate_input_payload` и `validate_result_payload` возвращают
нормализованный payload или структурированную ошибку до конструирования
будущей команды задания. CB-10 хранит `template_id` этой строки; повторное
чтение старой версии не зависит от текущего `is_active`.

## Просмотр и пагинация

`CatalogQuery` поддерживает optional category code, формат `online|offline|any`
и limit до 20. Фильтр `online` включает `online` и `any`, `offline` — `offline`
и `any`; отсутствие фильтра показывает все форматы.

Листинг:

- требует active member;
- разрешает уровень через текущую product-config version, не через stale cache;
- выбирает только active category + единственную active template version с
  `minimum_level <= resolved level`;
- сортирует по стабильному логическому ключу
  `(category.sort_order, template.code)`;
- использует валидируемый keyset cursor с этими значениями, а не OFFSET.

`template.code` глобально идентифицирует логический шаблон, а category sort_order
неизменяем. Поэтому публикация новой version уже показанного code не меняет его
keyset-позицию и не возвращает шаблон повторно на следующей странице. Новая
версия ещё не показанного code видна на своей позиции. Деактивация между
запросами может только скрыть запись и не возвращает уже пройденную. Telegram
показывает шесть карточек на страницу и сохраняет фильтры в callback.

## Административный интерфейс

- `/catalog_category <code> on|off`;
- `/catalog_template <code> on|off` — включает последнюю версию или отключает
  текущую;
- `/catalog_template_reward <code> <1..4>` — клонирует активную/последнюю
  версию с новой наградой и следующим номером версии.

Полный application API выпуска версии принимает все поля и нужен следующим
задачам/будущей админке. Telegram намеренно не становится JSON-редактором.
Неавторизованные, невалидные и replay-команды не оставляют частичных эффектов.

## Изменяемые компоненты

- `src/community_bot/domain/catalog.py`;
- `src/community_bot/application/catalog.py`;
- `src/community_bot/infrastructure/db/catalog.py`, `database.py`, `models.py`;
- `src/community_bot/transport/telegram/catalog.py`;
- `migrations/versions/0005_task_catalog.py` и
  `migrations/data/task_catalog_v1.json`;
- зависимости/lock, документация MVP и `tasks/CB-9/*`;
- unit и PostgreSQL integration tests каталога, synthetic aiogram smoke.

## Риски и меры

- Конкурентные версии: единый advisory gate, row locks, unique constraints и
  прямой timeout-тест двух writers.
- Переписывание истории: DB-trigger, старые version rows, direct SQL negative
  tests и FK-ready identity.
- Stale level cache: только `resolve_member_level` по active config.
- Неконтролируемая Schema: локальный Draft 2020-12 validator, пределы размера/
  глубины, без remote resolver.
- Callback больше лимита Telegram: компактный cursor и тест длины до 64 bytes.
- Процессный перегрев: один review полного плана, один целевой контур готового
  кода и один final review; полная регрессия не запускается.

## Критерии готовности

- закрыты все шесть Jira AC;
- seed/empty DB и `0004→0005→0004→0005` воспроизводимы;
- целевые unit, PostgreSQL integration и synthetic Telegram smoke проходят без
  skip/deselect;
- Ruff, ty, diff/secret scan чисты;
- `implementation-report.md` связывает каждый AC с реальным тестом;
- final review готового staged diff имеет `Status: approved`.
