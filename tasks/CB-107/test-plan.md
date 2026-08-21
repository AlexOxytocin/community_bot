# CB-107 — план проверки

## Принцип

Использовать существующие pytest/Testcontainers/Playwright и минимальное число
воспроизводимых команд. Не запускать отдельную backend reliability regression:
reliability code не меняется, а один static/browser oracle доказывает только
нулевую видимость в активном Mini App. Полная продуктовая регрессия не входит в
CB-107.

## Автоматические проверки

### 1. Domain, auth и DTO

```powershell
uv run pytest tests/unit/test_registration_domain.py tests/unit/test_web_auth.py -q --no-cov
```

Обязательные cases:

- label whitespace/`1..32`, ordered max five, stable UUID и action shape;
- absolute HTTPS, hostname, no credentials/control chars, URL max length;
- signed valid username, absence→`NULL`, malformed/unsigned reject; repeat no-op;
- DTO возвращают links/own username и detail-only `can_rate_karma`, не
  возвращают Telegram ID/private karma/auth data; существующие
  reliability/statistics fields не меняются.

### 2. PostgreSQL, API и migration

```powershell
uv run pytest tests/integration/test_registration.py tests/integration/test_web_api.py -q --no-cov
```

Минимальный integration scenario должен доказать:

1. create/edit/delete сохраняют порядок, ID и owner-only boundary;
2. exact replay каждого action с тем же key не создаёт второй UUID, link, audit
   или receipt; conflicting payload с тем же key возвращает `409`;
3. две конкурентные create при четырёх links не оставляют больше пяти;
4. public projection показывает только links активного видимого member;
5. username repeat без audit; concurrent update/clear сериализуются; change/clear
   дают один safe audit; unknown/failure оставляют member/audit/session без effects;
6. `can_rate_karma` совпадает с `begin_vote`: eligible/ineligible/self/status change;
7. isolated migration: downgrade fixture до `0021`, legacy member/data,
   `upgrade 0022`, default `[]`, NOT NULL/checks, valid max-five write, reject
   object/non-array/six links, `downgrade 0021`, повторный `upgrade 0022`;
8. таблицы/строки reliability и leaderboard query/order не входят в diff этого
   scenario и не модифицируются migration.

### 3. Один connected browser journey, два viewport

```powershell
uv run pytest tests/browser/test_mini_app.py -q --no-cov -k "profile_contract_links_back_focus_and_no_visible_reliability"
```

Один параметризованный Playwright test последовательно проходит при `375×812`
и `430×932`:

1. заполненный owner profile: username/city/level/credits/experience/karma,
   bio/skills/links и одинаковые pencils;
2. отдельные name/city/bio/skills editors: initial focus, counters/validation,
   отсутствие `Отмена`, Back без request, Save с retry тем же key, новый key
   после изменения invalid draft;
3. partial owner: три empty CTA и отсутствие пустых value cards;
4. links list/new/edit: max-five behavior, order, pencil, compact red trash,
   единственный `Сохранить`;
5. list/edit/direct/reload→confirm: Back без mutation возвращает соответственно
   trash/большую `Удалить`/list pencil или Add; confirm → следующая pencil/Add;
6. reload/deep-link каждого editor/link route восстанавливает authoritative
   state или безопасный empty/error state, не stale draft;
7. foreign: без credits/edit/empty; exact karma flag, status-change скрывает action;
8. public link/foreign valid `@username ↗` вызывают native opener; own plain,
   absent/malformed hidden; проверены `openLink` и secure browser fallback;
9. late responses не перерисовывают другой screen revision;
10. keyboard order, visible focus, accessible names, dialog focus containment,
    `documentElement.scrollWidth <= innerWidth` и отсутствие critical overlap;
11. один oracle проверяет одновременно static source и DOM: в `app.js` нет
    `reliabilityText`, `reliabilityPercent`, `Надёжность` и active
    `.reliability` reads; в owner/list/member detail нет видимого reliability
    текста/значения.

Используется текущий intercepted browser harness, без второго suite/framework.

