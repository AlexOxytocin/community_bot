# CB-96 — независимая final-проверка, попытка 02

Status: changes_requested

## Проверенные замечания

1. Финальный устойчивый DOM `T01` при `375×812` пуст: browser mock возвращает
   `items=[]`, а проверка фиксирует промежуточный render adapter до завершения
   bootstrap/revalidation. Нужны содержательный mock существующего connected
   `/api/v1/tasks`, ожидание settled DOM, проверка видимой предметной карточки и
   screenshot именно финального состояния — без production fixture hook.
2. Oracle переходов неполон. Все `93 production_ui_local` edge должны идти
   кликом по реальному source control и проверять объявленные `screen_marker`,
   state, exact history, focus, `safe_fallback` и `request_count`. Все `10
   existing_http_connected` edge должны исполняться реальными кликами с mock
   endpoint/method/count; source-text grep не является поведенческим evidence.
3. Контракт задаёт `P05.navigation_class=context`, но runtime и тесты считают
   экран root. Нижняя навигация должна быть скрыта, а логический Back и возврат
   focus — видимы и проверены parity assertion из контракта, без отдельного
   ручного списка root-экранов.

## Требуемая коррекция

Один консолидированный цикл: закрыть три причины выше, повторить exact
`103/17/26/11/128` и `93/25/10`, запустить Node syntax, targeted Ruff,
`git diff --check` и весь browser-файл, затем снять девять финальных
`375×812` screenshots вне репозитория. Результат остаётся локальным и требует
новой независимой проверки.
