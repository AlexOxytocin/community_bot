# CB-27 — план исправления wall-clock зависимости notification tests

## Цель

Сделать notification integration tests независимыми от времени запуска CI, не
меняя production-политику окна доставки `[09:00, 21:00)`.

## Изменения

1. Разрешить test seed принимать явный aware timestamp.
2. В сценариях немедленной доставки и reminder invalidation использовать
   фиксированный UTC timestamp внутри окна участника с timezone `UTC`.
3. Сохранить реальные проверки переноса за границы окна в доменных unit tests.

## Проверка

- два исходно падавших теста и readiness cleanup;
- весь `tests/integration/test_notifications.py`;
- Ruff, ty и независимый final review;
- полный PostgreSQL suite выполняет GitHub CI.

Production-код, схема БД и notification policy не меняются.
