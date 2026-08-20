# CB-93 — единый полный UI-план Community Mini App

Версия: 05. Статус: owner review. Только design/planning; implementation, API/backend/domain и production runtime не меняются.

## 1. Утверждаемые решения

- Визуальное направление: спокойная тёмная основа, cyan как primary/active, violet только как route accent.
- Active member: `Каталог / Мои / Участники / Профиль`.
- Moderator: те же четыре roots + `Модерация`.
- Administrator: те же четыре roots + `Управление`; superadministrator — administrator с системным permission, а не отдельная роль.
- Context screens скрывают bottom navigation и используют `Назад` к logical parent.
- Лидерборд расположен в `Участники`, называется `Лидерборд`, сортируется по all-time experience и не встраивается в собственный профиль.
- Solo/group — один task flow; group создаёт независимые слоты.
- `Описание` и `Критерии приёмки` — отдельные поля. `Формат` — только Онлайн/Офлайн. Поля «Формат результата» нет.
- Submission UI строится по сохранённому result schema; freeform contract показывает одно поле `result`.
- В Mini App нет notification inbox/read state: короткое Telegram-сообщение ведёт к permission-checked target.
- Один screen — не больше одного primary action; destructive/financial actions имеют preview/confirm.

## 2. Полный screen inventory

Канонические IDs, роли, entry и обязательные states находятся на full screen board. Состав:

### A — запуск и onboarding

`A01 Bootstrap`, `A02 Недоступная сессия`, `A03 Приглашение`, `A04 Правила/consent`, `A05 Анкета регистрации`, `A05A Preview/submit`, `A06 Pending`, `A06A Rejected/reopen`, `A07 Ограниченный доступ`.

### T — каталог и создание

`T01 Каталог`, `T02 Фильтры`, `T03 Полная карточка`, `T03A Confirm принятия`, `T04 Solo/group`, `T04A Шаблон/без шаблона`, `T04B Черновики`, `T05 Редактор`, `T06 Preview`, `T07 Confirm публикации`, `T08 Success`.

### M — assignment/result/review/cancellation/dispute/appeal

`M01 Мои задания`, `M02 Взятые`, `M03 Назначение`, `M04 Редактор результата`, `M04A Версии результата`, `M05 Preview`, `M06 Confirm`, `M07 Submitted`, `M08 Отказ исполнителя`, `M09 Созданные`, `M10 Задание/слоты`, `M11 Review`, `M12 Решение`, `M13 Outcome`, `M14 Спор`, `M14A История материалов спора (только чтение)`, `M15 Статус`, `M16 Апелляция`, `M17 Закрытие набора/отмена автора`, `M18 Ответ исполнителя`, `M19 Статус отмены`.

### P — participants/profile/karma/economy

`P01 Участники`, `P02 Карточка участника`, `P03 Карма`, `P04 Karma outcome`, `P05 Лидерборд`, `P06 Собственный профиль`, `P07 Редактор профиля`, `P08 Баланс`, `P09 История операций`, `P10 Операция`.

### S — moderation

`S01 Очередь кейсов`, `S02 Кейс`, `S03 Preview решения`, `S04 Outcome`, `S05 Очередь регистраций`, `S06 Заявка`, `S07 Решение регистрации`, `S08 Новая санкция`, `S09 Активные санкции`, `S10 Санкция/история`, `S11 Оплаченные выполнения`, `S12 Fraud-case`.

### G — administrator/superadministrator

`G01 Hub`, `G02–G04 Invitations`, `G05–G07 Members/role/status`, `G08/G08A Categories (metadata read-only + active toggle)`, `G08B/G09 Templates/schema versions`, `G10 Все tasks/assignments`, `G11/G12 Ledger corrections/reversals`, `G13/G14/G14C Raw karma/history/moderation`, `G14A Reliability history`, `G14B Member ledger`, `G15/G15A Audit`, `G16/G16A/G17/G18 Versioned config`, `G19/G20 Community task create/preview`, `G21/G22 Publication approval`, `G22A/G22B Community review`, `G22C Reviewer replacement`, `G22D Community cancellation`, `G23/G23A/G24/G25 Risk/interaction alert/penalty`, `G26 Administrators`, `G27/G28 Appeals`.

### N — явно отсутствующий Mini App UI

