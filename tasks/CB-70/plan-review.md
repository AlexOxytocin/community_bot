# CB-70 — независимая проверка плана

**Status: approved**

Проверено содержание `plan.md` с reviewer hash `38A0BD90…`; после вердикта в
плане изменена только строка статуса. Итоговый hash
`97736974EF0E5203800A2F34BFA160D4E91F847A9E5CE9A5DD85CCF22CDDCAC0`.
Блокирующих замечаний нет.

## Подтверждённые границы

- Пять routes переиспользуют existing `start/advance/edit/preview/publish`;
  второго engine, form/schema framework, migration или persistence owner нет.
- Actor-native web path не принимает Telegram identity и не изменяет
  `conversation_states`; permissive Telegram edit semantics сохранены.
- Test-run isolation остаётся fail-closed и не блокирует участника навсегда:
  direct mismatched access запрещён, valid start атомарно supersede-ит старый
  current draft без чтения или копирования payload.
- Current draft и preview строятся в одной transaction/revision. Просроченный
  preview после restart возвращает safe `needs_edit=true`, а web edit проверяет
  exact revision под draft lock.
- Same-key replay имеет один receipt; different-key business retry публикации
  возвращает тот же immutable `task_id` без повторных reserve/audit/outbox
  effects и сохраняет existing отдельный receipt.
- Domain validators остаются владельцами reward, URL, deadline, slots и
  format/city. DTO/DOM не публикуют private/internal поля и raw schema.
- Test matrix покрывает scope transitions, restart/recovery, stale/conflict,
  concurrent publish, privacy, Telegram regression и один browser journey.

## Ponytail

`Lean already. Ship.`

## Остаточный риск

Заявленные transaction/replay/privacy свойства должны быть подтверждены
runtime diff и запланированными PostgreSQL/browser gates. До merge CB-69 общие
`web.py` и static assets остаются stop gate для реализации CB-70.