### 4. Targeted coverage изменённых Python owners

```powershell
uv run pytest tests/unit/test_registration_domain.py tests/unit/test_web_auth.py tests/integration/test_registration.py tests/integration/test_web_api.py -q -o addopts="" --cov=community_bot.domain.registration --cov=community_bot.application.registration --cov=community_bot.infrastructure.db.registration --cov=community_bot.infrastructure.db.database --cov=community_bot.infrastructure.db.models --cov=community_bot.application.reputation --cov=community_bot.infrastructure.db.reputation --cov=community_bot.transport.web --cov-branch --cov-report=term-missing --cov-fail-under=0
```

`implementation-report.md` фиксирует per-owner line/branch и все новые gaps.

## Static deletion oracles

### Legacy profile — ожидается exit code `1` (совпадений нет)

```powershell
rg -n "profile-settings|editableProfileFields|profileValue|profileFields|profileDetails|profileEdit|profile-field-(list|row|editor|actions|status)|Мои показатели" src/community_bot/transport/static/app.js src/community_bot/transport/static/styles.css
```

Отсутствие profile-local `Отмена`, preview и task statistics дополнительно
проверяется browser scope, потому что эти общие слова законно используются в
других продуктовых flows.

### Visible reliability — один oracle

Не добавлять отдельный backend test. Проверка входит в connected browser test
выше и использует static precondition:

```powershell
rg -n "reliabilityText|reliabilityPercent|Надёжность|\.reliability" src/community_bot/transport/static/app.js
```

Ожидается exit code `1`. `web.py`, reputation/domain/DB и leaderboard DTO могут
и должны продолжать содержать reliability contract.

## Syntax и качество

```powershell
node --check src/community_bot/transport/static/app.js
node --check src/community_bot/transport/static/platform.js
uv run ruff format --check .
uv run ruff check .
uv run ty check
git diff --check
```

После commit последняя команда повторяется как
`git diff --check origin/main...HEAD`. `node --check` проверяет оба изменённых ES
module без добавления Node dependency в проект.

## Diff, scope и secrets

```powershell
git diff --name-only origin/main...HEAD
git diff --stat origin/main...HEAD
git diff --no-ext-diff --unified=0 origin/main...HEAD -- . ':!uv.lock' | rg -n "(?i)(bot[_-]?token|api[_-]?key|authorization:|cookie:|initdata=|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY)"
git diff --exit-code origin/main...HEAD -- uv.lock pyproject.toml docs
git diff --exit-code origin/main...HEAD -- src/community_bot/domain/reputation.py src/community_bot/infrastructure/db/reputation.py tests/unit/test_reputation_domain.py tests/integration/test_reputation.py
```

Secret-like scan ожидает exit code `1`. Dependency/docs gate ожидает `0`.
Последний reliability gate ожидает `0`; если links projection потребует двух
разрешённых additions в reputation files, reviewer проверяет hunks вручную:
только `profile_links` mapping, ноль изменений reliability folding/writers/
ordering, а test paths надёжности остаются без diff.

Ожидаемый runtime/test/migration allowlist:

```text
migrations/versions/0022_profile_links.py
src/community_bot/infrastructure/db/models.py
src/community_bot/domain/registration.py
src/community_bot/application/registration.py
src/community_bot/infrastructure/db/registration.py
src/community_bot/infrastructure/db/database.py
src/community_bot/application/reputation.py
src/community_bot/infrastructure/db/reputation.py
src/community_bot/transport/web.py
src/community_bot/transport/static/app.js
src/community_bot/transport/static/styles.css
src/community_bot/transport/static/platform.js
tests/unit/test_registration_domain.py
tests/unit/test_web_auth.py
tests/integration/test_registration.py
tests/integration/test_web_api.py
tests/browser/test_mini_app.py
tasks/CB-107/plan.md
tasks/CB-107/plan-source-context.md
tasks/CB-107/test-plan.md
tasks/CB-107/plan-review.md
tasks/CB-107/implementation-report.md
tasks/CB-107/final-review.md
tasks/CB-107/evidence/**
```

