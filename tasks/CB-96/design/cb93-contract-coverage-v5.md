# CB-93 — контрактная сверка UI, концепция 05

Статус: design/planning only. Production/repo runtime не изменяется. UI не добавляет поля или доменные операции, которых нет в действующем продуктовом контракте.

## 1. Проверенные источники

- `docs/mvp/01_PRODUCT_REQUIREMENTS.md`, `02_DOMAIN_RULES.md`, `03_USER_FLOWS.md`, `04_TASK_CATALOG.md`, `06_DATA_MODEL.md`, `08_MODERATION_AND_ABUSE.md`;
- `docs/release-2/PARITY_MATRIX.md`, ADR-0017 и `tasks/CB-64/parity-map.json`;
- действующие domain/application contracts и модели PostgreSQL для tasks, assignments, registration, reputation, economy, moderation и notifications;
- обязательный follow-up Оркестратора: templates/schema, community publication/reviewer, disputes→appeals, sanctions, alerts/penalties, invitations/onboarding, roles/status, histories/corrections, versioned config и outbound notifications.

## 2. Поля задания: ни одно не потеряно

| Поле/факт движка | Создание | Preview | Каталог/detail | Assignment/review | Admin |
|---|---|---|---|---|---|
| `task_kind: solo/group` | T04, T05 | T06 | T03 | M03, M10 | G19, G20 |
| `category_id`, name, icon | T05 | T06 | T01, T03 | M03, M10 | G08/G08A/G19; metadata read-only, current engine разрешает только active toggle |
| `time_size: XS/S/M/L/XL` | T05 | T06 | T03 | M03 | G19 |
| `estimated_minutes` | выводится из size или шаблона, не отдельное freeform-поле | T06 | T03 | M03/M11 | G19/G20 |
| `credit_reward_per_performer` | T05, только разрешённая шкала | T06 | T01/T03 «за слот» | M03/M11/M12 | G19/G20 |
| `performer_slots` | solo=1, group≥2 | T06 + общий резерв | T01/T03 свободно/всего | M10 по слотам | G19/G20 |
| `reserved_credit_total` | вычисляемый preview, не редактируется | T06 | не показывается чужому участнику | M10 создателю | для community отсутствует |
| `title` | T05, до 80 | T06 | T01/T03 | M03/M10/M11 | G19/G20 |
| `description` | T05, до 1200 | отдельная секция T06 | отдельная секция T03 | M03/M10/M11 | G19/G20 |
| `completion_criteria` | отдельное обязательное поле T05, до 700 freeform | отдельная секция T06 | отдельная секция T03 | рядом с результатом M03–M05/M11–M12/S02 | G19/G20/G22B |
| `input_payload` / `input_schema` | schema-driven поля T05; freeform использует только разрешённый contract | labels+values T06 | только public/safe projection T03 | M03/M11/S02 | G09 schema editor |
| `deadline_at` | timezone-aware future datetime T05 | T06 | T01/T03 | M03/M07/M11/M14 | G19/G20 |
| `format` | только `Онлайн/Офлайн`; `ANY` допустим лишь как template constraint | T06 | T01/T03 | M03/M11 | G09/G19 |
| `city` | обязательно только для Offline | T06 | T03 | M03/M11 | G19 |
| `materials.text`, `materials.url` | T05, только http/https без credentials | T06 | T03 | M03/M11/S02 | G19/G20 |
| template identity/version | T04A | T06 | safe template label при необходимости | snapshot неизменяем | G08B/G09 |
| creator/author/origin | из session; не редактируется | T06 | T03: участник или «Сообщество» | M03/M10/M11 | G19/G20 |
| independent `reviewer_admin_id` | не применяется к обычному member task | — | у community виден безопасный reviewer label | G22A–G22C | G19/G20 |
| `minimum_level` | template/config-derived для member flow | T06 | T03 и причина disabled accept | M03 | G09/G19 |
| `performer_instructions` | template contract, не выдуманное поле freeform | T06 | T03 «Как выполнять» | M03/M11 | G09/G19 |
| task/slot statuses | не редактируются напрямую | publish outcome | open/full/closed/expired/cancelled | весь lifecycle M02/M03/M09/M10 | G10 |
| `TEST-*` scope | не выбирается участником | badge preview при active test run | badge `ТЕСТ`, visibility scoped | M02/M03/M10 | нет продуктового управления test run |
| `safety_snapshot_json`, command IDs, revisions | нет raw UI | только безопасный итог | нет raw UI | stale/exact replay states | audit-safe projection, raw payload закрыт |

Отдельного поля «Формат результата» нет. Оно удалено из всех экранов и критериев. `format` означает только Онлайн/Офлайн.

## 3. Результат и assignment: фактический контракт

