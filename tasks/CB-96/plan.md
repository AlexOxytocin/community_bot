# CB-96 — план реализации полного presentation layer концепции 05

## Цель и граница

Реализовать в фактическом native Telegram Mini App полный UI концепции 05:
визуальную систему, 103 screen/state ID, 17 no-UI границ, 26 capabilities и
128 явных product/user transitions. CB-96 меняет только presentation layer.

В CB-96 запрещены новые backend endpoints, projections, application seams,
domain/storage/schema/migration/dependency changes. Существующие API-вызовы
сохраняются, если новый UI может использовать их без изменения контракта.
Неподключённые production actions показывают `disabled_reason`/unavailable и
не имитируют authoritative success. Fixtures доступны только development,
tests и screenshot harness.

Размер: `large`, процесс: уровень `3`. Архитектура: принятый ADR-0017 — native
HTML/CSS/ES modules без React/Vite/Node и новых frontend dependencies.

## Нормативный manifest

`ui-contract.json` является machine-countable presentation contract, а
`ui-inventory.md` — его полный человекочитаемый screen/transition/no-UI view:

- 103 уникальных UI ID и 17 уникальных no-UI ID;
- 26 capability IDs;
- 11 allowlisted route patterns;
- каждый UI ID имеет один route pattern, `view_state`, component family,
  role variant, entry, logical parent, только применимые visual/system states,
  fixture policy и закрытый `connection_class`;
- 128 уникальных product transition с ID, source ID/view state, target ID/route/view
  state, trigger, from/to state, history semantics, runtime scope, guard и
  browser-visible oracle;
- каждый primary action имеет класс `existing_http_connected`,
  `ui_local_only` или `disabled_unavailable`; no-UI строки имеют отдельную
  disposition, а доступность данных фиксируется независимо через `data_mode`;
- conceptual success неподключённого действия имеет scope
  `dev_test_fixture_only`, а production edge остаётся на том же screen с
  `disabled_reason`;
- нет `#/ui/<screen-id>`, 103 renderer keys, API owner или mutation contract.

Manifest генерируется `build_ui_contract.py` из утверждённого board плюс явных
route/parent/success/navigation mappings. Runtime не читает task JSON и не
становится generic screen framework: browser tests сверяют production registry
с manifest.

Count 128 является производным от явных flows concept 05. Повторяющиеся Back,
reload, deep-link и system-state правила хранятся как global invariants и
per-screen navigation/reload/deep-link attributes, а не размножаются до сотен
фиктивных edges. Generator отдельно assert-ит обязательные и запрещённые key
edges, включая запрет success→mutation Back.

## Route и component модель

11 patterns: `start`, `catalog`, `task`, `composer`, `work`, `work_item`,
`members`, `member`, `profile`, `moderation`, `admin`. Screen ID передаётся как
allowlisted `view_state`, а не создаёт отдельную страницу.

Переиспользуемые families ограничены доказанной визуальной ответственностью:
shell/context header, root nav, list/card, detail, form/field, tabs, dialog,
status/skeleton и sticky action. Feature renderers собирают эти primitives;
generic screen builder, schema framework, store или command bus не создаются.

## Visual и navigation contracts

- dark/neon token system: cyan primary/active, violet route accent, Manrope,
  единые cards/buttons/forms/chips/dialogs/status blocks;
- root navigation использует replace и показывает только role-visible roots;
- context screen использует push, скрывает bottom nav, хранит logical parent и
  focus return;
- dirty Back открывает confirm; dialog Back/Escape закрывает dialog; success
  replace-ит mutation history;
- reload и deep-link target повторяют bootstrap/view checks; deep link остаётся
  hint, а не authorization bypass;
- loading сохраняет геометрию, empty/error/permission/disabled называют
  причину и следующий доступный шаг;
- 375px без horizontal overflow, controls ≥44px, semantic labels,
  focus-visible, keyboard order, contrast и reduced-motion.

## Production/fixture boundary

1. Production build не принимает fixture query/hash/localStorage flags и не
   импортирует fixture modules.
2. Existing connected screens получают authoritative success только из
   текущего API response.
3. Unconnected screens доступны как полный UI/state representation, но их
   action disabled с понятной причиной «Подключение будет добавлено следующим
   этапом».
4. Fixture harness детерминированно показывает content/empty/error/permission/
   validation/preview/confirm/success для browser oracle и скриншотов.
5. Fixtures не записывают balance, permissions, outcomes или mutation state в
   production storage и не подменяют existing API.

## Шаги реализации

### Slice 0 — manifest и scope guard

