# CB-106 — независимое ревью frozen plan

Schema: `community_bot.plan_review.verdict.v1`

Status: approved

## Проверенные источники

- Jira `CB-106` прочитана read-only через Atlassian Rovo по ARI
  `ari:cloud:jira:c5d6d202-cdba-4d4e-88be-a3f927b6fc5b:issue/10138`;
  финальная область, восемь acceptance criteria, confirmed trace и запрет
  runtime-работы до отдельного owner freeze совпадают с планом.
- Прочитаны `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`, полный пакет роли
  `agents/plan-reviewer/{README.md,instruction.md,config.yaml}` и актуальный
  `tasks/CB-106/plan.md`. Для fast lane `1B` owner-provided source packet
  использован вместо отдельного `plan-source-context.md`.
- Сверены перечисленные source files: migration и `MemberModel`, domain/application/
  DB registration chain, application/DB reputation chain, web DTO/routes/mappers,
  все legacy-вхождения в `app.js`, notification/outbox timezone path и существующие
  API/browser oracles.

## Замечания по области

Обязательных замечаний нет.

- План удаляет только `availability`, пользовательский `timezone`, `current_goal`
  и `help_categories` из active web surface. `ProfileField`, registration steps,
  normalization и submit mapping остаются внутренним registration contract
  (`src/community_bot/domain/registration.py:63-104`,
  `src/community_bot/infrastructure/db/registration.py:31-42,580-604`).
- `help_categories_json` и `skill_tags_json` являются разными колонками
  (`migrations/versions/0004_registration_and_profiles.py:26-43`,
  `src/community_bot/infrastructure/db/models.py:112-121`). Запрет migration,
  rename и reinterpretation корректен; `skill_tags` остаётся в own/public
  projections, DTO и UI.
- Предложенные шесть runtime-файлов точны и не избыточны: две application
  projections, два DB mapper, web boundary и единственный Mini App renderer.
  Models, migrations, domain registration, notifications, outbox, CSS и новые
  abstractions для этой правки не требуются.

Ponytail verdict: `Lean already. Ship.`

## Замечания по логике решения

Обязательных замечаний нет.

- Web request сейчас принимает весь `ProfileField`
  (`src/community_bot/transport/web.py:145-149`). План сужает только transport
  type до закрытого allowlist, затем явно преобразует разрешённое значение в
  existing enum перед service call (`src/community_bot/transport/web.py:574-611`).
  Поэтому четыре legacy names отклоняются на validation boundary с 422, а domain
  registration flow не меняется.
- Response removals минимальны: четыре поля удаляются из `MeDto`/`_me_dto`, а
  три действительно существующих public поля — из shared
  `MemberDto`/`_member_dto` (`src/community_bot/transport/web.py:129-177,
  1619-1663`). `timezone` в public DTO уже отсутствует.
- Все достижимые UI-ветви названы: own editable rows
  (`src/community_bot/transport/static/app.js:856-935`), participant metadata
  fallback (`:1026-1063`) и public member detail (`:1255-1275`). Сохраняемая
  строка «Навыки» использует отдельный `member.skill_tags` и не зависит от
  `help_categories`.
- Internal notification timezone не проходит через удаляемый DTO/projection:
  `PostgresNotificationQueue` строит recipient из `MemberModel.timezone` и
  передаёт его в `DeliveryWindow.schedule(timezone_name=...)`
  (`src/community_bot/infrastructure/outbox/postgres.py:140-152,488-498,
  606-629`). Запрет изменений outbox/model сохраняет этот contract.
- Раздел API-совместимости честно фиксирует breaking removal отдельно для own
  GET, двух public member endpoints и legacy PUT, а также отсутствие data loss и
  неизменность `skill_tags`/notification contracts.

## Замечания по стратегии проверки

Обязательных замечаний нет.

- Existing API scenario `tests/integration/test_web_api.py:109-235` уже содержит
  successful supported update, validation, replay, concurrency и authoritative
  reread; его bounded adaptation может проверить четыре 422, сохранение
  соседнего supported field и неизменный persisted timezone без нового test file.
  Shared `MemberDto` mapper плюс list/detail calls
  (`tests/integration/test_web_api.py:1239-1255`) покрывают оба public response
  endpoints.
- Existing browser profile oracle
  `tests/browser/test_mini_app.py:1307-1595` проверяет DOM, editor, retry,
  focus/safe rendering, а existing participants oracle `:1598-1750` достигает
  catalog row и public detail. В сочетании с предписанным legacy-filled fixture
  и zero-occurrence source oracle этого достаточно для own rows, participant
  fallback и public detail без нового geometry/UI scope.
- Static oracle корректно разделяет удаляемый web contract и допустимые internal
  timezone consumers. Отдельный zero-occurrence запрет для `skill_tags` не
  вводится; существующие skills assertions сохраняются без переписывания,
  расширения или новой acceptance-функциональности.
- Тесты в ходе planning review не запускались по явному ограничению review
  packet; план требует targeted API/browser, Ruff, ty, diff/secret checks,
  Ponytail audit и независимый diff verdict после реализации.

## Обязательные исправления

Нет.

## Остаточные риски

- Approval относится только к frozen plan и текущим source contracts. При
  реализации browser oracle должен фактически пройти own profile, participant
  list fallback и public detail с legacy-filled fixtures; один static grep без
  этих существующих переходов не заменяет DOM/a11y/focus evidence.
- До отдельного owner freeze запрещены runtime edits и tests. После freeze
  остаются implementation, targeted gates, короткий independent diff verdict,
  PR/CI/merge и обязательный immutable release/public smoke для runtime diff.
