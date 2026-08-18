# CB-55 — отчёт о реализации

## Результат

Реализован только согласованный read-only slice:

`Mini App -> Модерация -> open/appealed queue -> Назад`.

Добавлен один `GET /api/v1/moderation/cases?limit=1..50`. Detail и mutation
routes отсутствуют. Карточки очереди не интерактивны.

## Reuse и границы

- HTTP boundary вызывает существующий `ModerationService`.
- Service получает актуального member через существующий `SqlAlchemyUnitOfWork`
  и разрешает чтение только active moderator/administrator.
- Существующий moderation store выбирает только `open|appealed`; для moderator
  добавляет `case_type != 'fraud_review'` до `order_by(opened_at,id)` и `limit`.
- DTO — явный allowlist: `id`, `assignment_id`, `case_type`, `status`, `revision`,
  `current_code`, `opened_at`, `resolved_at`.
- GET не вызывает `commit`, receipt, audit, outbox или ledger.
- Не добавлены domain rules, tables, migrations, dependencies, frameworks,
  services или repositories.

CB-64 import/reconciliation не использован и не отменён: endpoint читает
текущий authoritative moderation store. Import/cutover gates продолжают
действовать только для будущей миграции/deploy.

## Проверки

- `uv run ruff check ...` — green.
- `uv run ruff format --check ...` — green.
- `uv run ty check ...` — green.
- `uv run pytest tests/unit/test_web_auth.py -q --no-cov` — `12 passed`.
- targeted API/privacy/filter/effects:
  `test_web_moderation_cases_authorizes_filters_and_projects_safe_queue` —
  `1 passed`.
- отдельный browser journey:
  `test_moderation_queue_loading_empty_closed_and_back_focus` — `1 passed`.
- один контрольный non-browser suite:
  `uv run pytest -m "not browser" --no-cov -q` —
  `526 passed, 3 deselected`.

После первого final review закрыты два Major finding и повторно зелены только
затронутые targeted checks:

- initial `#moderation` сохраняется до bootstrap и открывает очередь через тот
  же GET; browser case стартует с прямого hash и также покрывает `401`;
- все web sessions создаются до before-snapshot; exact after-snapshot сравнивает
  moderation case state и counts receipts, ledger, audit, outbox;
- API matrix дополнен restricted moderator;
- targeted API и browser после исправлений — по `1 passed`; полный контрольный
  suite намеренно не дублировался.

## Simplicity audit

Ponytail `shrink`: изменение ограничено существующим owner/UoW/store, одним GET
и одним экраном. CSS и design system не расширялись; schema/dependency diff
нулевой. Удаление route/DTO/screen и двух read-параметров полностью откатывает
slice без data rollback.

## Отложено намеренно

Registration decisions, roles/status editing, config, publication/reviewer
replacement, case detail/evidence, dispute decisions, appeals, sanctions,
karma/risk/alerts/audit UI и любой generic admin platform остаются в roadmap и
не изменены этим slice.

## Остаточные gates

До commit/push/PR требуется независимый final review. После green review:
commit, push, PR, CI, merge и Jira `Готово` по разрешённому delivery route.
