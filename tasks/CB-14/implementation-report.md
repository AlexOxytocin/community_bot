# CB-14 — отчёт о реализации

## Результат

Принят единый профиль пилота и закрыты пять актуальных критериев Jira CB-14.
Q-001 закрыт D-024; hosting, release, error reporting/log retention и
PostgreSQL recovery закреплены ADR-0008.

По явному решению владельца external daily backup, application object storage и
webhook исключены из CB-14. Jira description и критерии синхронизированы через
Atlassian API до изменения канонических документов.

## Принятые решения

- Когорта: закрытое межпрофессиональное сообщество практической взаимопомощи,
  20–30 приглашённых взрослых участников, ручное одобрение, 4–6 недель.
- Runtime: Render Pro, два image-backed background workers, managed PostgreSQL
  18 в одном project/region.
- Release: один reviewed `linux/amd64` image в GHCR по SHA-256 digest,
  единственный worker pre-deploy migration gate, expand-only schema,
  последовательность `worker → bot` и partial rollback без downgrade.
- Наблюдаемость: JSON-логи Render 14 дней; scrubbed Sentry error events максимум
  30 дней без Telegram payload, секретов и приватного пользовательского текста.
- Recovery: только managed Render PITR, recovery window семь дней,
  `RPO <= 24h`, `RTO <= 4h`, restore drill до пилота и каждые четыре недели.

## Изменённые источники

- `docs/adr/0008-pilot-runtime-and-operations.md` — статус `Принято` и полный
  эксплуатационный контракт.
- `01_PRODUCT_REQUIREMENTS.md` — ниша, размер, доступ и длительность пилота.
- `TECH_STACK.md` — Render/GHCR/release/readiness.
- `07_SECURITY_AND_PRIVACY.md` — PITR, RPO/RTO и restore oracle.
- `09_IMPLEMENTATION_PLAN.md` — точная область CB-15 и снятые барьеры.
- `10_TEST_PLAN.md` — provisioning, scrubber и PITR readiness checks.
- `11_DECISIONS_AND_OPEN_QUESTIONS.md` — D-024, закрытый Q-001 и два оставшихся
  открытых технических вопроса.
- `HANDOFF.md` и `PROJECT_CONTEXT.md` — актуальный handoff и ближайший результат.

## Проверки

- `git diff --check` — успешно.
- Локальные Markdown-ссылки в 17 изменённых/новых файлах — без ошибок.
- Поиск старых формулировок о неопределённой нише/провайдере и этапе 0 — чисто.
- R2 и external daily backup отсутствуют в активном эксплуатационном контракте;
  старые варианты сохранены только в review history CB-14.
- Full pytest не запускался: runtime-код, schema и зависимости не менялись.
  Общая регрессия остаётся CB-16.

## Остаточные обязательства CB-15

Фактические Render/Sentry resources ещё не созданы. CB-15 должна реализовать
deployment manifest, GHCR pipeline, outbox delivery, retries, heartbeat,
readiness, scrubber, operational runbook и реальный PITR restore drill. До
provisioning нужно подтвердить текущие возможности оплаченного плана.
