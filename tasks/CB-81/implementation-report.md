# CB-81 — отчёт реализации

**Статус:** реализация и локальные gates готовы к независимому final review;
commit, push, PR, merge, release и production deploy ещё не выполнялись.

**Baseline:** `7981d5b222843c9e8eda219b0244be2077f55635` (`origin/main`).

## Результат

На существующем экране «Профиль» добавлено редактирование ровно одного
существующего `ProfileField` за запрос. Web transport передаёт server actor в
one-shot `RegistrationService.update_own_profile_field`, а после commit выполняет
fresh `own_profile` и возвращает существующий `MeDto`.

Новый путь не вызывает Telegram `begin_profile_field_edit` или
`save_profile_field` и не обращается к `conversation_states`. Новых domain rules,
полей, tables, migrations, models, repositories, services, dependencies,
frameworks или generic schema renderer нет.

## Критерии и доказательства

| Критерий | Статус | Доказательство |
|---|---|---|
| Actor-native own profile | выполнен | `PUT /api/v1/me/profile` берёт actor только из secure session, запрещает extra DTO fields и вызывает один existing `RegistrationService`; client identity не принимается. |
| Existing domain/UoW reuse | выполнен | Используются `ProfileField`, `normalize_profile_value`, `require_profile_owner`, existing registration identity/member locks, audit, receipt, commit и existing `_set_member_profile_field`. |
| Exact replay | выполнен | Existing receipt outcome хранит typed marker `web_profile_update:<actor>:<field>:<fingerprint>` без schema change. Exact marker replay не мутирует данные; тот же key с другим command или чужим Telegram marker даёт `409`. |
| Conversation isolation | выполнен | `test_web_profile_update_is_exact_concurrent_and_conversation_safe` сохраняет active foreign `task` flow с exact payload/revision после success, replay, conflict, invalid request и concurrent updates. Production path не импортирует conversation helper/model. |
| Нет lost update разных fields | выполнен | Тот же PostgreSQL oracle одновременно обновляет `city` и `current_goal`; identity/member locks сериализуют commands, single-column setter сохраняет оба значения. |
| Authoritative reread | выполнен | Route после successful command заново вызывает `registration.own_profile(actor)`; HTTP oracle и browser journey проверяют server-normalized/returned value. |
| Telegram compatibility | выполнен | Existing integration loop вызывает прежние `begin_profile_field_edit`/`save_profile_field` signatures для всех восьми fields и проверяет прежние outcomes и `expected_input`. Их implementation не изменена. |
| Minimal vanilla UI | выполнен | Existing profile card получил hard-coded allowlist восьми fields, native `select`/`textarea`, safe text rendering и stable idempotency key при network/`5xx` retry. Browser oracle проверяет network abort, non-JSON `502`, exact same key, success и новый key после validation change. |

## Проверки текущего worktree

- `uv run ruff format --check .` — `314 files already formatted`.
- `uv run ruff check --output-format=concise .` — pass.
- `uv run ty check src tests ops` — pass.
- Named targeted nodes — `4 passed`:
  Web PostgreSQL isolation/concurrency, Telegram compatibility, closed route set
  и browser profile journey.
- `uv run pytest -q tests/browser --no-cov` — `7 passed`.
- `uv run pytest -q -m "not integration and not browser" --no-cov` —
  `421 passed, 161 deselected`.
- CI-equivalent non-browser suite
  `uv run pytest -q -m "not browser"` — `575 passed, 7 deselected`, coverage
  `82.56%`, exit `0`, `363.31s`.
- Первый long-running session закрылся без доставленного exit/output; process
  inspection подтвердил отсутствие task-owned `uv/pytest`. Ничего не
  завершалось принудительно. Тот же gate был повторён последовательно один раз
  и дал приведённый выше воспроизводимый green result.
- `git diff --check` — pass.
- Diff по `pyproject.toml`, `uv.lock`, migrations/schema paths — отсутствует.
- Added-lines credential literal scan — pass.

После последнего полного non-browser gate изменились только browser retry oracle
и reuse existing `retryableSubmissionError`, затем заново прошли полный browser
suite, named nodes, Ruff и `ty`. Non-browser runtime/backend diff после green
suite не менялся, кроме type-only объявления existing `get_member` в UoW
protocol.

## Ponytail и размер

Production diff остаётся в ровно пяти existing files и составляет **268 net
lines**:

- `application/registration.py`: +88 net;
- `infrastructure/db/database.py`: +15 net;
- `infrastructure/db/registration.py`: +16 net;
- `transport/static/app.js`: +96 net;
- `transport/web.py`: +53 net.

Это ниже owner stop trigger `>5 production/test files` и около 300 net production
LOC. Tests изменены в четырёх existing files. Новый retry mechanism не добавлен:
profile editor переиспользует existing `submissionRequest`,
`retryableSubmissionError`, operation-key generator и safe DOM helpers.

## Исправления по independent final review

Первый final review получил `changes_requested` по двум UI interleavings; backend
findings не было.

- Draft, error message и pending idempotency key перенесены из заменяемой DOM
  closure в existing profile screen `state`. Поздний leaderboard render теперь
  сохраняет введённое значение и exact key после ambiguous network failure.
- `PUT 200` считается завершённой mutation: returned authoritative `MeDto`
  применяется немедленно с предыдущей safe member projection. Последующий member
  GET только освежает projection; его `5xx` не показывает ложный save failure и
  не запускает второй PUT.
- Browser oracle теперь явно выполняет `member success → PUT abort → delayed
  leaderboard success → same-key retry`, затем non-JSON `502 → same-key retry →
  PUT 200 → member GET 503` и доказывает authoritative value без второго PUT.

После исправлений повторены: named nodes `4 passed`, полный browser suite
`7 passed`, Ruff format/lint и `ty` — pass.

**KEEP:** existing RegistrationService/UoW, single-field ORM setter, receipt,
locks, validation, secure actor session и static shell.

**DO NOT ADD:** conversation/revision framework, persistence/schema, domain
rules, generic editor, dependencies или Telegram semantics.

## Остаточный риск и следующий шаг

Изменения ещё не опубликованы. Следующий gate — независимый final review exact
diff и evidence. После `approved`: commit/push/PR, green remote CI/review, merge,
exact immutable release, serialized production activation и public smoke; Jira
`Готово` только после green smoke.
