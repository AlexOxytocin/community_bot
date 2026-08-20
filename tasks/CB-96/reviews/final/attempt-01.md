# CB-96 — независимая final + visual проверка

Schema: `community_bot.final_review.verdict.v1`

Status: changes_requested

## Terminal verdict

Реализация не соответствует concept 05 по фактическому UI и не закрывает
navigation/transition contract. Exact machine counts присутствуют, scope
frontend-only сохранён, целевой browser-файл в конечном состоянии проходит,
но его oracle подтверждает registry tokens и прямые вызовы экспортированных
функций, а не соответствие экранов board и не исполнимость всех product edges
пользовательскими controls.

## Проверенные источники

- полностью прочитаны канонические project rules, глобальная agent-budget
  policy, live Jira CB-96 и comments `10352`, `10353`, `10354`;
- полностью прочитаны `plan.md`, `test-plan.md`, `ui-contract.json`,
  `plan-review.md`, `plan-review-orchestrator.md`;
- сверены `cb93-ui-plan-v5.md`, `cb93-contract-coverage-v5.md` и нормативные
  `cb93-v5-key-screens-board.png`, `cb93-v5-complete-screen-board.png`,
  `cb93-v5-transition-map.png`;
- применены `ponytail-review`, `browser-qa` и
  `frontend-design-direction`;
- локальный HTTP fixture запущен с Playwright; actual 375×812 screenshots
  сняты вне репозитория в
  `C:\Users\User\.codex\visualizations\2026\08\19\01a01c02-28aa-7152-9931-c3ff63b34d31`.

## Обязательные изменения

### 1. Key screens являются contract-token placeholders, а не concept 05 UI

Location:

- `src/community_bot/transport/static/app.js:50-166` — runtime-копия raw
  `visual_contract` tokens;
- `src/community_bot/transport/static/app.js:327-449` — восемь generic
  templates печатают token как heading/label и подставляют `—` вместо
  предметного содержимого;
- `src/community_bot/transport/static/app.js:452-490` — общий status copy
  сообщает, что «доступна структура экрана», вместо реализации экрана.

Observed actual screenshots/DOM:

| Screen | Actual 375×812 | Expected concept 05 |
|---|---|---|
| T01 | карточки `filters`, `cursor`, `TEST marker` и `—`; нет каталога заданий | три предметные task cards, chips, reward/deadline, create action |
| T03 | `snapshot fields`, `open`, `full`, `expired`, `unavailable` и `—` | автор, reward/slots/time, инструкции, критерии, формат/место, deadline |
| M01 | `taken`, `created`, `recent` и `—` | tabs «Взятые мной / Созданные», реальные assignment cards и статусы |
| P06 | `profile`, `balance`, `XP/level`, `karma` и `—` | avatar/name/status, 24/180/96%, показатели и карточка профиля |
| S01 | `dispute`, `appeal`, `fraud admin-only` и `—` | очередь разрешённых кейсов с badges, временем и номерами |
| T05 | disabled inputs `all engine fields`, `schema`, `autosave`, `balance` | рабочая длинная форма с утверждёнными полями и понятными labels |
| P01 | `active-only`, `name/@username ≥3`, `cursor` и `—` | search и предметные member cards |
| P02 | `safe profile fields`, `aggregate`, `eligibility` и `—` | member identity, metrics, bio/tags и karma editor |
| P05 | `all-time XP`, `tie-breaks`, `own rank`, `cursor` и `—` | leaderboard rows, own rank и пояснение расчёта |

Дополнительные samples T06/T07/T08/A02/M14A воспроизводят тот же дефект:
`immutable snapshot`, `exact revision`, `success`, `append-only evidence
history` выводятся как пользовательский текст. A02 также даёт обрезанный
brand/header при focus outline. Baseline и actual расходятся на каждом из
девяти обязательных key screens.

Minimal correction: сохранить небольшой registry и восемь semantic layouts,
но заменить raw contract tokens конкретными русскими labels, fixture data и
композициями из boards. `visual_contract` должен быть проверочным metadata, а
не пользовательским copy. Production actions без engine connection остаются
disabled с причиной; это не требует превращать весь экран в placeholder.

### 2. Connected context screens сохраняют bottom nav — split-brain из 10354

Location:

- `app.js:292` — `setNavigation(screen, context = false)`;
- `app.js:759-761` — connected T05 вызывает `setNavigation("")`;
- `app.js:1126-1132` — connected P02 вызывает `setNavigation("")`;
- `app.js:1214-1222` — connected T03 вызывает `setNavigation("")`;
- `app.js:1748-1760` — connected work-item context вызывает
  `setNavigation("")`;
- `app.js:1907-1919` — connected moderation context вызывает
  `setNavigation("moderation")`.

Observed actual connected T03:

- URL: `http://127.0.0.1:<port>/#task`;
- Back visible: `true`;
- `#primary-navigation` visible: `true`;
- active bottom item: none;
- fixed nav перекрывает середину длинной карточки.

Screenshot: `cb96-connected-T03-context.png`. Presentation T03 при этом
скрывает nav, то есть один screen имеет два разных shells.

Expected: любой context screen скрывает bottom nav, показывает Back, хранит
logical parent и возвращает focus; roots показывают role-visible nav.

Minimal correction: сделать context/root явным обязательным аргументом,
передать `context=true` во все connected context renderers и обновить старые
DOM expectations. P05 также должен соответствовать утверждённому root/tab
варианту «Участников»: сейчас он ошибочно получает Back и скрытый nav.

