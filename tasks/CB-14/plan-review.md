# CB-14 — контрольное ревью плана после изменения владельца

Status: approved

## Проверенные источники

- Свежая Jira CB-14 через Atlassian Rovo API: пять актуальных критериев
  приёмки, решение владельца от 2026-08-11 и связь `blocks` с CB-15.
- Exact staged tree `1d482253011537490132e3a01b4cb900ee18dc91`:
  принятый ADR-0008, `plan-source-context.md`, `needs-info.md`,
  `architecture-solution.md`, `plan.md`, `test-plan.md`.
- Канонические правила проекта, Jira/agent workflow, MVP PRD, доменные правила,
  security/privacy, технологический стек, планы реализации и тестирования,
  журнал решений и ADR-0005.
- Исторические `reviews/plan/attempt-01.md`, `attempt-02.md` и
  `problem-escalation.md`; прежние R2/webhook-варианты остаются только историей
  review и не трактуются как активный контракт.
- Актуальные официальные сведения Render о Pro log retention, PostgreSQL PITR,
  семидневном recovery window, image digest, pre-deploy и rollback.

## Область задачи

Активный пакет согласован со свежей Jira из пяти AC. CB-14 закрывает Q-001,
hosting/runtime, error reporting/log retention/privacy, PostgreSQL recovery и
синхронизацию документов. Cloudflare R2, external daily backup, application
object storage и webhook исключены владельцем и не обещаны как результат CB-14
или CB-15.

A-001 закрыто полностью:

- `plan-source-context.md` перечисляет только актуальные in-scope решения;
- `architecture-solution.md` больше не делает evidence storage и transport
  escalation предпосылками CB-15;
- цель `plan.md` ограничена Q-001, hosting, error/log retention и PostgreSQL
  recovery, а не «всеми эксплуатационными вопросами».

## Логика решения

Пять Jira AC закрываются непротиворечивым контрактом:

1. Межпрофессиональная закрытая когорта: 20–30 приглашённых взрослых, ручное
   одобрение, 4–6 недель.
2. Render Pro, два image-backed процесса и managed PostgreSQL 18 в одном
   project/region.
3. Render logs 14 дней, Sentry events максимум 30 дней и deny-by-default
   privacy/scrubbing.
4. Единственный backup — Render PostgreSQL PITR: recovery window семь дней,
   `RPO <= 24h`, `RTO <= 4h`, restore drill до пилота и каждые четыре недели.
   External dump и восстановление старше window не обещаются.
5. Принятый ADR-0008 и перечисленные канонические документы синхронизируются,
   тогда как исключённые вопросы остаются открытыми вне CB-14.

P-002 не регрессировало. Новый GHCR digest назначается image-backed `worker`;
его единственный pre-deploy из нового image выполняет Alembic migration под
PostgreSQL advisory lock, а `bot` не мигрирует. Expand-only совместимость,
old/new smoke, порядок `worker → bot`, failure/partial rollback без schema
downgrade и retention предыдущего digest минимум 30 дней сохранены.

## Альтернативы и риски

Пакет остаётся пропорциональным MVP: не добавляет Redis, Celery, Kubernetes,
публичный API, внешний backup store или webhook. Потеря данных старше
семидневного PITR window прямо принята владельцем как ограничение пилота, а не
скрыта за неопределённой будущей инфраструктурой.

## Стратегия проверки

Сценарии 1–12 соответствуют пяти Jira AC. Сценарий 4 сохраняет полный release
gate P-002; сценарии 7–8 доказывают PITR contract и restore oracle; сценарий 9
проверяет отсутствие R2/daily dump и сохранение object storage/webhook вне
scope. Фактические provisioning, deployment smoke и PITR restore корректно
оставлены acceptance gates CB-15. Full regression для документальной CB-14 не
требуется.

## Обязательные исправления

Нет.

## Остаточные риски

- Фактический семидневный PITR window и достижимость RTO нужно подтвердить на
  выбранном Render workspace до пилота реальным restore drill.
- Одобрение плана не утверждает, что облачные ресурсы уже созданы или что CB-15
  реализована; это отдельная следующая задача с собственными проверками.
