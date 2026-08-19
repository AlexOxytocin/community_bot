# CB-81 — независимое финальное ревью

Schema: `community_bot.final_review.verdict.v1`

Status: approved

## Проверенная область

- Уровень процесса: 3 — authenticated mutation, exact replay и конкурентная запись профиля.
- Exact base: `HEAD == origin/main == 7981d5b222843c9e8eda219b0244be2077f55635`; проверен полный незакоммиченный diff относительно `origin/main` и обновлённый `implementation-report.md`.
- Scope остался в owner-approved границе: один actor-native `ProfileField` через existing `RegistrationService`, validation, UoW, single-field DB setter, audit/receipt и authoritative reread; новый production path не обращается к conversation storage.

## Findings

### P1

Findings нет. Оба P1 предыдущего review закрыты.

### P2

Findings нет.

## Перепроверка предыдущих P1

### Сохранность editor state при delayed leaderboard render

Field, value, message и exact pending operation key теперь принадлежат existing profile screen state (`src/community_bot/transport/static/app.js:278-308`), а не заменяемой DOM closure. Поэтому full render из `loadLeaderboard` восстанавливает тот же draft и key.

Browser oracle `tests/browser/test_mini_app.py:702-727` намеренно оставляет leaderboard pending, получает PUT abort, завершает delayed leaderboard response и доказывает сохранность `Rosario`; последующие abort/`502`/retry используют один и тот же `Idempotency-Key`.

### PUT success и failure последующего safe member reread

После `PUT 200` authoritative `MeDto` немедленно применяется к `state.profile`, pending edit завершается и экран рендерится до дополнительного GET (`src/community_bot/transport/static/app.js:318-321`). Safe member projection перечитывается отдельно; её failure не попадает в mutation catch и не показывает ложную ошибку сохранения (`src/community_bot/transport/static/app.js:322-330`).

Тот же browser oracle задаёт member GET `503`, проверяет authoritative `Rosario`, отсутствие save-failure message и отсутствие нового key/повторной mutation после успешного PUT.

## Критерии приёмки

| Критерий | Результат | Доказательство |
|---|---|---|
| Actor-native own profile и server-side permission | пройден | `src/community_bot/transport/web.py:511-545`, `src/community_bot/application/registration.py:816-864`; client identity не принимается, active-owner gate выполняется под member lock. |
| Exact replay/conflict | пройден | update advisory gate и typed actor/field/fingerprint marker `src/community_bot/application/registration.py:964-983`; receipt/profile/audit находятся в одной transaction. |
| Concurrent different fields без lost update | пройден | registration identity gate, deterministic member row lock и single-column setter; PostgreSQL oracle подтверждает оба значения. |
| Authoritative reread | пройден | backend возвращает fresh `own_profile`; UI применяет returned `MeDto` до optional safe projection reread. |
| Conversation isolation | пройден | added production lines не содержат `ConversationState`/conversation helper references; integration oracle сохраняет foreign payload/revision. |
| Telegram compatibility | пройден | runtime Telegram methods/signatures/outcomes не изменены; integration oracle проверяет все восемь fields и `expected_input`. |
| HTTP/session/origin/body/error/no-store | пройден | route переиспользует existing secure session, exact Origin, bounded JSON, positive decimal key, closed DTO/error helpers и `Cache-Control: no-store`. |
| UI retry/stale screen/safe DOM | пройден | updated browser interleaving oracle, screen revision guards и construction через `element`/`textContent`. |

## Validation evidence

- Независимый recheck: `uv run pytest -q tests/browser/test_mini_app.py::test_profile_and_leaderboard_are_safe_retryable_and_stale_safe --no-cov` → `1 passed in 4.49s`.
- Evidence текущего post-fix worktree из `implementation-report.md`: full browser `7 passed`; named backend/browser/Telegram/route nodes `4 passed`; Ruff format/lint и `ty` — pass.
- Ранее green non-browser evidence остаётся применимым: post-fix изменения ограничены `app.js`, browser oracle и отчётом; backend runtime/test diff не менялся.
- `git diff --check origin/main --` → pass.
- Exact size: 5 production files, 4 test files, 268 net production LOC.
- Diff по dependencies, lockfile, migrations и DB models/schema отсутствует.
- Added production lines: conversation access — none; credential literals — none.

## Security, transaction и compatibility

- Actor берётся только из secure Web session; field принадлежит closed `ProfileField`, extra request keys запрещены.
- Update-ID gate обеспечивает exact command serialization; registration identity gate и member row lock сериализуют distinct operations одного actor.
- Profile field, audit и receipt commit атомарны; replay parser отвергает другой actor/field/fingerprint и чужой Telegram outcome до mutation.
- Single-field ORM setter не перезаписывает другие profile fields и не читает/меняет `conversation_states`.
- Новых секретов, side effects, dependencies, schema/domain rules или Telegram semantics нет.

## Ponytail verdict

Ceilings соблюдены: 5 production files, 4 test files, 268 net production LOC; новых service/repository/model/framework/dependency нет. Исправление P1 использует existing profile screen state и request helpers.

`src/community_bot/transport/web.py:L129: delete: повторный ConfigDict(extra="forbid") уже наследуется от _Dto. Ничего не заменяет.`

`net: -1 lines possible.`

Это необязательное локальное сокращение и не блокирует approval.

## Workflow и обязательные действия

- Plan review имеет точный `Status: approved`; implementation report обновлён после исправлений.
- Ветка `task/CB-81` основана на актуальной указанной base; несвязанных runtime/test files в diff нет.
- Обязательных исправлений по final review нет.

## Остаточный риск и неопределённость

- Независимо повторён только named browser scenario; результаты full browser, named four, Ruff и `ty` сверены по post-fix implementation evidence, но второй раз в этом review не запускались.
- Approval означает локальную готовность к следующему branch/PR gate. CI, merge, immutable release, production activation и public smoke ADR-0019 ещё не выполнены; Jira `Done` до green public smoke запрещён.