Любой другой путь требует trace и обновления одобренного плана до изменения.

## Ручное evidence и capture paths

Точный manifest 22 synthetic/PII-free captures:

| ID / assertion / board | `375x812` | `430x932` |
|---|---|---|
| PR-01 own-filled / fields-actions / overview | `tasks/CB-107/evidence/browser/375x812/01-own-filled.png` | `tasks/CB-107/evidence/browser/430x932/01-own-filled.png` |
| PR-02 foreign / privacy-actions / overview | `tasks/CB-107/evidence/browser/375x812/02-foreign.png` | `tasks/CB-107/evidence/browser/430x932/02-foreign.png` |
| PR-03 own-partial / empty-CTA / overview | `tasks/CB-107/evidence/browser/375x812/03-own-partial.png` | `tasks/CB-107/evidence/browser/430x932/03-own-partial.png` |
| PR-04 name / save-back-focus / fields | `tasks/CB-107/evidence/browser/375x812/04-name.png` | `tasks/CB-107/evidence/browser/430x932/04-name.png` |
| PR-05 city / save-back-focus / fields | `tasks/CB-107/evidence/browser/375x812/05-city.png` | `tasks/CB-107/evidence/browser/430x932/05-city.png` |
| PR-06 bio / counter-save / fields | `tasks/CB-107/evidence/browser/375x812/06-bio.png` | `tasks/CB-107/evidence/browser/430x932/06-bio.png` |
| PR-07 skills / ordered-validation / fields | `tasks/CB-107/evidence/browser/375x812/07-skills.png` | `tasks/CB-107/evidence/browser/430x932/07-skills.png` |
| PR-08 links / pencil-trash-limit / links | `tasks/CB-107/evidence/browser/375x812/08-links.png` | `tasks/CB-107/evidence/browser/430x932/08-links.png` |
| PR-09 link-new / https-save / links | `tasks/CB-107/evidence/browser/375x812/09-link-new.png` | `tasks/CB-107/evidence/browser/430x932/09-link-new.png` |
| PR-10 link-edit / save-delete / links | `tasks/CB-107/evidence/browser/375x812/10-link-edit.png` | `tasks/CB-107/evidence/browser/430x932/10-link-edit.png` |
| PR-11 delete-confirm / deterministic-back / links | `tasks/CB-107/evidence/browser/375x812/11-link-delete-confirm.png` | `tasks/CB-107/evidence/browser/430x932/11-link-delete-confirm.png` |

`journey.json`, migration/verification txt содержат результаты, не screenshots.

`journey.json` содержит viewport, screen route/state, assertion IDs, focus
target и pass/fail, но не cookies, initData, Telegram ID, реальные usernames или
URL. Скриншоты используют синтетические данные.

Ручная сверка на каждом viewport:

- visual hierarchy и тексты совпадают с canonical boards;
- touch targets не меньше 44 CSS px, compact trash имеет accessible name;
- одна pencil semantics, одна normal Save, большие destructive buttons имеют
  текст `Удалить`;
- Back discard, reload и focus работают на всех editor/confirm routes;
- public link открывается безопасно, empty foreign fields скрыты;
- reliability отсутствует на owner/list/detail, shell/nav сохранены.

## Deployment и live acceptance

Локальные зелёные тесты не закрывают web delivery. После approved final review,
PR/CI/merge и deployment точного merge commit проверить:

1. production migration head `0022`, web health/readiness и static asset commit;
2. предыдущий image стартует на additive schema `0022`; destructive downgrade
   после реальной link mutation не выполняется;
3. Mini App launch использует signed initData, username sync/clear не раскрывает
   proof и не создаёт новую identity;
4. Jira CB-107 acceptance проходит на разрешённых test accounts в обоих
   viewport; чаты/медиа не читаются, сообщения не отправляются;
5. evidence фиксирует только commit, schema head, viewport и результат.

Если deployment или test accounts недоступны, это остаётся явным production
gate; нельзя сообщать `готово`/`done` для публичного web release.
