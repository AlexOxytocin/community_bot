# Release 2 — Mini App-only направление

**Статус:** принято владельцем
**Каноническое решение:** [ADR-0016](../adr/0016-mini-app-only-runtime.md)
**Эпик:** `CB-48`

## Результат

Release 2 заменяет старый Telegram chat UI новым Mini App/web UI поверх существующего backend. Параллельного fallback-бота и обязательного паритета с его меню нет.

Сохраняются:

- domain/application use cases и PostgreSQL UoW;
- ledger кредитов и опыта, audit и idempotency receipts;
- transactional outbox, worker и дедлайны;
- роли, статусы, permissions и ownership;
- каталог, задания, назначения, споры, карма и надёжность;
- неизменяемая история Alembic и защита test-run данных.

Telegram остаётся только для запуска Mini App, auth proof/deep link и коротких исходящих уведомлений без callback UI.

## Очередность

1. `CB-62` — очистка старого UI/runtime и фиксация границы.
2. `CB-51` — завершённая Pareto-cleanup backend без schema consolidation.
3. `CB-52` — минимальная web foundation: Telegram proof, короткая server
   session, internal `ActorContext` и пять read projections. Первый domain
   write и его operation identity добавляются в `CB-53` вместе с реальным UI
   consumer.
4. `CB-53` — frontend shell, routing и platform bridge.
5. `CB-54`—`CB-55` — продуктовые экраны и административные сценарии.
6. `CB-56` — внутренний `community-web` process и честный readiness текущего backend.
7. `CB-65` — отдельный image↔host-package provenance/security gate будущего rollout.
8. `CB-57` — public HTTPS, production deployment и live Mini App acceptance.

Compact DB import/cutover остаётся будущей областью `CB-64` и не блокирует
internal web readiness текущей схемы.

## Обязательные свойства

- backend остаётся единственным источником бизнес-состояния;
- frontend не вычисляет права и допустимые переходы;
- auth proof проверяется server-side;
- mutation replay/conflict детерминирован;
- state, ledger, audit и outbox не расходятся;
- прямой URL не обходит authorization или rollout gate;
- internal readiness не считается production deployment или live acceptance;
- будущий deployment не объявляется готовым без PostgreSQL, migration, immutable
  image↔host-package provenance и restore доказательств.

## Manual-first release contract

Принятый [ADR-0018](../adr/0018-reviewed-image-and-host-package-tuple.md)
ограничивает CB-65 публикацией immutable image и одного release bundle из
проверенного merge tree. Workflow не имеет production environment, SSH,
deploy key, forced command и server authority.

В CB-57 владелец отдельно выбирает exact green release run, вручную переносит
его единственный artifact и после host preflight запускает установленный
verifier/activator как root. Host проверяет внутреннюю согласованность
commit↔image↔package и root-owned bytes; cryptographic external authorship
artifact этим pilot contract не доказывается.

Routine activation допускает только уже совместимую схему: target, current и
live DB migration heads должны совпасть. Initial migration и любой
schema-changing rollout требуют отдельного owner-authorized gate. При
`pending` backup/restore блокируются; восстановление — exact rerun либо один
явный rollback на единственную previous tuple, без automatic recovery.

## Post-task delivery

Принятый [ADR-0019](../adr/0019-single-pilot-post-task-delivery-gate.md)
связывает каждый deployable merge с exact immutable artifact, manual-first
activation на одном pilot, public URL smoke и Jira evidence. Docs/tests/
`tasks/**`-only задачи получают явный skip. Migration-changing release требует
owner gate; `Done` до green public smoke допускается только по явному
документированному waiver. Deliveries выполняются последовательно, с одним
compatible rollback и без automatic CD/SSH framework.
