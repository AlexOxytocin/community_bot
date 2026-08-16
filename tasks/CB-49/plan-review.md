# CB-49 — повторное ревью плана

Схема: `community_bot.plan_review.verdict.v1`.

Status: approved

## Проверенные источники

- актуальная Jira `CB-49`: цель, область, критерии приёмки, статус, комментарий
  планирования, родитель `CB-48` и связь, по которой CB-49 блокирует CB-51;
- актуальная Jira `CB-48`: capability эпика, ограничения, parity-критерии и
  связь `Relates` с CB-24;
- актуальная Jira `CB-24`: описание и комментарии владельца от 2026-08-16,
  разрешающие architecture/parity R2 параллельно пилоту без новой экономики,
  монетизации, публичной регистрации и новых продуктовых направлений;
- полный актуальный пакет `tasks/CB-49/plan-source-context.md` и
  `tasks/CB-49/plan.md` после единого цикла исправлений первого review;
- предложенный `docs/adr/0014-multi-interface-release-2.md` и правила
  `docs/adr/README.md`; статус ADR остался `Предложено`;
- первое ревью CB-49 со всеми четырьмя обязательными исправлениями;
- `agents/plan-reviewer/instruction.md`, config, шаблон результата и
  `agents/README.md`;
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`, `docs/AGENT_WORKFLOW.md` и
  `docs/JIRA_WORKFLOW.md`;
- `docs/mvp/README.md`, `01_PRODUCT_REQUIREMENTS.md`, `02_DOMAIN_RULES.md`,
  `03_USER_FLOWS.md`, `05_BOT_INTERFACE.md`, `07_SECURITY_AND_PRIVACY.md`,
  `TECH_STACK.md` и `11_DECISIONS_AND_OPEN_QUESTIONS.md`;
- ADR-0004, ADR-0005, ADR-0006, ADR-0009, ADR-0011 и
  `docs/operations/PILOT_RUNBOOK.md`;
- официальная документация Telegram Mini Apps по `initData`, недоверенному
  `initDataUnsafe`, themes, safe area, launch modes и `start_param`:
  <https://core.telegram.org/bots/webapps>;
- визуальный референс владельца и его исходное направление палитры/типографики:
  <https://feat-alex-neon-landing-alex-neon.ks-design.workers.dev/>;
- фактические import boundaries, `pyproject.toml` и application-контракты,
  которые сейчас используют `telegram_user_id` и `update_id`.

Внешнее состояние Jira, Git remote и Telegram не изменялось.

## Область задачи

Область CB-49 соответствует Jira и эпическому capability. Задача фиксирует
долговременный продуктовый и архитектурный контракт, но не объявляет
реализованными HTTP API, frontend, auth/session, deployment, Release 1 tag или
browser UI. Сохраняются модульный Python-монолит, одна PostgreSQL, единые
application/domain правила, bot fallback и parity-ограничение.

Связь с CB-24 согласована: актуальное описание самой истории и комментарии
владельца разрешают R2 parity параллельно пилоту, одновременно запрещая до его
данных новую экономику, монетизацию, публичную регистрацию и новые продуктовые
направления. Противоречия источников нет.

Финальная палитра, typography и design tokens корректно вынесены в CB-58.
ADR-0014 фиксирует только нужные для multi-interface архитектуры ограничения:
semantic tokens, Telegram themes, accessibility, safe areas, mobile-first и
готовность к responsive browser layout.

## Логика решения

Выбранная форма — два inbound transport поверх одних application services —
сохраняет существующие доменные и транзакционные инварианты. FastAPI остаётся
transport-слоем, React/TypeScript/Vite — одним SPA-клиентом, а Telegram SDK
изолирован в `PlatformBridge`. Отдельный browser backend, копия frontend
business logic, Redis, broker и микросервисы не вводятся.

Все обязательные замечания первого review закрыты без расширения области.

1. **Identity/session/authorization contract закрыт.** Subject
   `ActorContext` — внутренний `member_id`; provider/session/time допустимы
   только как authentication/audit metadata. Role, status, permissions и
   ownership не считаются доверенными session claims и заново разрешаются из
   PostgreSQL каждым защищённым use case. Telegram proof связывается только с
   существующим member, будущий browser adapter выдаёт тот же internal subject
   и не создаёт публичную регистрацию. Session format, lifetime, CSRF и
   revocation обоснованно оставлены security review CB-52, но не могут заменить
   свежую server-side authorization.
2. **Operation identity protocol закрыт.** Зафиксированы
   `transport_namespace`, internal actor, external key, command и canonical
   payload fingerprint; уникальный scope receipt, exact replay, conflict при
   другом command/payload, детерминированный outcome и одна транзакция для
   receipt/domain/ledger/audit/outbox. Telegram и HTTP namespaces не
   маскируются друг под друга, а cross-transport races закрываются domain state,
   unique constraints и locks.
3. **`PlatformBridge` закрыт как проверяемая граница.** Определены capability
   detection, theme/viewport/safe-area events, back/close, haptics, Telegram
   links и start parameter; опасный молчаливый no-op заменён явным
   `supported|unsupported` и fallback. Bridge не хранит business state и не
   выполняет authorization. `start_param` и прямой URL являются только
   недоверенной навигацией, а доступ к объекту повторно проверяет API.
4. **Rollout и process gates закрыты.** Feature flags применяются server-side
   fail-closed до use case; отсутствующая или невалидная конфигурация означает
   `disabled`, прямой URL/HTTP не обходят gate. YAML-критерий имеет явное
   `not applicable` при отсутствии YAML diff и требует parse gate при его
   появлении. Статус ADR меняется на `Принято` только после этого review,
   показа точной редакции владельцу и отдельного явного решения.

## Альтернативы и риски

Альтернативы рассмотрены на достаточной глубине: отдельное Mini App приложение,
`sendData` как основной transport, Telegram proof внутри use cases,
Python-rendered UI/HTMX, Next.js/SSR, микросервисы и длинная `release/2`
отклонены по конкретным причинам. Выбор не создаёт универсального plugin
framework и ограничивает browser readiness двумя реальными extension points —
auth adapter и `PlatformBridge`.

Release strategy совместима с ADR-0011: Release 1 фиксируется только после
acceptance аннотированным `v1.0.0`, GitHub Release и immutable image digest;
`main` остаётся выпускаемым; постоянная `release/1.x` требует отдельного
фактического patch lifecycle. До принятия CB-56 продолжает действовать R1
контракт ADR-0009/D-025 без нового public ingress. CB-56 обязана отдельно
зафиксировать HTTPS edge, TLS, topology, rollout и rollback для R2.

Оценки `10–15%` текущей foundation-подготовки и `20–35%` будущего browser mode
прямо обозначены как диапазоны планирования для неизменной функциональности.
SEO, публичная регистрация, платежи, несколько сообществ и новый продуктовый
срез из оценки исключены.

## Стратегия проверки

План сопоставляет Jira-критерии с проверяемыми документальными assertions:

- capability и parity coverage по всем поверхностям Release 1;
- internal `member_id` и свежая server-side authorization;
- namespace/scope/fingerprint/outcome и replay/conflict operation protocol;
- capability/fallback и trust boundary `PlatformBridge`;
- fail-closed server-side feature flags при прямом API/URL;
- отсутствие заявлений о уже реализованном API/frontend;
- локальные Markdown links, русский язык, diff-check, secret-like scan и
  условный YAML parse gate;
- независимый final review уровня 3.

Ручной `test-plan.md` и live Telegram gate для CB-49 не нужны: задача не меняет
runtime и не заявляет пользовательский сценарий выполненным. Deployment/live
acceptance остаются в CB-50 и runtime-задачах R2. Это соответствует
пропорциональному процессу ADR-0004.

## Обязательные исправления

Нет.

## Остаточные риски

- ADR-0014 всё ещё имеет статус `Предложено`. После этого review владелец должен
  увидеть точную редакцию и явно принять её; только затем допустим статус
  `Принято` и реализация capability-документов.
- Session representation, lifetime, CSRF и revocation без Redis остаются
  решением CB-52 и требуют отдельной security-проверки.
- Domain/TLS/edge, feature-flag storage/cohort management и production topology
  остаются CB-56; до её принятия R1 ingress contract не изменяется.
- Browser auth provider, desktop composition и альтернативные уведомления не
  входят в R2; их появление требует отдельного продукта/решения.
- Design reference не является готовой design system. CB-58 должна доказать
  light/dark contrast, semantic states, reduced motion, safe areas и responsive
  поведение.
- Release 1 ещё не имеет принятой immutable точки; `v1.0.0`, GitHub Release и
  image metadata остаются gated результатом CB-50.

Полный исправленный пакет готов к отдельному решению владельца по ADR-0014 и
последующей реализации документационной области CB-49.