`N01 Outbox/worker`, `N02 Operation receipts`, `N03 Raw payloads`, `N04 Generic chat`, `N05 Manual notification composer`, `N06 Automatic punishment`, `N07 Raw karma for moderator`, `N08 Direct totals/reliability edit`, `N09 Public browser registration`, `N10 Notification inbox/read state`, `N11 Initial admin bootstrap`, `N12 Test-run orchestration`, `N13 Health/heartbeat/reconciliation`, `N14 Direct credit transfer`, `N15 Automatic task assignment`, `N16 User template publication`, `N17 Raw safety/private payload`.

## 3. Role visibility

- Guest видит только A01–A06A.
- Pending видит A06/A06A; active получает role roots.
- Paused видит собственный P06 и безопасный A07; restricted — только действия, не заблокированные sanction scope; suspended/left/banned не получают обычные roots.
- Moderator видит S01–S08 только в своей role/action matrix; fraud, raw karma, economy/config и interaction review не раскрываются.
- Administrator получает G tiles только по permissions (`member_read`, `karma_review`, `interaction_review` и другие предусмотренные права).
- Superadministrator-only: назначение/снятие administrator и подтверждение publication обычного administrator.
- Case party/conflicted staff/reviewer получает permission-closed без раскрытия закрытых материалов.

## 4. State contract каждого data/mutation screen

Каждый data screen: `loading`, `content`, `empty`, `error`, `permission-closed`; при наличии safe cached projection — `stale-content + refresh-error`.

Каждый action: `enabled`, `disabled с причиной`, `loading без изменения геометрии`, `safe error`, `authoritative success`.

Mutation: `editor → validation → preview → confirm → loading → success | safe error`. Preview обязателен для публикации, settlement/review, sanction, penalty, correction/reversal, config activation и appeal resolution.

Draft screens T05/M04/S03 сохраняют owner, payload, revision и restart/resume. Stale/foreign confirm не создаёт эффект.

## 5. Navigation, entry/exit/back/reload/deep-link

- Primary nav заменяет root; соседние roots не накапливаются в history.
- Context screen хранит logical parent и focus return target.
- Back на editor при dirty показывает confirm; Back из dialog закрывает его; Back после success не возвращает к активной mutation форме.
- Reload сначала повторяет auth, role/status/permission/ownership/state check, затем восстанавливает exact screen/draft; иначе safe parent/unavailable.
- Deep link — только target hint. Missing/private/foreign/obsolete object использует одинаковый safe unavailable outcome.
- External exit доступен из A02/A07; Mini App не использует browser history как product navigation.
- Telegram notification не создаёт промежуточный notification screen: event → bootstrap → target/fallback.

## 6. Ключевые transitions

- Onboarding: `A01→A03→A04→A05→A05A→A06→T01`; reject: `A06↔A06A→A05`.
- Member publish: `T01→T04→T04A/T04B→T05→T06→T07→T08→M10`.
- Assignment: `T03→T03A→M03→M04→M05→M06→M07`; extra submission returns to M04 and appends M04A version.
- Review: `M10/Telegram→M11→M12→M13→M10/M03`.
- Dispute/appeal: `M13 reject→M14/M14A→M15→M16→G27→G28→M15/M03`.
- Group cancellation: `M10→M17→M18→M19→M10/M03`.
- Karma: `P01→P02→P03→P04→P02`; ineligible stays P02 without disabled bait action.
- Admin category/template/config: `G01→G08→G08A/G08B→G09`; `G01→G16→G16A/G17→G18`.
- Community task: `G01→G19→G20→publish` for superadmin; ordinary admin: `G20→G21→G22→T03`; result: `G22A→G22B→M12/M13`; invalid reviewer: `G22C`.
- Alert: `G23→G24→legitimate/monitor outcome` or `G24→G25→G24 closed`; signal alone has no effect.
- Fraud: `S11→S12→S02→S03→S04`; sanctions: `G06/S02→S08→S09/S10`.

## 7. Field and mechanism completeness

Exact field-by-field and 26/26 parity mapping is in `cb93-contract-coverage-v5.md`. It is normative for implementation handoff; screen visuals never override it.

## 8. Owner gate

До явного утверждения владельца CB-93 остаётся planning/design record. После утверждения создаётся только terminal handoff Оркестратору с exact paths, inventory, decisions и blockers/open questions; отдельную implementation Jira-задачу оформляет Оркестратор.
