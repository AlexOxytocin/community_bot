# CB-22 — целевой план проверки

| № | Сценарий | Ожидаемый результат |
|---|---|---|
| 1 | Exact `model_dump()` верхнего уровня | Набор ключей полностью совпадает с `community_bot.pilot_metrics.v1`; старых сокращённых rate-ключей нет |
| 2 | Success thresholds | Пороговые booleans используют `task_fill_rate`, `assignment_completion_rate`, `repeat_action_rate` |
| 3 | Partial paid result | Assignment входит в completion numerator |
| 4 | Reward и его reversal/reject | Assignment не входит в effective completion numerator |
| 5 | Равенство результата у нескольких performers | Top 20% выбирается детерминированно по UUID |
| 6 | Малые buckets нельзя объединить до `count >= 3` | Значения уходят в `suppressed_count`, небезопасные labels отсутствуют |
| 7 | Community task и community reward | Published, paid completed и credits issued посчитаны отдельно от member pairs |
| 8 | Репрезентативный A–D dataset | В одном отчёте доказаны invitation/onboarding, task/assignment, ledger/reversal, karma/retention и privacy-safe aggregates |
| 9 | PostgreSQL: karma revision в каждой из двух недель | Adapter возвращает обе immutable history revisions; retention = `1/1` |
| 10 | Privacy/output/docs | Нет member/Telegram/private text; runbook/checklist/retrospective используют exact contract |

Команды: целевой `pytest` для unit metrics, PostgreSQL pilot adapter и A–D dataset; `ruff format --check`, `ruff check`, `ty check`, `uv build`, `git diff --check`. Полный `pytest` не запускается.
