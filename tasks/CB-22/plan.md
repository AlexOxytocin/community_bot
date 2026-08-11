# CB-22 — план исправления метрик пилота

## Цель

Вернуть отчёт CB-16 к уже утверждённому versioned JSON-контракту, считать karma activity по полной immutable history и доказать заявленные граничные сценарии без повторной полной регрессии.

## Изменения

1. Переименовать public report fields в `invite_conversion_rate`, `onboarding_completion_rate`, `task_fill_rate`, `task_fill_rate_48h`, `assignment_completion_rate`, `repeat_action_rate`, `weekly_retention_rate`. В `success` использовать те же базовые rate-имена: `task_fill_rate`, `assignment_completion_rate`, `repeat_action_rate`.
2. Оставить `schema_version=community_bot.pilot_metrics.v1`: это исправление реализации ещё не опубликованного контракта, а не изменение принятого контракта.
3. В `PostgresPilotMetrics` загружать karma activity из каждой строки `karma_vote_history` как `(actor_member_id, created_at)` с cutoff `created_at < to_at`; текущую mutable строку `karma_votes` для retention не использовать.
4. Добавить exact JSON-key oracle и целевые unit cases: paid partial; reward с reversal/reject не является completion; deterministic top tie; невозможное безопасное объединение малых buckets приводит к suppression; community aggregates; полный репрезентативный A–D report dataset.
5. Добавить PostgreSQL case `previous-week create → current-week revision`: один actor активен в обеих неделях, обе revisions прочитаны из history.
6. Синхронизировать runbook/checklist/retrospective и implementation report только там, где фактические имена или доказательства меняются.

## Готовность

- Все критерии Jira CB-22 сопоставлены воспроизводимым assertions.
- Целевой unit/integration контур, Ruff, ty, build и diff-check зелёные.
- Независимый final review одобряет единый готовый snapshot.
- Исправление отдельным PR вливается в `task/CB-16`; общая регрессия CB-16 не запускается повторно.
