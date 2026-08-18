# CB-71 — отчёт о реализации

## Статус

Scope реализован локально в `task/CB-71`; исходный baseline поручения —
`4af786dae39f3c89c97ebf1e97da355ad09aa964`, актуальная база после refresh —
`bb543e978467882d90a323fdc9c180b0201a9629`. Runtime code, product tests,
release infrastructure и production state не менялись. Owner-approved extra
fix и единственная независимая проверка завершены: `Status: approved`.

## Что изменено

- `AGENTS.md` получил active fail-closed instruction для Оркестратора.
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` закрепил канонические allowlist,
  denylist, recovery, thread identity и delivery ownership.
- ADR-0015 дополнен уже принятым сквозным решением без нового ADR.
- `agents/config.yaml` содержит один machine-readable `orchestrator_boundary`.
- `agents/workflow.yaml` ссылается на boundary, назначает task-thread owner и
  заменяет legacy delivery mapping на strict product-task/runtime-diff gate.
- ADR-0019, agent/Jira/release workflow docs и exact architecture test удаляют
  owner waiver и широкий docs/tests/task-artifacts skip.
- Новый framework, role, hook/daemon, dependency и deterministic runtime guard
  не добавлены.

## Критерии приёмки и доказательства

| Критерий | Статус | Доказательство |
|---|---|---|
| Абсолютный запрет кода и явный allowlist | закрыт | Active instruction и главный guardrail запрещают любые code/docs/tests/repository/task/Git/PR/merge/release/deploy/terminal Jira actions; config задаёт закрытые `allowlist`/`denylist` и `execution_and_blocked`. |
| Handoff/recovery без takeover | закрыт | Config: три recovery trigger, `create_successor_with_compact_handoff`, `orchestrator_takeover: forbidden`; workflow ссылается на тот же контракт. |
| Subagent не равен видимому task-thread | закрыт | `subagent_is_user_visible_task_thread: false`, scope только matching task-thread; prose повторяет границу. |
| Один Jira/thread/branch | закрыт | `one_current_visible_thread_per_issue`, `task/{issue_key}`, successor повторно использует issue и branch. |
| Delivery остаётся в task-thread | закрыт после owner-approved extra cycle | Все active/canonical/config/workflow boundaries и exact test используют `product_task OR any_runtime_diff`; finite taxonomy удалена. Новый immutable release, production activation и green public smoke выполняет matching task-thread до Jira `Done`. |
| Узкий deploy skip | закрыт | Только process/docs-only задача без runtime diff получает `skip`; широкий docs/tests/task-artifacts diff-only skip удалён из ADR-0019, consumers и exact test. Diff CB-71 содержит лишь project process instructions, agent policy/workflow, architecture contract test и task artifacts. |
| Ponytail minimal diff | закрыт | Переиспользованы пять существующих канонических точек и ADR-0015; role-файлы и runtime не затронуты, decorative guard отсутствует. Independent plan review: `Lean already. Ship.` |

## Проверки

- `uv run pytest --no-cov -q tests/architecture/test_agent_orchestration_policy.py`
  → `11 passed in 0.34s`.
- Загрузка `agents/config.yaml` и `agents/workflow.yaml` через PyYAML →
  `yaml-ok`.
- Точечный поиск обязательных policy keys → все allow/deny/recovery/thread/
  delivery keys найдены.
- `git diff --check origin/main` → без ошибок.
- Secret-like scan added lines → `secret_scan=pass`.
- `git diff --name-only origin/main` → только active/process/release
  documentation, agent policy/workflow и architecture contract test; untracked
  `tasks/CB-71/*` также является только task artifacts.

## Отклонения от плана

После первого final review scope расширен только на существующие canonical
delivery consumers и exact architecture test. Причина: старые owner waiver и
широкий diff-only skip делали новый strict standing rule противоречивым.
Runtime code и release infrastructure по-прежнему не меняются.

## Delivery

До merge внешнего delivery решения ещё нет. После merge CB-71 должна получить
privacy-safe Jira evidence `skip`: задача process/docs-only и не содержит
runtime diff. Immutable release, production activation и public smoke для
CB-71 не требуются.

## Остаточный риск

Репозиторий не получает надёжный identity-сигнал активного Codex-thread, поэтому
enforcement остаётся instruction-level. Декоративный guard не добавлен; любое
неоднозначное действие явно блокируется политикой.
