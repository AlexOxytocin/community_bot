# CB-68 — профиль и таблица вклада в Mini App

## Статус и основание

- Jira: `CB-68`, эпик `CB-48`, статус на старте фазы — «В работе».
- Ветка: `task/CB-68`.
- Точный baseline: `f2cc1cca9ca47c015b6d9e8469edd8d914a20a7f` (`origin/main`).
- Уровень процесса: **2**. Это не bugfix уровня `1B`, а новая видимая пользователю возможность, которая показывает чувствительные с точки зрения приватности reputation data. Риск ограничен: данные, API, схема, зависимости и доменные правила не меняются. Новый ADR, `plan-source-context.md` и отдельный `test-plan.md` не требуются.

## Цель и пользовательский путь

Добавить один read-only путь:

```text
Mini App → Профиль → мои показатели → таблица вклада
```

После существующего session bootstrap экран использует только уже защищённые
server-side projections:

1. `GET /api/v1/me` — собственные public fields, credit balance, experience и
   уровень с display name;
2. `GET /api/v1/members/{member_id}` для `member_id` из `/me` — безопасная
   karma/reliability projection;
3. `GET /api/v1/leaderboard?limit=30` — существующий ранжированный список вклада.

Клиент читает ответы через явный display allowlist и не вычисляет karma,
reliability, level или rank. Разрешены только `display_name`, заполненные
`city`/`timezone`/`short_bio`/`current_goal`/`help_categories`/`skill_tags`/
`availability`, `credit_balance`, `experience_total`, `level.number`/
`level.display_name`, `karma.score`/`karma.count`, `reliability.accepted`/
`reliability.approved_weight`/`reliability.no_show`/`reliability.rate` и поля
строк leaderboard `rank`/`display_name`/`experience`/`unique_recipients`/
`reliability`/`no_show`. `member_id`,
`telegram_username`, неизвестные response keys и private markers не
рендерятся. При `reliability.rate = null` текст — «Недостаточно данных».

## Reuse и границы контракта

Переиспользуются без изменений:

- `GET /api/v1/me` и `MeDto` в `src/community_bot/transport/web.py`;
- `GET /api/v1/members/{member_id}`, `MemberDto` и `_member_dto` в том же файле;
- `GET /api/v1/leaderboard` и `LeaderboardDto` в том же файле;
- server-side authorization и безопасная profile/reputation projection, уже
  вызываемые этими routes;
- существующие Mini App shell, fetch/session bootstrap, History API и native
  HTML/CSS/ES modules в `src/community_bot/transport/static/`.

### В scope

- tab/navigation «Профиль»;
- loading, empty/error/retry presentation для profile/leaderboard requests;
- собственная безопасная profile card и leaderboard list с semantic markup и
  видимым keyboard focus;
- один browser scenario для полного пути и privacy/null-reliability oracle.

### Явный non-scope

- backend/API/DTO/schema/migration/dependency changes;
- новые routes, cursor/load-more, search или чужие profile screens;
- karma vote/edit, raw karma/history/review, personal statistics и mutations;
- изменение visibility, reliability, level, ledger, ranking, auth/session или
  operation identity rules;
- React/Vite/Node, state-management layer или generic UI component framework;
- production deployment до merge и прошедших delivery gates.

## Владение файлами и порядок реализации

| Владелец | Файл | Минимальная работа |
|---|---|---|
| CB-68 | `src/community_bot/transport/static/index.html` | Добавить одну кнопку навигации «Профиль». |
| CB-68 | `src/community_bot/transport/static/app.js` | Запросить три существующих GET, отрисовать profile/leaderboard, states и History API transition. |
| CB-68 | `src/community_bot/transport/static/styles.css` | Добавить только стили, нужные card/list/empty presentation. |
| CB-68 | `tests/browser/test_mini_app.py` | Один расширенный Playwright oracle; не создавать новый test layer. |

`src/community_bot/transport/web.py`, application/domain/infrastructure,
migrations, `pyproject.toml` и integration API tests не меняются: их контракт
уже существует и не расширяется этой задачей.

## Проверки и пользовательский oracle

Один browser test с synthetic Telegram bridge и существующим session bootstrap
проверяет:

1. переход `Mini App → Профиль` и доступность navigation keyboard/focus;
2. display name, заполненные city/timezone/short bio/current goal/help
   categories/skill tags/availability, credit balance, experience, номер и
   display name уровня из `/me`; незаполненное optional public поле не создаёт
   пустую строку/секцию;
