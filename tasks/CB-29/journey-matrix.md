# CB-29 — полный discovery-прогон пользовательских цепочек

Дата снимка: 11 августа 2026 года.

## Граница и способ проверки

Владелец явно определил текущую серверную базу как тестовую и разрешил создавать
синтетических участников, задания, расчёты, споры, оценки, санкции и алерты. Для
поведения использовались production application services и production-composed
Dispatcher. Прямые DB fixtures применялись только для синтетических moderator/
second-admin ролей, community task без публичного transport и продолжения прогона
после обнаруженного stale registration state. Immutable audit/receipts не удалялись.

Для output-driven сценария каждый следующий input извлекался из предыдущего Bot API
response. Вручную собранный UUID/callback не считается доказательством UI.

## Общие доказательства

- immutable production image `25919f762838`, bot/worker/PostgreSQL healthy;
- production schema `0010`;
- полный локальный PostgreSQL gate: `381 passed`, `0 skipped`, `0 deselected`,
  coverage `80.40%`;
- Ruff format/check, `ty`, build и оба entrypoint check прошли;
- созданы два синтетических participant, moderator и second administrator;
- после всех production-сценариев ledger/cache: credits `66=66`, experience `9=9`;
- orphan counts для assignments/tasks, transactions/members, results/assignments и
  moderation cases/assignments равны нулю;
- duplicate receipt IDs и duplicate ledger idempotency keys отсутствуют;
- 33 outbox events materialized, незавершённых outbox events нет; 15 уведомлений
  доставлены, 57 synthetic-recipient доставок ожидаемо завершились
  `telegram_recipient_unavailable`, pending/processing нет.

## Матрица 1–51

