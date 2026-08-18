# CB-69 — отчёт реализации

**Статус:** реализация готова к независимому final review; commit, push, Jira и deploy не выполнялись.

**Baseline:** `49e8a7a360f1f8f8d5e5c5a5d827c17511ba6a05`.

## Критерии и доказательства

| Критерий | Статус | Доказательство |
|---|---|---|
| Durable begin/save/confirm | выполнен | Три actor-native routes используют existing `AssignmentService.begin_submission`, `save_submission_draft`, `confirm_submission_draft`; `tests/integration/test_assignments.py::test_web_submission_draft_is_durable_exact_and_actor_native` подтверждает restart/resume, different-key concurrent save с одним winner, fingerprint conflict и один result/outbox при concurrent confirm. Stale DB `ValueError` переводится на application boundary в закрытый `AssignmentError`/HTTP `409`. |
| Fail-closed contract | выполнен | `AssignmentCard.submission_contract` возвращает только `freeform_result_v1` при `template_id is None`; actor-native application guard стоит до draft/result mutation. HTTP oracle вызывает direct web begin для template assignment и доказывает `409` плюс ноль draft rows, а legacy template draft сохраняет прежнюю schema-validation semantics. |
| Origin/session/body/idempotency | выполнен | Routes сначала проверяют Origin, web session и numeric key; body ограничен 4096 bytes, top-level DTO `extra=forbid`, `expected_revision` strict integer. Один HTTP scenario покрывает missing Origin, noncanonical UUID, nonempty begin, missing assignment, malformed content type/JSON/revision, oversized body, exact replay и same-key conflict save/confirm. |
| Exact replay и test scope | выполнен | Web receipt несёт command fingerprint. Replay сверяет owner/fingerprint и до возврата receipt повторяет `ensure_task_test_access`; `test_web_submission_replay_rechecks_test_scope` доказывает fail-closed после выхода из active test run без нового receipt/result. |
| Privacy | выполнен | `SubmissionDraftDto` allowlists только `id`, `revision`, `result`; malformed/private payload key не сериализуется (`test_submission_draft_projection_is_allowlisted_and_revisions_are_strict`). |
| Telegram regression | выполнен | Тот же PostgreSQL scenario доказывает: web actor не создаёт `ConversationStateModel`; legacy Telegram template begin/save сохраняют schema validation, `text → preview`, exact replay, а confirm очищает flow. |
| Native Mini App journey | выполнен | Один browser oracle проходит begin network retry, non-JSON `502` confirm retry с тем же key, autofocus textarea, preview, explicit confirm, safe late-response navigation, detail refresh и literal XSS text rendering. |

## Проверки

- `uv run ruff format --check .` — pass.
- `uv run ruff check .` — pass.
- `uv run ty check src tests ops` — pass.
- `uv run pytest -q tests/unit/test_web_auth.py --no-cov` — `17 passed`.
- Combined targeted coverage: unit + все assignment/HTTP integration tests — `39 passed`; `assignments.py` 73%, `web.py` 96% при отключённом только глобальном package threshold (`--cov-fail-under=0`).
- Machine diff intersection из `coverage json` и `git diff --unified=0 origin/main`: изменённые runtime statements `168/181` (**92.8%**), branches `46/54` (**85.2%**). Непокрытый остаток — defensive foreign/corrupt receipt branches; owner, stale scope, fingerprint conflict, legacy replay и transport negative matrix покрыты.
- Targeted PostgreSQL nodes: durable actor-native + legacy flow и stale test-scope replay — `2 passed`.
- Targeted HTTP node: bounded/exact/template-closed matrix — `1 passed`.
- `uv run pytest --no-cov -q tests/browser/test_mini_app.py` — `6 passed`.
- `git diff --check origin/main` — pass.
- Staged added-lines secret scan — pass. Pattern проверяет credential literals;
  ссылка `bot_token=BOT_TOKEN` в test setup классифицирована как identifier, а
  не секретное значение.

Repository-wide `fail_under=80` не используется как локальная оценка subset:
ADR-0017 отменяет global percentage и требует targeted coverage изменённых
runtime-модулей. Поэтому pytest собирает coverage с `--cov-fail-under=0`, после
чего отдельно проверяется пересечение executable lines/branches с exact diff.
Полный repository suite остаётся PR CI gate.

## Ponytail и размер

Production net diff: около **473** строк (`assignments.py` +136, `web.py` +173, `app.js` +161, `styles.css` +3); targeted tests около **606** net lines. Это превышает plan trigger ~280 и поэтому требует explicit review.

**KEEP:** existing durable drafts/results/receipts, existing service/UoW, free-form validator, static shell, SHA-256 stdlib.

**REMOVE / reuse:** duplicate `_submission_actor` удалён; existing `_accept_actor` расширен и переименован в shared `_command_actor` для accept и submission commands.

**DO NOT ADD:** direct submit, migration/table, new service/repository/UoW/framework, generic schema renderer or client authorization.

Превышение runtime вызвано trust-boundary checks
(actor/replay/test-scope/fingerprint), тремя resource routes и one-screen
accessible retry/preview/confirm UI. Test diff вырос внутри четырёх существующих
scenario-файлов: добавлены не отдельные слои, а PostgreSQL owner/legacy/scope,
один HTTP negative matrix и один browser journey. После reuse audit дальнейшее
сокращение означало бы убрать transport validation, privacy allowlist, exact
replay либо заявленные oracles; новых abstraction/persistence/test framework не
введено.

## Остаточный риск и следующий шаг

Изменения локальны и не deployed. Нужны независимый `final-review.md`, полная PR CI/coverage и только затем стандартный branch route. Rollback до merge — удалить только CB-69 routes/seam/static form/tests; durable data/schema не менялись.
