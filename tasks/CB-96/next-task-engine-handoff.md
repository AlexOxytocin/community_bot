# CB-96 — handoff следующему этапу подключения движка

Этот файл не является областью реализации CB-96. Он сохраняет уже найденные
разрывы для отдельной Jira-задачи после deployment UI.

## Что уже подключено частично

Текущий Web API обслуживает bootstrap/auth, основной member task cycle,
freeform creation, assignment/result/review/dispute, profile, karma,
leaderboard и dispute moderation. CB-96 сохраняет эти вызовы, если новый UI не
требует изменения transport/application/domain contract.

## Что потребует отдельного доказанного adapter mapping

- invitation onboarding и registration moderation;
- templates/schema-driven create/submit и result versions;
- group cancellation;
- task-detail deep link как самостоятельный read;
- ledger/reliability/audit/config histories;
- member role/status and administrative controls;
- sanctions, fraud, appeals and corrections/reversals;
- community task publication/reviewer/review/cancellation;
- interaction alerts, risk signals and penalties;
- outbound Telegram target routing для разрешённых events.

| UI surfaces | Существующий engine owner/evidence | Текущий Web status | Проверка следующей задачи |
|---|---|---|---|
| A03–A06A, S05–S07, G02–G04 | `RegistrationService` invitation/start/answer/submit/moderate | pre-member bootstrap и admin list/detail не подключены полностью | доказать bounded bootstrap и invitation projections без guest runtime |
| T04A, M04A, G08–G09 | `CatalogService`, сохранённые template/result schemas | templates/version history transport неполон | минимальные read/adapters для active immutable versions |
| M17–M19 | `TaskService` group cancellation rules | нет полного Web flow | request/response/status adapters поверх существующего owner |
| T03 deep link | `TaskService` task/card rules | detail доступен из текущего catalog context, отдельный read отсутствует | permission-safe task detail projection |
| P08–P10, G11–G14B | `EconomyService`, `ReputationService` histories/corrections | own/admin history transport неполон | allowlisted ledger/reliability reads и typed existing commands |
| G05–G07, G26 | `MemberFoundationService` role/status rules | admin management transport неполон | server-owned list/detail/allowed role-status actions |
| G15–G18 | audit/config owners и immutable config versions | safe histories/upload/activation не подключены полностью | safe audit/config projections; никакого raw payload/path input |
| S08–S12, G27–G28 | `ModerationService` sanctions/fraud/appeals | Web surfaces неполны | conflict-free commands и exact effect previews |
| G19–G22D | `TaskService`/`AssignmentService` community rules | publication/reviewer lifecycle неполон | independent-reviewer-safe adapters |
| G23–G25 | `ModerationService` interaction alerts | signals/outcome/penalty Web flow неполон | private projection и human-reviewed existing outcome |
| Telegram targets | notification outbox/event contracts | in-app inbox отсутствует | allowlisted event→target hint с fresh authorization |

Следующая задача обязана для каждого action доказать существующего
application/domain owner, текущий Web API status и минимальный adapter gap.
Новые domain rules/schema/migrations по-прежнему требуют отдельного решения.

## Граница CB-96

Пока connection отсутствует, production UI показывает `disabled_reason` или
permission-safe unavailable. Fixture data и conceptual success разрешены только
в development/tests/screenshots и никогда не считаются состоянием движка.
