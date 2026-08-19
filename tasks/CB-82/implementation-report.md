# CB-82 — отчёт о реализации

## Статус

Локальная реализация и обязательные automated gates завершены. Ветка готова к
независимому финальному ревью; PR, merge, release, production activation,
public smoke и terminal Jira transition ещё не выполнялись.

## Что изменено

- В существующем `ReputationService` четыре karma use case получили
  actor-native Web identity и versioned safe exact replay через существующий
  receipt. Legacy Telegram identity path, draft/upsert/history/audit/signals и
  aggregate остаются теми же.
- `begin_karma_draft` теперь fail-closed сохраняет любой существующий
  non-karma conversation owner до общего `claim_text_flow`.
- Добавлен один strict action endpoint
  `POST /api/v1/members/{member_id}/karma-vote`: actor только из Web session,
  target из path и server-owned draft, receipt scope только по actor/key,
  payload — в fingerprint.
- Existing leaderboard открывает safe member profile с минимальной native form.
  После confirm comment очищается, а aggregate обновляется отдельным
  authoritative `GET /api/v1/members/{member_id}`.
- Новых domain rules, schema, migrations, models, repositories, services,
  dependencies, notifications, frameworks или state manager нет.
- Independent final review воспроизвёл reciprocal begin deadlock: sanction check
  удерживал actor row до общего pair gate. Lock order исправлен на
  `identity → reputation pair → sanction → deterministic member rows`; новый
  PostgreSQL oracle одновременно проводит две встречные Web-оценки через begin
  и confirm без deadlock.

## Отклонения от плана

Нет. Stop gates нового persistence owner/domain/schema не сработали. CSS не
менялся: существующих компонентов оказалось достаточно. Ponytail-review:
`Lean already. Ship.`

## Критерии приёмки и доказательства

| Критерий | Статус | Реализация | Проверка и доказательство |
|---|---|---|---|
| Existing profile/leaderboard target и один compact API | Закрыт локально | Safe member profile, одна action route и одна vanilla form | Browser profile/leaderboard/karma test; closed route-set unit test |
| Actor только из Web session, target server-validated | Закрыт локально | Closed DTO не принимает actor; target сверяется с draft на каждом action | Integration: actor field rejected, hidden/absent parity, foreign target conflict |
| Reuse existing ReputationService/UoW | Закрыт локально | Actor-native seam внутри четырёх существующих use cases | Full diff; mixed Web/legacy concurrent confirm test |
| Revision, eligibility, fresh authorization и concurrency | Закрыт локально | Existing rules/locks плюс fresh Web confirm restriction check и pair-first lock order | Stale/fingerprint conflicts, post-draft restriction, one-winner и reciprocal no-deadlock tests |
| Exact replay без duplicate effect | Закрыт локально | `karma_web_v1` safe outcome в existing receipt | Delayed replay begin/save/comment/confirm; exact vote/history/audit/receipt counts |
| Foreign conversation flows не перезаписываются | Закрыт локально | Local fail-closed guard в karma persistence adapter | Table-driven exact state test для четырёх owners |
| Authoritative safe reread после confirm | Закрыт локально | Confirm outcome отделён от subsequent safe profile GET | API aggregate assertion и browser refresh assertion |
| Privacy DOM/API/error boundary | Закрыт локально | Safe DTO, generic allowlisted codes, text-only DOM, comment cleanup | API privacy assertions; browser DOM/console assertion |
| Immutable release, activation и public smoke до Jira Done | Ожидает delivery | Runtime diff локально готов | `test-plan.md` выполняется только после merge/release/activation |

## Проверки

| Проверка | Команда или сценарий | Результат |
|---|---|---|
| Formatting | `uv run ruff format --check .` | 321 files formatted |
| Lint | `uv run ruff check .` | Passed |
| Type check | `uv run ty check src tests ops` | Passed |
| Full non-browser suite после lock-order fix | `uv run pytest -m "not browser"` | 579 passed; coverage 82.31% |
| Full browser suite | `uv run pytest tests/browser --no-cov` | 8 passed |
| Post-review task-creation/Karma browser regression | full browser suite after UI control-lock fix | 8 passed |
| Targeted foreign-flow/mixed concurrency | targeted `test_reputation.py` selection | 2 passed |
| Reciprocal Web begin/confirm concurrency | targeted `test_reputation.py` selection | 2 drafts, 2 votes/history, no deadlock |
| Targeted Web karma matrix | targeted `test_web_api.py` selection | 2 passed |
| JavaScript syntax | `node --check src/community_bot/transport/static/app.js` | Passed |
| Diff formatting | `git diff --check` | Passed |

## Документация

Обновлён task package: source context, approved plan review, implementation
plan, manual production test plan и этот implementation report. Новый ADR не
требуется: реализация следует принятым ADR-0014/0016/0017/0019.

## Ограничения и остаточные риски

- Existing 63-bit receipt hash имеет прежний теоретический collision risk;
  mismatch остаётся fail-closed.
- Public mutation smoke требует production-eligible пары. Её отсутствие
  блокирует Jira Done; seed или eligibility bypass запрещены.
- Production privacy/log evidence и exact immutable release можно подтвердить
  только после merge и activation.

## Внешние изменения

В Jira добавлен только плановый комментарий. Push, PR, merge, release,
production activation, Telegram actions и terminal Jira transition не
выполнялись.

## Следующий шаг

Независимый final review уровня 3. После `Status: approved` — commit, push, PR,
green CI, merge, exact immutable release, production activation, public smoke
и только затем Jira `Готово`.
