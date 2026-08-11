# CB-13 — эскалационная контрольная проверка плана

Status: approved

Схема: `community_bot.plan_review.verdict.v1`.

## Проверенные источники

- свежие Jira `CB-13`, `CB-11`, `CB-12`, `CB-15`, ранее в текущем полном цикле
  прочитанные напрямую через Atlassian Rovo JQL API: описания, критерии
  приёмки, статусы, родители и связи;
- полный актуальный пакет `tasks/CB-13/plan-source-context.md`, `needs-info.md`,
  `plan.md`, `test-plan.md`;
- архивы двух проверок `reviews/plan/attempt-01.md`,
  `reviews/plan/attempt-02.md` и `problem-escalation.md`;
- `agents/plan-reviewer/instruction.md`,
  `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`;
- `docs/mvp/02_DOMAIN_RULES.md`, `05_BOT_INTERFACE.md`, `06_DATA_MODEL.md`,
  `07_SECURITY_AND_PRIVACY.md`, `08_MODERATION_AND_ABUSE.md`,
  `10_TEST_PLAN.md`, `11_DECISIONS_AND_OPEN_QUESTIONS.md`, включая D-014–D-023;
- ADR-0005/0006 и фактические migrations `0007`/`0008`, assignment/dispute,
  reliability, economy reversal, reputation/karma, permissions, DB UoW и
  Telegram receipt contracts.

Внешнее состояние Jira, Git remote и код не изменялись.

## Выводы по области

CB-13 остаётся одним крупным, но практичным MVP-срезом: dispute resolution и
appeal, санкции, interaction alerts/penalties, risk signals и moderation
Telegram flow. Отдельный broker, moderation service, debt model или rules
engine не вводятся. Фоновое ускорение expiry/delivery остаётся CB-15, полная
регрессия — CB-16. Семь Jira AC сопоставлены с 18 targeted scenarios, которые
запускаются одним gate после полной реализации.

## Закрытие полного review cycle

### B-001 — закрыто без регрессии

P-001–P-003 явно приняты владельцем 11 августа 2026 года:
`needs-info.md` имеет `Status: accepted`, а канонический журнал содержит
принятую D-023. `plan-source-context.md` теперь также прямо ссылается на это
решение и больше не содержит ложного открытого барьера.

### M-001 / R-001 — закрыто

Resolution/appeal state machine реализуема поверх CB-11/CB-12:

- immutable dispute opening отделён от current-case snapshot и append-only
  resolutions/appeal/evidence;
- applicability различает member/community origin и отклоняет невозможные
  combinations до эффектов;
- обычная appeal использует `resolution_reversal`, fraud — exact
  `fraud_reversal`, с source links и единым economy batch;
- append-only `reliability_outcome_corrections` даёт CB-12 projection
  однозначный effective outcome без переписывания terminal root;
- insufficient reversible credit/experience атомарно отклоняет command;
- однажды оплаченный slot остаётся занят навсегда.

Оставшийся paid-fraud разрыв закрыт минимально: active administrator открывает
case для `approved|partially_approved` через `OpenFraudCaseCommand` с reason и
evidence. Команда использует тот же assignment-scoped case gate, exact
command/update payload identity и один active-case invariant; конкурирует с
appeal/resolution под тем же gate. Только fraud resolution может обратить paid
ledger rows. При insufficient balance не остаются case, ledger, reliability,
alert, audit или receipt effects. Сценарий 15 доказывает replay, conflict, race,
source links, cache equality, alert recompute и rollback.

### M-002 / R-002 — закрыто

Duration, permissions и restore rules остались точными: restriction/suspension
имеют будущий `ends_at`, ban бессрочен, moderator не ограничивает `karma_vote`,
а stale sanction не перезаписывает более новый status.

`EffectiveMemberStatusResolver` теперь используется каждым application path,
где status влияет на authorization или projection. Read вычисляет effective
status без доверия истёкшему физическому `suspended`; mutation под member lock
сначала идемпотентно фиксирует expiry/restore, затем применяет status gate.
Поэтому CB-15 ускоряет expiry, но не определяет correctness. Сценарий 8
проверяет elapsed suspension без worker и через mutation, и через profile/read.

### M-003 — закрыто без регрессии

- Karma exclusion остаётся привязан к exact vote revision.
- Vote и exclude/restore используют один порядок pair gate → vote/revision lock;
  новая revision делает прежнее moderation decision stale.
- Любой resolution/appeal reversal пересчитывает interaction alert.
- Risk-signal key включает exact rule, UTC bucket и нормализованную сущность либо
  fingerprint; raw comment не копируется в signal/outbox/log.
- Сценарии 10, 13 и 14 сохраняют доказательство recompute, bucket replay,
  privacy и concurrency.

## Выводы по проверке

Тестовый пакет покрывает обязательные границы без чрезмерного расширения:

- migration/backfill/append-only cycle;
- freeze, все применимые resolution codes, concurrent winner и fault rollback;
- conflict matrix, appeal boundary, exact reverse, reliability folding и
  permanent paid-slot occupancy;
- sanction permissions, overlap, expiry без worker и защита нового status;
- interaction threshold/window/rearm, penalty atomicity и notes privacy;
- karma signal thresholds, revision-aware exclude/restore и отсутствие
  автоматического наказания;
- unpaid/paid fraud, exact reversal и insufficient rollback;
- synthetic Telegram replay/stale/forged/privacy и direct SQL invariants;
- общий targeted pytest без skip/deselect, migration cycle, Ruff, ty, build,
  entrypoints, link/diff/secret checks.

Все семь Jira AC имеют достижимый application flow и проверяемый oracle.

## Обязательные исправления

Нет.

## Остаточные риски

- `insufficient_reversible_balance` оставляет спор или fraud case без изменения
  до ручного следующего решения; это осознанная простая политика MVP и не требует
  debt model.
- `EffectiveMemberStatusResolver` является сквозной прикладной policy и должен
  действительно использоваться всеми перечисленными status-dependent paths;
  сценарий 8 и финальный diff review контролируют это при реализации.
- PostgreSQL aggregates и advisory gates достаточны для пилота 20–30 участников;
  оптимизация требуется только по наблюдаемой нагрузке.

Эскалационный пакет закрывает B-001, M-001–M-003 и R-001–R-003 без регрессий.
План готов к реализации после обычного handoff по процессу задачи.