1. Зафиксировать и проверить exact 103/17/26/11/128 counts.
2. Добавить архитектурный test: screen IDs не являются routes/components;
   transition refs полны и уникальны; stale 84/9/75 manifest не используется.
3. Добавить diff guard: никакие application/domain/infrastructure/models/
   migrations/backend route/dependency files CB-96 не меняет.
4. Обновить Git remap перед первым runtime edit; конфликт в static UI/test
   paths останавливает реализацию.

### Slice 1 — visual system и shell

1. Перестроить `index.html` под semantic app shell, context header, live region
   и bottom safe-area navigation.
2. Переписать tokens/primitives в `styles.css`, сохранив Manrope и current
   static delivery.
3. Вынести из `app.js` минимальные native modules: platform/router/view state,
   DOM primitives и feature renderers; модуль появляется только при второй
   реальной ответственности.
4. Удалить старый hero и разрозненные top buttons.

### Slice 2 — router, view states и system states

1. Реализовать только 11 allowlisted patterns и allowlisted `view_state`.
2. Реализовать root replace, context push/Back/focus, dirty confirm, dialog
   close, success replace, reload и deep-link representation.
3. Общими primitives покрыть loading/content/empty/error/permission_closed/
   disabled_reason/confirm/success без 103 копий.
4. Unknown view/resource/role получает safe unavailable, не чужие данные.

### Slice 3 — member surfaces A/T/M/P

1. A01–A07: launch/auth/onboarding/status presentation; неподключённый
   onboarding disabled/unavailable в production.
2. T01–T08: catalog/detail, solo/group, template/freeform, criteria, draft,
   preview/confirm/success; existing freeform calls сохраняются.
3. M01–M19: assignments/results/review/dispute/appeal/group cancellation;
   existing cycle сохраняется, неподключённые states честно disabled.
4. P01–P10: member search/cards/karma/leaderboard и own profile/ledger;
   leaderboard остаётся отдельным экраном в «Участниках».

### Slice 4 — moderation/admin surfaces S/G

1. S01–S12: dispute, registration moderation, sanctions, fraud surfaces.
2. G01–G28: permission-shaped admin hub, invitations/members/catalog/config,
   community flow, histories, appeals, alerts and penalties.
3. G08A: metadata read-only и active toggle representation; G09 только
   template version. Никакой выдуманной category edit.
4. Все ещё неподключённые actions в production завершаются disabled state;
   full conceptual flows доказываются dev/test fixture scope.

### Slice 5 — fixture harness и visual evidence

1. Создать deterministic fixture adapter в test/dev-only boundary, исключённый
   из production imports/build path.
2. Table-driven browser oracle проходит все 103 screen IDs, 128 product edges
   и global invariants по различающимся route/navigation/layout classes.
3. Переснять production UI: full board, transition map, key groups и длинные
   create/task screens в двух частях.
4. Выполнить pixel/structure review относительно concept-05 references без
   копирования устаревшего concept-04 manifest.

### Slice 6 — convergence и delivery

1. Выполнить browser/accessibility/visual/architecture gates из `test-plan.md`.
2. Подтвердить existing API non-regression и отсутствие новых backend routes.
3. Создать `implementation-report.md`, Ponytail review и независимый
   `final-review.md`.
4. Gate 2: показать diff и commit messages; после подтверждения commit/push/PR,
   CI/review/merge.
5. Создать новый immutable release, активировать production и выполнить public
   Mini App smoke по ADR-0019. Только после green public smoke этап готов.

## Следующая отдельная задача

`next-task-engine-handoff.md` сохраняет найденные engine/API gaps. После
deployment CB-96 создаётся отдельная Jira-задача на screen→engine→API mapping и
минимальные доказанные adapters. Этот handoff не разрешает backend изменения в
CB-96.

## Критерии готовности

1. Manifest и production registry дают 103/17/26/11/128 без missing/duplicate.
2. Все screen/state/transition видимы и исполняются в browser oracle.
3. Production не содержит fixture success для неподключённых actions.
4. Diff не содержит backend/application/domain/storage/schema/dependency work.
5. Visual/mobile/accessibility checks зелёные; reference screenshots обновлены.
6. Оба plan review имеют `Status: approved`; после реализации independent final
   review также approved.
7. PR/CI/merge/release/deploy/public smoke завершены.

## Gate

Standing owner decision в Jira comment 10346 разрешает начать implementation
автоматически только после двух утверждённых плановых ревью:
`plan-review.md` и `plan-review-orchestrator.md`. До этого runtime не меняется.
