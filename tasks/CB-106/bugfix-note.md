# CB-106 — compact bugfix note

## Симптом

Mini App показывала и позволяла редактировать четыре legacy profile fields:
`availability`, пользовательский `timezone`, `current_goal` и
`help_categories`; те же значения продолжали входить в own/public web DTO.

## Причина

Общий registration enum и исторические DB columns по-прежнему автоматически
использовались как web editable/public allowlist. Static profile/member
renderers напрямую читали все четыре keys. При этом internal timezone имеет
отдельного действующего consumer: notification scheduling.

## Правка

- Web request allowlist закрыт на `display_name`, `city`, `short_bio`,
  `skill_tags`; legacy field names fail-closed на transport validation.
- Четыре keys удалены из own DTO/projection; три реально публичных keys удалены
  из member DTO/projection.
- Legacy rows, participant availability fallback и public member detail rows
  удалены из единственного Mini App renderer.
- `ProfileField`, registration flow, models/columns/migrations,
  `MemberModel.timezone` notification path и весь `skill_tags` contract не
  менялись.

Production diff: 4 runtime files, `+4/-31`; новых runtime files,
abstractions, dependencies, schema/model/migration changes: `0`.

## Проверка

- API exact profile oracle: `1 passed` (`--no-cov`).
- Browser own/participant/public-detail oracles: `2 passed` (`--no-cov`).
- Unit web mapper oracle: `1 passed` (`--no-cov`).
- Node syntax, Ruff check/format, ty changed production scope и
  `git diff --check`: green.
- Static oracle: legacy client identifiers/labels в `app.js` — `0`; legacy
  profile fields в web DTO definitions — `0`.
- Независимый short diff review: `Status: approved`; повторный focused API +
  browser run — `3 passed`; Ponytail: `Lean already. Ship.`

## Риск

Удаление keys и PUT values намеренно breaking для legacy web clients; владелец
принял atomic Mini App/backend release без compatibility adapter. Persisted
данные не удаляются. Full regression выполняет CI; production evidence будет
добавлено после immutable release и smoke.
