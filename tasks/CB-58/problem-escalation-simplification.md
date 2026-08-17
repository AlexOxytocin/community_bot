# CB-58 — эскалация компактной редакции

## Основание

Новая компактная редакция получила два последовательных `changes_requested`:

1. первая проверка нашла отсутствующие specimens, broken hover contrast,
   неполный Telegram fallback и фактически незагруженный Manrope;
2. повторная проверка подтвердила исправление этих пунктов, но обнаружила
   cascade hover → pressed, неполную pair matrix fallback, drift overlay и
   неучтённый font bundle.

Обе попытки сохранены:

- `plan-review-simplification-attempt-1.md`;
- `plan-review-simplification-attempt-2.md`.

## Корневая причина

Сокращение правильно удалило производную спецификацию, но contract tests
проверяли отдельные token values и HTML markers, а не композицию состояний:

- CSS cascade не является суммой независимо валидных цветов;
- provider overlay создаёт смешанные provider/base pairs;
- preview дублирует semantic values и может расходиться с JSON;
- logical artifact inventory не включил binary asset.

## Один консолидированный fix

1. Поставить active/pressed rules после pointer hover и проверить computed
   styles реальным pointer down для primary, secondary и danger.
2. Проверять все пары, образующиеся после provider overlay, включая state,
   status и surface roles; accepted-but-unsafe counterexample обязан вызвать
   полный fallback.
3. Добавить theme-specific `--overlay` и compact JSON ↔ CSS semantic parity
   test.
4. Зафиксировать font/license как части preview bundle с size/hash gates.

Новых компонентов, token generators и runtime resolver в CB-58 не добавлять.
После fix разрешена одна терминальная независимая проверка. Новый
`changes_requested` или `blocked` останавливает CB-58 для решения владельца.
