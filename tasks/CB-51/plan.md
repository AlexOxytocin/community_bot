# CB-51 — один Pareto-проход перед Mini App

## Результат

За один проход удалить очевидную техническую обвязку старого Telegram/test-run
управления, не менять бизнес-движок, PostgreSQL schema и миграции, после чего
перейти к web API. Полный compact-schema/importer из прежнего плана отложен:
для текущего продукта на 20–30 человек его цена выше подтверждённой пользы.

Уровень риска: `2`. ADR-0017 остаётся направлением возможного будущего
сокращения, но не является областью этого прохода.

## Что меняется

1. Удалить незавершённые CB-51 scaffolding для compact importer, encrypted
   migration backup и универсального deletion contract. Они не нужны без
   фактической миграции схемы.
2. Удалить неиспользуемый runtime-код управления test-run lifecycle:
   `TestRunService`, его UoW protocols, create/status/cleanup/finish adapters и
   тесты этого удалённого API.
3. Сохранить `test_runs`, `test_run_participants`, `test_run_id`,
   `active_scope`, `participant_ids` и post-removal quarantine test. Поэтому
   synthetic rows по-прежнему не попадают в обычные tasks/assignments/outbox.
4. Оставить в `application/conversations.py` только используемый `TextFlow`;
   удалить service/protocol с единственным тестовым caller и его unit test.
5. Не менять domain/application функции задач, профилей, ledger, levels,
   leaderboard, karma, reliability, templates, disputes, appeals, sanctions,
   risk alerts, notifications и versioned config.

## Что намеренно не делаем

- новую schema, importer, data migration или backup format;
- FastAPI/web UI — следующие CB-52—CB-55;
- переписывание больших task/moderation/economy services;
- удаление полезных integration tests только ради числового потолка;
- изменение `agents/config.yaml`, принадлежащее другому рабочему потоку.

## Проверяемый выигрыш

- production Python LOC уменьшается относительно `main`;
- test LOC и число тестов уменьшаются только вместе с удалённым API;
- migrations и зависимости не меняются;
- один quarantine integration test остаётся самостоятельным и не импортирует
  helper из удалённого lifecycle test;
- все оставшиеся unit/architecture/documentation/smoke tests и точечные
  PostgreSQL tests проходят.

## Gate

```powershell
uv run pytest tests/integration/test_legacy_test_run_quarantine.py -q --no-cov
uv run pytest tests/unit tests/architecture tests/documentation tests/smoke -q --no-cov
uv run ruff format --check .
uv run ruff check .
uv run ty check
git diff --cached --check origin/main
git diff --cached -U0 origin/main | uv run python -c "import re,sys; text=''.join(line[1:] for line in sys.stdin if line.startswith('+') and not line.startswith('+++')); patterns=(r'AKIA[0-9A-Z]{16}', r'gh[pousr]_[A-Za-z0-9]{36,}', r'-{5}BEGIN .* PRIVATE KEY-{5}', r'(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*\S{8,}'); hits=[pattern for pattern in patterns if re.search(pattern,text)]; print('secret_scan=pass' if not hits else 'secret_scan=fail:' + ','.join(hits)); raise SystemExit(bool(hits))"
```

Stop: любой import/caller удалённого API вне удаляемых тестов или расхождение
quarantine. Rollback: один commit этого Pareto-прохода; schema/data не меняются.