| № | Сценарий | Результат первого полного прогона | Доказательство / разрыв |
|---:|---|---|---|
| 1 | Image/schema/process health | passed | Image immutable; schema `0010`; три контейнера healthy. |
| 2 | Active config и 10 уровней | defect `CB-33` | До ручного application bootstrap: 0 config/levels при green readiness. После bootstrap: ровно одна active config и 10 уровней. |
| 3 | Catalog seed | passed | 8 active categories и 8 active templates. |
| 4 | Level config у active users | defect `CB-33` | До bootstrap active members не имели разрешимой версии; после bootstrap missing count равен нулю. |
| 5 | Ledger/cache и FK-инварианты | passed | `66=66` credits, `9=9` experience, четыре orphan-query равны нулю. |
| 6 | Создание приглашения из меню | passed | Synthetic admin прошёл `/start` → фактическую admin button → фактический invite callback; token извлечён из ответа. |
| 7 | Consent и анкета из prompt | passed | Два synthetic participants прошли consent и семь prompt без знания внутренних IDs. |
| 8 | City → timezone / ambiguity | passed | Production registration приняла однозначные города; ambiguity/alias regression входит в 381-pass suite. |
| 9 | Restart/resume/stale answer | passed | PostgreSQL restart/stale/replay scenarios прошли в полном gate. |
| 10 | Preview → submit → admin queue | passed | Submit callback и registration queue entry извлечены из предыдущих ответов. |
| 11 | Approve из карточки, один grant | passed | Approval callback извлечён из queue card; exact replay дал одну activation и один grant на участника. |
| 12 | Reject → edit → resubmit → approve | passed | Полный PostgreSQL state-machine scenario прошёл; effects/replay проверены. |
| 13 | Все кнопки main menu отвечают | defect `CB-33` | До config card/balance/members были unavailable, find/create молчали; после bootstrap все дали content/empty state. |
| 14 | Own profile и edit | defect `CB-31` | Synthetic participant card/edit доступны; bootstrap administrator остаётся с неполным повреждённым profile. |
| 15 | Members catalog visibility | passed | После config видимый catalog вернул active profiles и исключил non-active. |
| 16 | Member profile callback/pagination/direct access | defect `CB-30` | Members view не даёт достижимой profile action; slash path требует UUID. |
| 17 | Balance/history/stats/leaderboard без UUID | defect `CB-31` | Функции отвечают после config, но повреждённый bootstrap display name попадает в views. |
| 18 | Active-admin gate/menu | passed | Реальные admin menu, requests и moderation buttons извлечены из ответа и отработали. |
| 19 | Browse/filter/pagination/stale cursor | passed | После config production browse дал empty state; eligibility/cursor matrix прошла в полном gate. |
| 20 | Create выбирает template из Bot response | passed | Author выбрал фактический template callback из ответа. |
| 21 | Draft/restart/preview без reserve | passed | Bot явно предложил `/task_preview`; preview выполнен, reserve до publish не возник. |
| 22 | Publish/replay/one reserve | passed | Publish callback извлечён из preview; task создан, reserve коррелирован; replay покрыт PostgreSQL gate. |
| 23 | Insufficient balance/invalid payload rollback | passed | Negative PostgreSQL scenarios прошли без остаточных effects. |
| 24 | Cancel unaccepted task/refund | defect `CB-30` | Business path прошёл, но UI требует `/task_cancel <UUID>`. |
| 25 | Accept из карточки и policy checks | passed | Performer принял задачу фактическим callback; last-slot race дала 1 success, 1 `AssignmentError`, 1 assignment и 1 receipt. |
| 26 | My assignments/cancel unpaid slot | defect `CB-30` | Main-menu `Мои задания` показывает authored tasks; performer path скрыт за `/my_assignments` и UUID. |
| 27 | Result draft/version/preview/submit/restart | defect `CB-30` | После accept нет инструкции/button. При ручном `/assignment_submit <UUID из ответа>` остальные draft/revision/confirm шаги стали output-driven. |
| 28 | Full settlement exactly once | defect `CB-30` | Production ledger/status/replay прошли, но author review callback transport не рендерится. |
| 29 | Partial conservation/replay matrix | defect `CB-30` | Production partial payment дал 1 credit/1 XP и refund остатка; UI review недостижим. Формула 2/3/4/5/11 покрыта suite. |
| 30 | Reject-only dispute window/finalizer | defect `CB-30` | Production reject→dispute и no-dispute finalizer работают; начало требует скрытой команды/UUID. |
| 31 | Deadline/no-show vs submit race | passed | Production no-show/refund и exact finalizer replay пройдены; concurrency matrix прошла в suite. |
| 32 | Dispute action → admin queue | defect `CB-30` | Case создаётся и виден service/queue, но assignment не показывает достижимую dispute action. |
| 33 | Moderator preview/confirm/party conflict | defect `CB-30` | Business path работает; queue не рендерит действия и требует UUID/revision/code. |
| 34 | Resolution outcome matrix | defect `CB-30` | Production full resolution и suite всех outcomes зелёные; moderator UI отсутствует. |
| 35 | Appeal/reversal/rollback/paid slot | defect `CB-30` | Production appeal другим admin выполнен: exact reversal, новый outcome, paid-slot retention; UI требует скрытые команды. |
| 36 | Sanction/revoke/expiry | defect `CB-30` | Production restriction блокирует только accept, revoke восстанавливает, suspension expires с историей; UI требует IDs/type/actions. |
| 37 | Private moderation text absent from notifications/logs | passed | Privacy/observability suite зелёный; Jira evidence содержит только безопасные aggregates. |
| 38 | Permanent karma eligibility after paid interaction | passed | После resolution reversal обе стороны сохранили eligibility. |
| 39 | Profile → karma value/comment/confirm | defects `CB-30`, `CB-32` | Видимой karma action нет; после registration approval stale `registration:submitted` дополнительно блокировал новый flow. |
| 40 | Karma change/current/history | defect `CB-30` | После одноразовой fixture-repair service дал +1 → replay → -1: одна current row, revision 2, две immutable history rows; UI start отсутствует. |
| 41 | Anonymous aggregate/count | passed | Aggregate после -1 равен -1 при count 1; identity не раскрыта. |
| 42 | Admin raw/history с audit | defect `CB-30` | Production raw view вернул current+2 history и ровно один audit с replay; Telegram admin action отсутствует. |
| 43 | Community task/reviewer/system reward | defect `CB-30` | Production community assignment approved, exact replay, единственный `community_task_reward`, ledger/cache совпали; публичного create/review UI нет. |
| 44 | Reviewer conflict/replacement | defect `CB-30` | Domain/PostgreSQL matrix зелёная; управляющий UI отсутствует. |
| 45 | Четвёртое взаимодействие создаёт alert | defect `CB-30` | На interaction count 4 при threshold 3 создан ровно один non-blocking alert; admin UI его не показывает. |
| 46 | Alert outcome/manual penalty/idempotency | defect `CB-30` | Alert закрыт `penalty_recommended`, применён ровно один penalty `-1`, replay не дублирует; UI action отсутствует. |
| 47 | Notification retry/dedup/timezone/deadline | passed | Все 33 outbox materialized; real recipients имеют sent, synthetic unavailable классифицированы terminal; retry/dedup/window suite зелёный. |
| 48 | Story A: registration → task → full pay → leaderboard | defects `CB-30`, `CB-32`, `CB-33` | Все business effects доказаны на одной базе, но UI обрывается перед submission/review, а registration оставляет stale flow. |
| 49 | Story B: publish → cancel → refund | defect `CB-30` | Publish output-driven; cancel требует скрытый UUID. |
| 50 | Story C: reject → dispute → partial resolution | defect `CB-30` | Status/ledger/audit/reversal пройдены через services; непрерывного Telegram UI нет. |
| 51 | Story D: paid interaction → karma +1 → -1 → views | defects `CB-30`, `CB-32` | Economy/eligibility/current/history/raw audit доказаны; stale registration state и отсутствие karma UI ломают живую цепочку. |

## Консолидированные root causes и Jira

### CB-33 — production readiness не активирует обязательную product config

Release запускает migrations, bot и worker, но не выполняет идемпотентный config
bootstrap/activation и не проверяет config/levels в readiness. Временная активация
через существующий coordinator восстановила core UI, что подтверждает root cause.

### CB-31 — bootstrap administrator не проходит полный профильный lifecycle

Первый administrator может остаться active с неполным или повреждённым profile, а
штатного repair/onboarding пути нет.

### CB-32 — registration approval не завершает общий conversation state

Approval активирует member и начисляет grant, но оставляет
`registration:submitted`; следующий FSM flow отклоняется как уже занятый. Для
продолжения discovery удалены только две synthetic stale rows после фиксации дефекта.

### CB-30 — domain реализован без непрерывного Telegram UI

После базовой навигации задания, результаты, review, disputes, moderation, karma,
community и alerts требуют внутренних UUID/revision/JSON. Существующие E2E читают
эти значения из БД/services и поэтому не доказывают пользовательскую достижимость.

Duplicate search по четырём компонентам не нашёл существующих Bugs. CB-30–CB-33
созданы как отдельные Bugs, связаны `Relates` с CB-29; High Bugs CB-30/CB-32/CB-33
блокируют CB-24. Каждый имеет label `cb16-regression` и ровно один severity label.

## Следующий шаг

Исправить CB-33, CB-31, CB-32 и CB-30 в отдельных ветках от актуального `main`.
Между ними выполнять только targeted tests и CI соответствующего Bug. После merge
всего пакета повторить эту же матрицу один раз целиком на новом immutable image.
