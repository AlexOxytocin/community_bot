# CB-96 — эскалация после двух final review

Две независимые проверки завершились `changes_requested`. Причины повторного
false-green: browser oracle фиксировал `T01` до завершения bootstrap/revalidation;
transition oracle не проверял полное поведение `production_ui_local` и
`existing_http_connected`; класс навигации дублировался вручную и разошёлся с
контрактом для `P05`.

Выбран один консолидированный корректирующий цикл: дождаться settled connected
DOM, проверять переходы через реальные source controls и вывести navigation
parity из контракта. Новая архитектура, engine adapter или расширение области не
нужны. После локальных gates требуется новая независимая final-проверка.

## Решение владельца

По Jira comment `10355` полный scope из `103` UI ID сохраняется. Сохраняются
`8` предметных semantic layouts и `11` route patterns; одинаковый fallback для
разных экранов удаляется, а каждый ID получает собственное предметное
содержание. Решение не вводит `103` отдельных components, routes или tests.
Неизвестное production-состояние закрывается безопасно и не изображает
авторитетный success.