### 3. Фактические URLs не реализуют единую модель 11 patterns

Location: `app.js:167-179`, `app.js:496-539`, а также legacy pushes
`app.js:760`, `1129`, `1220`, `1437`, `1752`, `1911`.

Observed:

- presentation T03: `#/tasks/unavailable-resource?view_state=t03`;
- connected T03: `#task` без task identity;
- presentation P02: `#/members/unavailable-resource?view_state=p02`;
- connected P02: `#member-profile` без member identity.

`history.state` assertions не устраняют это расхождение. Synthetic
`unavailable-resource` не является production resource identity, а legacy
hash не соответствует заявленному allowlisted pattern.

Minimal correction: connected renderers и presentation registry должны
использовать один canonical URL builder с реальным opaque resource ID; fixture
resource token допустим только внутри test/dev harness. Unknown/deep-link
resource должен fail closed в safe fallback после access/state check.

### 4. 93 local edges не доказаны как пользовательски исполнимые

Location:

- runtime `localPrimaryTargets` в `app.js:188-233` содержит только 41
  source→target mapping;
- test loop `tests/browser/test_mini_app.py:314-397` для всех не-connected
  edges напрямую импортирует module и вызывает
  `navigatePresentationScreen(...)`;
- тот же тест вручную вызывает target и для `dev_test_fixture_only` edges,
  вместо исполнения source trigger.

Contract counts корректны: `93 production_ui_local`,
`25 dev_test_fixture_only`, `10 production_existing_api`, итого `128`. Но
прямой вызов target navigation доказывает только возможность нарисовать
target. Он не доказывает наличие source control, trigger, guard, disabled
semantics или исполнимость edge. Это особенно заметно на screens без строки в
`localPrimaryTargets`: primary action просто перерисовывает тот же screen.

Minimal correction: для каждого из 93 production local edges table-driven
browser test должен найти и активировать реальный source control и проверить
actual URL/history/focus/target. 25 fixture-only edges должны выполняться через
явный test/dev-only adapter, недоступный production navigation. 10 connected
edges сохраняют текущие mocked authoritative handlers и проверяются кликом по
реальному control.

### 5. Visual/browser oracle даёт false green относительно board

Location: `tests/browser/test_mini_app.py:170-229` сравнивает DOM text с тем же
`visual_contract`, который runtime печатает как UI; `:314-397` обходит
controls прямым module call.

Итоговый targeted run после стабилизации worktree:

```text
uv run pytest --no-cov -q tests/browser/test_mini_app.py
14 passed in 37.54s
```

Этот green сосуществует с фактическими screenshots выше, где все девять key
screens не совпадают с board. Следовательно, тест защищает само-дублирование
контракта, а не acceptance.

Minimal correction: добавить screenshot/structure assertions по девяти key
screens и form/editor/confirm/outcome/state samples; проверять предметные
labels, card hierarchy, nav visibility, sticky overlap и отсутствие raw
tokens/`—`. Без actual screenshot visual verdict не должен становиться green.

## Scope и safety evidence

Подтверждено:

- runtime/test diff затрагивает ровно четыре разрешённых файла:
  `app.js`, `index.html`, `styles.css`, `test_mini_app.py`;
- итоговый diff: `+1011/-45`; backend/API/application/domain/storage/schema/
  migrations/dependencies не менялись;
- production fixture query/hash/localStorage activation не найден;
  `?ui-preview=1`, `#screen/...`, `#ui-preview=...` fail closed, storage пуст;
- manifest содержит exact `103/17/26/11/128`;
- action classes: `61 ui_local_only`, `10 existing_http_connected`,
  `32 disabled_unavailable`; 32 disabled screen показывают reason и не делают
  request;
- 17 no-UI и 26 capability rows присутствуют.

Эти пункты не компенсируют visual/navigation/edge defects.

## Targeted verification

```text
node --check src/community_bot/transport/static/app.js       PASS
uv run ruff check tests/browser/test_mini_app.py             PASS
git diff --check                                             PASS
uv run pytest --no-cov -q tests/browser/test_mini_app.py     14 passed
```

Первый browser run пересёк незавершённое параллельное изменение файла и упал
на `content != success`; после стабилизации текущего worktree обязательный
повтор выше зелёный. Verdict основан на конечном состоянии и independently
reproduced DOM/screenshots.

## Ponytail review

`tests/browser/test_mini_app.py:130-229: delete: runtime-token parity loop,
который принимает raw contract metadata за UI evidence. Оставить один
registry parity check; заменить остальное предметными behavior/visual cases.`

`tests/browser/test_mini_app.py:314-397: shrink: 118-edge direct-target
navigator доказывает helper, а не edge. Один table-driven source-control
executor с отдельными adapters для local/fixture/connected scopes.`

`app.js:50-289: shrink: planning contract вручную размазан по inventory,
route, template, disabled и transition maps. Оставить одну компактную runtime
таблицу и derived indexes; raw metadata не рендерить.`

`net: -120 lines possible` без потери 103/128 registry evidence; необходимые
предметные fixture compositions считаются отдельно и не являются generic
framework.

## Required terminal state

Status остаётся `changes_requested` до одновременного выполнения всех пяти
исправлений и повторной actual 375×812 visual проверки против concept 05.
