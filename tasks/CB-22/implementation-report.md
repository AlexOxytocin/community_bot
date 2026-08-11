# CB-22 — отчёт о реализации

## Результат

Исправлены все три дефекта из Jira CB-22:

- `community_bot.pilot_metrics.v1` сериализует exact поля `invite_conversion_rate`, `onboarding_completion_rate`, `task_fill_rate`, `task_fill_rate_48h`, `assignment_completion_rate`, `repeat_action_rate`, `weekly_retention_rate`; nested `success` использует те же три пороговых rate-имени;
- karma activity читается из каждой immutable revision `karma_vote_history` по `actor_member_id` и `created_at`, а не из текущего mutable vote;
- добавлены прямые oracles для partial reward, reversed reward, community aggregates, deterministic top tie, privacy suppression и репрезентативного A–D dataset.

## Доказательства критериев Jira

| Критерий | Доказательство |
|---|---|
| Exact public JSON contract | Unit assertion по `json.loads(model_dump_json())` и CLI key scan |
| Success thresholds используют те же поля | Exact nested `success` key assertion и threshold assertions |
| Все immutable karma revisions | PostgreSQL adapter выбирает `karma_vote_history.actor_member_id/created_at` |
| Previous-week create → current-week update | Изолированный PostgreSQL test даёт retention `1/1 = 1.0000` |
| Partial/reversal/tie/suppression/community | Пять прямых unit cases с точными numerator/denominator/output assertions |
| A–D report dataset | Отдельный representative test с invitation, onboarding, member/community tasks, assignments, ledger, alert, dispute и cross-week karma |
| Честный targeted gate | Ниже перечислены только фактически запущенные команды; full regression не повторялась |

## Выполненные проверки

- `uv run ruff format --check .` — `323 files already formatted`;
- `uv run ruff check .` — успешно;
- `uv run ty check src tests` — успешно;
- целевой unit + PostgreSQL integration contour — `9 passed`, `2 deselected`; два deselected относятся к migration CB-23;
- `uv build` — sdist и wheel собраны;
- `community-pilot-report` на пустом периоде — exact 22 top-level keys и 3 exact success keys;
- `git diff --check` — успешно.

Полный `pytest` не запускался повторно: authoritative regression CB-16 уже зафиксирован как `369 passed`, а процесс требует исправлять найденные после него дефекты отдельными ветками и целевыми проверками.

## Интеграция

Ветка `task/CB-22` должна быть влита отдельным PR в `task/CB-16`. После слияния CB-22 и CB-23 родительский CB-16 проходит единый повторный final review без дублирования полной регрессии.
