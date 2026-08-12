# CB-30 — финальный эскалационный plan review

Status: approved

## Reviewed sources

- свежая Jira CB-30 через Atlassian Rovo: Bug, High, `cb16-regression`, пять критериев приёмки, связь с CB-29 и блокировка CB-24;
- `tasks/CB-30/problem-escalation.md`, `reviews/plan/attempt-01.md`, `reviews/plan/attempt-02.md`;
- актуальные `plan-source-context.md`, `plan.md`, `test-plan.md`;
- обязательные project rules/workflow, MVP domain/interface/data/moderation/decision documents и ADR-0006;
- фактические application/transport/schema-контракты task, assignment, moderation, reputation, conversation и production `_dispatcher`.

## Scope findings

- E-001 закрыт: community task сохраняет `created_by_admin_id` и `reviewer_admin_id`, reviewer выбирается из другого active administrator, creator/performer/conflicted reviewer запрещены, а утрата пригодности ведёт в `reviewer_required` с безопасной replacement-командой и определёнными deadline semantics.
- E-002 закрыт: `conversation_states` является единственным durable владельцем свободного текста; claim/switch/cancel выполняются под identity gate, router вызывает только сохранённый flow, restart и collision разных draft stores имеют явный oracle.
- E-003 закрыт: post-payment fraud и raw-karma read/exclude/restore достигаются только через выданные ботом карточки. Fraud остаётся administrator-only; raw read требует `karma_review`, аудируется и не раскрывается member/moderator; mutation сверяет точную vote revision.
- E-004 закрыт: request appeal разрешён только active performer/creator — стороне case — в семидневном полуинтервале, а appealed case решает другой conflict-free active administrator. Сценарий 9 отдельно доказывает оба шага и запреты outsider/original conflicted resolver.
- Область остаётся практичным regression-MVP: read projections, существующие routers/services, единый conversation owner и одна ограниченная migration без web-admin, нового workflow framework или полной регрессии продукта.

## Design findings

- Обязательных замечаний нет. Все mutation остаются в существующих application/storage UoW с повторной авторизацией, update/identity/entity gates, receipt-before-commit и существующими ledger/audit/outbox invariants.
- Технические IDs допустимы только внутри callback payload; пользователь их не вводит, payload проверяется на лимит 64 байта, stale/перехваченный callback повторно авторизуется.
- Privacy contract согласован: обычные карточки не содержат UUID, revision, JSON, evidence и приватные комментарии; raw karma возвращается только разрешённому administrator в личном ответе с audit.

## Verification findings

- Jira AC 1: сценарии 1–22 покрывают output-driven assignments, result, review, dispute, moderation, appeal, sanctions, karma, community task и interaction alert.
- Jira AC 2: позитивные и запретительные role/permission oracles присутствуют для performer/creator/reviewer/moderator/administrator, fraud, appeal, sanctions, alerts и raw karma.
- Jira AC 3: production `_dispatcher` работает с PostgreSQL и fake Bot API; каждый следующий text/callback берётся только из предыдущего захваченного ответа, без DB-driven ID, ручной сборки callback и импортов будущих callback constants.
- Jira AC 4: member full/partial/reject/no-show, community reward, appeal/fraud reversal и bounded interaction penalty проверяются через видимый UI с итоговыми status/ledger oracles.
- Jira AC 5: exact replay, stale callback, concurrent duplicate, insufficient rollback и отсутствие второго receipt/ledger/audit/outbox проверяются целевыми сценариями; migration cycle и legacy preservation определены.
- Проверки пропорциональны задаче: широкий targeted PostgreSQL/Dispatcher E2E и обычные quality gates выполняются здесь, а единый полный regression и реальный Telegram connector остаются в CB-29 после слияния regression Bugs.

## Required actions

- Нет.

## Residual risks

- Реализация крупная по числу Telegram-веток, поэтому implementation report должен дать явное соответствие всех 26 сценариев фактическим тестам. Это контролируемый риск выполнения, а не пробел плана.