| Механизм/поле | UI |
|---|---|
| Принятие слота, запрет self-accept, minimum level, task state, max active assignments | T03A с понятной причиной disabled; authoritative outcome → M03 |
| Durable submission draft, owner/revision/restart | M04; autosave/saved/stale revision/error; reload восстанавливает тот же draft |
| Template result schema | M04 строится строго по сохранённой Draft 2020-12 schema; неподдержанная schema → unavailable, не угадывается |
| Freeform result | одно поле `result`, 10–2000 символов; это содержимое результата, не его «формат» |
| Immutable result versions | M04A; новая отправка создаёт новую версию и не продлевает review deadline |
| Preview/confirm/exact submit | M05→M06→M07; success заменяет history entry и не допускает повторной отправки по Back |
| Review 72h, reminders 24/48h, auto-confirm boundary | M07/M11; countdown and outcome; worker не имеет отдельного UI |
| Full/partial/reject | M12: full, `ceil(50%)`, reject; consequence preview до confirm. Отдельного review-comment поля в текущем command contract нет, поэтому UI его не выдумывает |
| Reject dispute window 24h | M13/M14/M15; reserve/system issuance frozen |
| Dispute explanation/evidence/result history | M14/M14A/S02; append-only и permission-safe |
| One appeal in 7 days | M16; только причина апелляции. Решение — G27/G28 другим conflict-free admin |
| Performer withdrawal | M08: только accepted assignment, обязательная причина и показ reliability consequence |
| Creator cancel/close group intake | M17; свободные слоты возвращаются сразу, occupied performers получают M18 |
| Cancellation response matrix | M18/M19: accept, continue/submit, declined, obsolete, completed; карточка не возвращается в каталог |
| Deadline/no-show/settling/finalization | M03/M10 status states; отдельного worker UI нет |
| Community reviewer required/replacement | G22A–G22C; новый валидный reviewer получает новое 72h окно только в предусмотренном случае |
| Community cancellation before submit | G22D; только permitted admin, community/system reason, audit and appeal path |

## 4. Профиль, регистрация, карма и лидерборд

| Контракт | UI |
|---|---|
| Invitation: intended Telegram ID, max uses, uses count, expiry, revoke | A03, G02–G04 |
| Consent | A04 |
| Registration fields | A05: display name, city, timezone, short bio, current goal, help categories, skill tags, availability |
| Registration preview/submit/reject/reopen | A05A, A06, A06A; staff S05–S07 с review comment |
| Own editable profile | P06/P07: те же 8 полей; active и paused видят собственную карточку |
| Safe public member profile | P02: username, display name, city, bio, goal, help categories, skills, availability, experience, level, anonymous karma aggregate, reliability |
| Member catalog/search | P01: только active; поиск только по display name и username, от 3 символов; cursor pagination |
| Karma eligibility and vote | P02→P03→P04; +1/0/−1, comment 10–300, edit current vote, no self/admin bypass |
| Raw karma/history/moderation | G13/G14/G14C только active administrator + `karma_review`; каждый read audited; moderator не видит raw |
| Reliability | P02/P06; публично процент только после 5 принятых, иначе «Недостаточно данных»; история G14A append-only |
| Personal statistics | P06: completed, partial, earned XP, unique recipients, categories, no-show, reliability; лидерборд не встраивается в профиль |
| Leaderboard | P05 внутри `Участники`; experience DESC + 4 tie-breaks, own rank и cursor; баланс и карма не сортируют |
| Ledger | P08–P10 own safe projection; G14B admin projection; все 10 transaction types и reversal links |

## 5. Роли, статусы, санкции и corrections

- Member, moderator, administrator — роли; superadministrator является administrator с системным permission, не четвёртой ролью.
- Статусы: pending, active, paused, restricted, suspended, left, banned. A07 показывает только безопасный собственный status, blocked actions и срок.
- G07 содержит только разрешённые transitions: active↔paused; member↔moderator; administrator access меняет только superadministrator; self-change закрыт.
- S08–S10 покрывают notice, warning, restriction, suspension, ban, blocked actions `create_task/accept_task/karma_vote`, reason, start/end, issue/revoke/expire history.
- G11/G12 покрывают только журналируемые credit/experience adjustment и exact reversal; прямого редактирования totals нет.
- G14A и G28 покрывают reliability/outcome corrections append-only; terminal root не переписывается.
- G14C исключает/возвращает точную revision кармы и никогда автоматически не создаёт санкцию.

## 6. Versioned catalog/config и community ownership

