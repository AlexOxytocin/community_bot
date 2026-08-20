# CB-100 — отчёт реализации

## Результат

- `+ Создать` больше не открывает T04/T04A: существующий GET current-state ведёт
  прямо в blank T05 либо в условный T04B recovery.
- Blank T05 не создаёт draft до submit. Первый submit один раз выполняет
  idempotent `start`, сохраняет возвращённые server id/revision в form closure и
  затем вызывает существующий `save`.
- Current/stale draft показывает authoritative title и явные действия. Stale
  draft редактируется с сохранёнными values/revision; «Создать новое» вызывает
  одну существующую command boundary action `start_new`.
- `start_new` переиспользует `TaskService.start`, task identity gate, receipt
  replay и atomic `create_task_draft`; замена разрешена только для точных
  видимых `draft_id/revision`, предыдущий current становится non-current, новый
  создаётся ровно один раз.
- После retryable POST failure доступны повтор с тем же idempotency key и
  GET-only восстановление. После успешного POST с ошибкой follow-up GET повторная
  mutation блокируется, а recovery перечитывает authoritative current state.
- Backend template capability, schema, migrations, repository structure,
  dependencies, domain validation, test-run isolation и publish semantics не
  изменены.

## Матрица приёмки

| Критерий | Доказательство | Статус |
|---|---|---|
| Zero draft → editor, POST=0 до submit | browser action log и отсутствие T04B DOM | green |
| Stale preview не тупик | recovery → edit → изменённый deadline → T06 | green |
| Exact values/revision | recovery title из DTO; save использует revision `1` | green |
| Create new без дубликата | API replay: две одинаковые команды, distinct key по старой revision → 409; всего два drafts `[old non-current, new current]` | green |
| Retry/repeated click | browser 503→retry с тем же Idempotency-Key; POST 204→GET 503 восстанавливается только GET и оставляет POST count неизменным | green |
| Удалены T04/T04A/templates copy | static source exact zero-count oracle | green |
| Back/reload | draft editor → recovery → Catalog; T06 reload и editor/preview history | green |
| Foreign/test-run/stale fail closed | скрытый test-run current → 409 и zero-effect; owner/scope/revision проверяются до supersede | green |

## Проверки

- targeted API `start_new` — 1 passed;
- targeted creation browser matrix — 3 passed;
- `tests/integration/test_web_api.py tests/integration/test_task_creation.py` — 30 passed;
- полный browser file — 17 passed;
- полный non-browser gate — 582 passed, 17 deselected;
- Ruff format/lint, `ty`, node syntax и `git diff --check` — green.

## Delivery state

PR/CI/merge, immutable release, production activation и public/Telegram wrapper
smoke остаются обязательным следующим gate. До них задача не считается
завершённой.

## Остаточный риск

Canonical Telegram wrapper не имеет RequestWebView harness; post-deploy smoke
использует утверждённую bounded схему: две session probes, allowlisted
`ui-messages`, menu-button proof и связанный public/API smoke без raw initData.
