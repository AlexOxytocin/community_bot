# CB-51 — отчёт о Pareto-рефакторинге

## Итог

За один проход удалена неиспользуемая техническая обвязка, оставшаяся после
отказа от старого Telegram UI. Бизнес-движок, PostgreSQL schema, миграции,
outbox, worker и зависимости не менялись.

Воспроизводимый функциональный diff `git diff --cached --stat origin/main --
src tests`: 8 файлов; production-код сокращён на 414 строк, тесты — на 420
строк после переноса active-run privacy oracle. Task artifacts считаются
отдельно, потому что `final-review.md` меняется самим reviewer-ом. Незавершённый
compact-import/backup spike из предыдущих коммитов ветки отменён и не входит в
итоговый net diff.

## Изменения

1. `application/conversations.py` сокращён до используемого `TextFlow`.
   `ConversationService` и UoW protocols удалены: production callers у них не
   было.
2. `application/test_runs.py` сокращён до `TestRunScope`. Удалён lifecycle API,
   который потерял runtime caller вместе с управляющим Telegram CLI.
3. В PostgreSQL adapter удалены create/status/cleanup/finish test-run методы.
   Сохранены `active_scope` и `participant_ids`, необходимые fail-closed
   фильтрации.
4. Удалены три test-файла, проверявшие только удалённые API. Quarantine test
   стал самостоятельным и по-прежнему проверяет active/completed synthetic
   tasks, assignments и outbox.
5. Полная compact-schema/importer миграция отложена до появления измеримого
   bottleneck. Это исключает второй проект внутри подготовки Mini App.

## Сохранённый продуктовый контур

Не менялись задачи и профили, karma, levels, leaderboard, reliability,
group/community tasks, templates, disputes, appeals, sanctions, interaction
alerts, notifications, ledger и versioned product config. Таблицы
`test_runs`/`test_run_participants`, поля `test_run_id` и история Alembic
сохранены.

## Проверки

- quarantine integration: `1 passed`;
- полный suite без несвязанного orchestration-policy файла: `498 passed in
  284.84s`;
- unit/architecture/documentation/smoke с тем же исключением: `359 passed`;
- Ruff format: `209 files already formatted`;
- Ruff lint: pass;
- `ty check`: pass;
- поиск удалённых symbols в `src tests`: совпадений нет;
- diff migrations/dependencies относительно `origin/main`: пусто;
- `git diff --cached --check`: pass.
- scan credential-shaped значений в добавленных staged lines: pass.

`tests/architecture/test_agent_orchestration_policy.py` исключён из двух
агрегатных прогонов: девять его cases падают на незакоммиченной несвязанной
правке `agents/config.yaml`. Файл не входит в CB-51 и не был изменён или
добавлен в index.

## Остаточный риск

Этот проход не уменьшает число доменных таблиц и не строит web API. Он только
снимает очевидный мёртвый слой с минимальным blast radius. Следующий полезный
шаг — CB-52: тонкий API над уже сохранённым движком, без нового framework слоя
на каждую операцию.
