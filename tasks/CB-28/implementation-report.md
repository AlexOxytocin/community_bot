# CB-28 — отчёт о реализации

## Причина дефекта

CB-21 проверял application handlers, но называл это пользовательским E2E. Тест
вручную отправлял `/admin`, `nav:admin:registrations` и
`registration:approve:<uuid>`, не получая их последовательно из ответов бота.
Кроме того, меню проверялось как неполное подмножество кнопок. Поэтому отчёт
`9/9` и `12/12` не доказывал достижимость административного решения.

## Исправление

- в главное меню добавлена кнопка `Администрирование` с существующим серверным
  active-administrator gate;
- `Заявки` направлены в существующий registration presenter, который показывает
  полную карточку и кнопки `Одобрить`/`Отклонить`;
- команда `/registrations` и новый menu callback используют одну функцию;
- каноническое правило Telegram-тестов теперь запрещает считать вручную
  сконструированный callback доказательством UI/E2E;
- USER_GUIDE и BOT_INTERFACE синхронизированы.

## Доказательство

- production DB до исправления: владелец `administrator/active`, одна заявка
  `submitted`;
- production-composed тест проходит `/start` → текст кнопки
  `Администрирование` → callback `registration:list` из ответа → callback
  `registration:approve:<member_id>` из карточки → exact replay;
- результат: target `active`, ровно один `starting_grant`;
- неадминистратор и moderator по-прежнему получают отказ;
- целевой контур: `15 passed`, без skip/deselect;
- Ruff format/check, ty и `git diff --check` — успешно.

Полная регрессия MVP локально не повторялась: CB-28 является отдельным
production Bug после CB-16. Перед merge обязательны independent final review и
GitHub CI, после merge — production deploy и проверка текущей submitted-заявки.