3. karma score/count и reliability из safe member response;
4. `rate = null` в own reliability и `reliability = null` в leaderboard row
   отображаются как «Недостаточно данных», без client-side percentage
   calculation;
5. leaderboard rows отражают ответ `/leaderboard`, включая rank, experience,
   unique recipients, reliability и no-show;
6. один privacy/XSS sentinel помещён в top-level, nested profile/reliability и
   leaderboard response boundaries; raw karma comment/rater marker,
   `member_id`, `telegram_username` и неизвестные private keys отсутствуют в
   DOM, а HTML-like dynamic text остаётся буквальным текстом через существующий
   `textContent` и не создаёт injected elements/attributes;
7. пустой leaderboard имеет отдельное понятное состояние;
8. visible loading state предшествует ответу; независимо отказавшие profile
   boundary (`/me` либо `/members/{id}`) и
   leaderboard boundary показывают scoped error и после retry переходят в
   authoritative success без ложного смешанного состояния;
9. pending response после Back отбрасывается существующим `screenRevision`
   guard, не заменяет каталог и не ломает восстановленный focus;
10. Back возвращает к предыдущему screen с ожидаемым focus.

Сценарий также записывает network methods/paths profile-screen: после
завершённого session bootstrap допускаются только `GET /api/v1/me`,
`GET /api/v1/members/{self}` и `GET /api/v1/leaderboard` с повторами при retry;
`POST`/`PUT`/`PATCH`/`DELETE` и неизвестные paths отсутствуют.

Перед final review выполнить точные gates:

```powershell
uv run pytest tests/browser/test_mini_app.py --no-cov -q
uv run ruff check tests/browser/test_mini_app.py
uv run ruff format --check tests/browser/test_mini_app.py
uv run ty check tests/browser/test_mini_app.py
git diff --check origin/main
git diff --cached -U0 origin/main | uv run python -c "import re,sys; text=''.join(line[1:] for line in sys.stdin if line.startswith('+') and not line.startswith('+++')); patterns=(r'AKIA[0-9A-Z]{16}', r'gh[pousr]_[A-Za-z0-9]{36,}', r'-{5}BEGIN .* PRIVATE KEY-{5}', r'(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*\S{8,}'); hits=[pattern for pattern in patterns if re.search(pattern,text)]; print('secret_scan=pass' if not hits else 'secret_scan=fail:' + ','.join(hits)); raise SystemExit(bool(hits))"
```

Перед `git diff --cached` все четыре planned files и task plan должны быть
явно staged; commit выполняется только после approved final review. Поэтому
secret gate проверяет весь planned delivery diff, включая новый task artifact,
а не пустой index.

Existing API integration tests запускаются только как regression контракта,
а не расширяются. Полная product regression не входит в CB-68.

## Ponytail

- **KEEP:** три существующих GET route, server authorization, DTO allowlist,
  native static shell и один browser test.
- **REMOVE:** ничего; задача не является cleanup.
- **DO NOT ADD:** API endpoint/DTO, service/repository, migration/table,
  dependency, frontend framework, generic router/pagination abstraction,
  client-side reputation calculation.
- Ожидаемый net LOC: примерно `+90–150` runtime lines в трёх static files и
  `+90–140` lines в existing browser test; backend/API/schema/dependencies —
  **0**. Перед финальным review один Ponytail audit удаляет очевидные
  duplicate helpers/markup, не превращаясь в refactor.

## Stop, rollback и delivery gates

### Stop

Остановить реализацию и вернуть вопрос владельцу, если потребуется:

- новый/изменённый API contract, DTO, backend owner, migration, table или dependency;
- показать raw karma author/comment, private fields либо обойти server-side
  visibility/session checks;
- вычислять/исправлять reliability, rank, level или ledger state на клиенте;
- более одного самостоятельного browser scenario или новый UI framework для
  прохождения требований.

### Rollback

До merge удалить только CB-68 static/UI и browser-test diff. После deployment
rollback — предыдущий совместимый application image/static bundle. Database,
ledger, outbox и schema не изменяются, поэтому downgrade migration не нужен.

### Delivery

После approved `final-review.md`: commit → push → PR → green CI/review → merge
в `main`. Поскольку runtime/static Mini App меняется, затем обязателен delivery
gate ADR-0019: green `main` CI, exact immutable artifact, manual-first pilot
activation, public URL smoke и Jira evidence. До этого нельзя заявлять public
Mini App готовым; deployment и live acceptance выполняются только после merge.
