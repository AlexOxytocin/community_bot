# CB-69 — исходный контекст плана

## Точный baseline

- `origin/main`: `49e8a7a360f1f8f8d5e5c5a5d827c17511ba6a05`.
- Jira: `CB-69`, родитель `CB-48`, статус при планировании — «В работе».

## Обязательные источники

- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` — Mini App-only, Jira/branch gates,
  Ponytail и запрет дублирования backend.
- `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md` — Level 3 plan/review и
  delivery route.
- `docs/adr/0017-lean-community-mini-app-core.md` — сохраняются durable
  submission draft ownership/revision/restart/resume/exact-confirm semantics.
- `docs/adr/0019-single-pilot-post-task-delivery-gate.md` — deployable frontend
  после merge требует exact release, pilot activation и public smoke.
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md`, `docs/mvp/02_DOMAIN_RULES.md` —
  assignment result/review lifecycle и права участника.
- `src/community_bot/application/assignments.py` — существующие
  `begin_submission`, `save_submission_draft`, `confirm_submission_draft`.
- `src/community_bot/infrastructure/db/assignments.py` и `models.py` —
  existing durable draft/result owners; новая schema не нужна.
- `src/community_bot/transport/web.py` и `transport/static/app.js` — текущие
  session/Origin/idempotency/static-client границы.
- `src/community_bot/domain/tasks.py` — existing free-form result validator;
  `template_id is None` является authoritative discriminator без schema copy.

## Принятое сужение

Прямой web submit отклонён: он создал бы временный второй путь мимо принятого
durable preview. CB-69 переиспользует три существующие application operation.
Template и неизвестная future schema fail closed до mutation; их UI не
маскируется generic renderer или frozen schema fingerprint в этой задаче.

Новые ADR, migration, dependency, service/repository/UoW и deployment
infrastructure не требуются. CB-68 merged/deployed в текущем baseline и передал
ownership общих static-файлов CB-69.
