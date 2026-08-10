# CB-9 — повторное ревью плана

Status: approved

Схема: `community_bot.plan_review.verdict.v1`.

## Проверенные источники

- актуальные `tasks/CB-9/plan-source-context.md`, `plan.md`, `test-plan.md`;
- замечания P-001 и P-002 предыдущего ревью;
- ранее проверенные шесть критериев Jira `CB-9` и текущие UoW/level resolver contracts.

## Область повторной проверки

Проверены только консолидированные исправления P-001 и P-002 и отсутствие регрессии в покрытии шести Jira AC.

## Логика решения

### P-001 — закрыто

Все изменяющие catalog handlers теперь используют единый порядок `update gate → exact receipt → catalog mutation gate → actor member lock → code versions → mutation + audit + receipt → one commit`. Replay возвращается до catalog/member locks. Это согласуется с общим Telegram UoW и не создаёт второго lock order. Сценарий 10 запускает два concurrent exact retry одного admin update и проверяет один writer, сохранённый outcome и отсутствие дублей version/audit/receipt.

### P-002 — закрыто

Keyset использует стабильный логический ключ `(category.sort_order, template.code)` без UUID строки версии. Поэтому reward-version уже показанного logical template сохраняет позицию и не появляется повторно после курсора. Сценарий 6 прямо вставляет такую версию между страницами и проверяет отсутствие повтора показанного code, пропуска ещё не показанных code и отклонение повреждённого cursor.

## Стратегия проверки

Карта шести Jira AC не регрессировала: active/level/category visibility покрыта сценариями 4, 5, 7, 8 и 17; пагинация — 6 и 17; новая стоимость и неизменяемая история — 9–11 и 16; inactive category — 7 и 16; обязательные поля до downstream command — 3 и 13–15; seed 8+8 и миграционный цикл — 1–3. Целевого контура достаточно для MVP без полной регрессии продукта.

## Обязательные исправления

Отсутствуют.

## Остаточные риски

- Фактическая реализация должна сохранить заявленный lock order и глобальную идентичность `template.code`; это проверяется целевыми PostgreSQL-тестами и final review.
- Русский safety copy и точное содержимое seed проверяются по готовому manifest в final review.
