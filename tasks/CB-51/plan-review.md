# CB-51 — терминальная проверка плана compact backend

Schema: `community_bot.plan_review.verdict.v1`

## Проверенные источники

- Jira CB-51 и комментарий `10227` через Atlassian Rovo.
- `tasks/CB-51/plan-source-context.md` и актуальный
  `tasks/CB-51/plan.md`.
- Принятый ADR-0017 и полный `tasks/CB-64/parity-map.json`.
- Существующие модели, karma eligibility, backup/restore scripts и
  канонические продуктовые/доменные правила.
- Ponytail full и `ponytail-review` для проверки лишних слоёв и зависимостей.

## Итог повторной проверки

Обязательных замечаний нет. Исправленный пакет устраняет все три блокера
предыдущего terminal review и согласован с Jira CB-51.

### Backup и restore

- `plan.md:L58-L62` ограничивает изменение существующими Python ops вместо
  нового backup framework.
- `plan.md:L93-L98` задаёт поток `pg_dump → gpg` сразу в encrypted file,
  secret-файл вне git, отсутствие plaintext dump, SHA-256 manifest и
  hash-before-decrypt restore.
- `plan.md:L188-L210` использует абсолютный secure artifact root вне repository,
  owner-only ACL и явные stop conditions для пути, ACL, `gpg`, secret file и
  hash mismatch.
- Backup, manifest, inventory и quarantine не помещаются в worktree. Restore
  остаётся обязательным исполнимым Slice 2 gate, а не заявляется заранее
  выполненным.

### Provenance и test-run quarantine

- В `parity-map.json` добавлено глобальное правило: каждая legacy row получает
  ровно один provenance `public|synthetic|ambiguous`; `ambiguous` блокирует
  import.
- Table transforms теперь различают import public rows и archive synthetic
  task/assignment/case closure для tasks, ledger, audit, outbox, notifications,
  reputation и moderation data.
- Member cached totals больше не копируются. `plan.md:L82-L87` и oracles
  `ECONOMY`, `KARMA`, `RELIABILITY`, `RISK_ALERTS`, `FULL_IMPORT` требуют
  пересчёта credit/experience/level/karma/reliability/risk только из
  импортированных public rows.
- Эвристики по member ID, времени и названию запрещены; недоказуемое
  происхождение останавливает import. Поэтому derived karma/risk row не может
  быть молча удалена или ошибочно объявлена public.

### Deterministic rerun

- `plan.md:L102-L109` и `L201-L204` задают два последовательных `apply`.
- Второй запуск обязан вернуть `second_run_mutations=0`; любое изменение строки
  является stop condition. `FULL_IMPORT` oracle синхронизирован с этим правилом.

### AUTH boundary

- `plan.md:L115-L122` переводит только внутренние session/operation primitives
  в `backend_ready`.
- Passing nodes CB-51 ограничены `REGISTRATION`, `MEMBERS` и
  `AUDIT_IDEMPOTENCY`.
- Telegram `initData`/Origin/revoke/redaction capability `AUTH` остаётся
  `planned_external` за CB-52; финальный backend gate повторяет ту же границу.

## Ponytail

`Lean already. Ship.`

План не вводит broker, cache, command bus, repository/UoW/DI framework или
generic event framework. `gpg` имеет доказанную необходимость: ADR-0017 требует
encrypted production backup, а stdlib не предоставляет эквивалентного
шифрования.

## Validation evidence

- Jira comment `10227` совпадает с фактическими изменениями плана и parity map.
- JSON parse: `43` legacy tables, `43` table links, `26` capabilities и `11`
  constraints; provenance rule и обновлённый `FULL_IMPORT` oracle присутствуют.
- Machine checks подтвердили: cached totals не переносятся как authoritative,
  `zero ambiguous`, encrypted SHA restore, `second apply mutates zero`,
  `backend_ready` и `AUTH planned_external` явно зафиксированы.
- `uv run pytest tests/unit/test_restore_drill.py tests/architecture
  tests/documentation tests/smoke -q --no-cov
  --ignore=tests/architecture/test_agent_orchestration_policy.py` —
  `105 passed`.
- `git diff --check` по CB-51 plan/review и parity map — без ошибок.

## Остаточная неопределённость

- Реальный состав shared/production DB станет известен только после read-only
  inventory. Ноль `ambiguous` является обязательным gate, поэтому неизвестные
  данные не разрешают destructive fallback.
- `gpg` отсутствует в текущем локальном Windows PATH. План корректно делает его
  наличие preflight/stop condition; encrypted backup и restore должны быть
  фактически выполнены в Slice 2 до любого удаления legacy owner.
- C02 может обосновать двенадцатую active-pointer table. Ceiling явно подчинён
  parity и не разрешает ослабить immutable config history.

Status: approved