- G08A category: code, name, description, icon, sort order, visibility, creation mode, active flag.
- G08B/G09 template version: code/version/name/description, creator and performer instructions, completion criteria, input/result schemas, reward, estimated minutes, format, minimum level, maximum performers, moderation required, active flag.
- G16/G16A/G17/G18 product config: schema version, monotonic config version, hash, levels with thresholds/names/descriptions/messages/permissions, interaction threshold/window, maximum active assignments, active pointer and activation history.
- G19/G20 community task: полный task snapshot, origin=community, author «Сообщество», no member reserve, reward `1–4`, slots and independent reviewer. Исключение выше `4` описано в продуктовых правилах, но отдельного justification field нет в текущем draft/command contract, поэтому концепция не придумывает это поле.
- G21/G22: ordinary admin submits for superadministrator approval; superadministrator may publish directly; unpublished draft never appears in T01.
- G22A–G22D: independent result review, reviewer replacement and permitted pre-submit cancellation.

## 7. Alerts, fraud, disputes and audit

- S01–S04: dispute/appeal cases and durable resolution preview, exact confirm, seven origin-valid outcome codes.
- S11/S12: paid assignment investigation and admin-only fraud case with reason/evidence reference and reversible-payout precheck.
- G23/G24/G25: private interaction episode, counted assignments, threshold/window/config version, private meeting notes, legitimate/monitor/penalty_recommended, bounded one/both-member penalty; signal alone does nothing.
- G23A: review-only risk signals; no automatic access, balance, status or sanction effect.
- G15/G15A: safe immutable administrative audit projection. Raw before/after, outbox payload and secrets are not exposed.
- G27/G28: appeal resolution exact-reverses prior effects then applies new outcome; paid slot remains occupied.

## 8. Outbound notifications: что реально есть

Отдельного Mini App inbox, unread/read state и ручного notification composer в текущем контракте нет. Событие доставляется коротким allowlisted Telegram-сообщением; если release добавляет deep link, он ведёт прямо к target и повторно проходит identity/permission/state check.

| Событие | Target |
|---|---|
| registration approved | разрешённый root после A01 |
| task published | T03 либо безопасный T01 fallback |
| cancellation requested | M18 |
| task/assignment cancelled | M03/M10/M19 |
| assignment accepted | M10 slot |
| assignment submitted/reviewed/rejected/autoconfirmed/no-show | M03/M11/M13 |
| assignment disputed / moderation resolved | M15/S02 |
| deadline/review reminders | M03/M11 |
| reviewer required | G22C/G22A |
| interaction alert opened | G24, только authorized administrator |

## 9. Capability parity: 26/26

| Capability ID | UI / disposition |
|---|---|
| AUTH | A01/A02/A07 + permission-checked deep links |
| REGISTRATION | A03–A06A, S05–S07 |
| MEMBERS | P01/P02/P06/P07, G05–G07 |
| CATALOG_CONFIG | T04A/T05/M04, G08–G09 |
| MEMBER_TASKS | T04–T08, T03, M09/M10 |
| GROUP_TASKS | T04/T05/T06, M10, M17–M19 |
| COMMUNITY_TASKS | G19–G22D, T01/T03, G22A/B |
| ASSIGNMENT_LIFECYCLE | T03A, M02–M13 |
| DEADLINES | T03/M03/M07/M11/M14 + outbound reminders; worker no UI |
| ECONOMY | P08–P10, G11/G12/G14B |
| REVERSALS | G12/G28/S12 |
| LEVELS_LEADERBOARD | P05/P06/P08, G16A |
| KARMA | P02–P04, G13/G14/G14C |
| RELIABILITY | P02/P06, G14A/G28 |
| DISPUTES | M14/M14A/M15, S01–S04 |
| APPEALS | M16, G27/G28 |
| SANCTIONS | A07, S08–S10 |
| RISK_ALERTS | G23/G23A/G24/G25 |
| CONFLICTS | S02/S03, G19/G20/G22A–G22D/G27/G28 |
| NOTIFICATIONS | Telegram outbound → target deep link; N01/N10 for absent Mini App surfaces |
| AUDIT_IDEMPOTENCY | stable loading/success/exact replay; G15 safe audit; N02/N03 raw internals |
| TASK_CREATION_DRAFT | T04B/T05–T08 |
| SUBMISSION_DRAFT | M04–M07 |
| MODERATION_DRAFT | S03/S04/G28 |
| FULL_IMPORT | нет продуктового UI; migration/ops boundary N13 |
| MINI_APP_REACHABILITY | весь screen inventory + transition map |

## 10. Итог сверки

- 26/26 parity capability IDs имеют UI или явное обоснование отсутствия Mini App UI.
- Все поля task/template/profile/invitation/config/assignment, которые должны видеть или вводить люди, привязаны к конкретным экранам.
- Технические IDs, raw payloads, leases, hashes команд, safety snapshots и worker states не превращены в пользовательские поля.
- Вымышленное поле «Формат результата» отсутствует; результат отображается только через сохранённый result schema либо фактическое freeform-поле `result`.
