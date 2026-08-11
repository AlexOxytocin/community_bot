# CB-13 — план реализации

## Цель и уровень риска

Один крупный Level 3 срез: довести существующий assignment dispute до
воспроизводимого решения и одной апелляции, добавить обратимые санкции,
interaction alerts/penalties и приватные risk signals. Полную регрессию не
запускать; после готового кода выполнить один targeted gate.

Пакет P-001–P-003 из `needs-info.md` принят владельцем 11 августа 2026 года и
фиксируется как D-023 до реализации.

## Миграция `0009`

1. Сохранить существующий immutable opening в `assignment_disputes`; добавить
   отдельный current-case snapshot с `status=open|resolved|appealed`, timestamps
   и current resolution identity. Старые строки backfill как `open`. Opening
   actor/reason/comment/assignment не изменяются; snapshot разрешает менять
   только status/current resolution/version по серверной процедуре.
2. Добавить append-only `dispute_evidence`, `dispute_resolutions` и
   `dispute_appeals`. Resolution хранит exact code, moderator, comment,
   command/update identity, снимок конфликтов и ссылки на созданные ledger,
   reliability и audit effects. Один initial resolution и не более одной appeal.
   Append-only `reliability_outcome_corrections` хранит previous/new terminal
   outcome; projection CB-12 складывает root и последнюю валидную correction.
3. Добавить `member_sanctions` и append-only `sanction_events`.
   Sanction хранит type, restricted actions, reason, start/end, author,
   previous status и current state; revoke/expire — новые events, не delete.
4. Добавить `interaction_alerts`, `interaction_alert_assignments` и
   `interaction_alert_penalties` по принятой D-016/D-017, включая один open
   episode на unordered pair и FK из penalty ledger.
5. Добавить `moderation_risk_signals` и `karma_vote_moderation` для приватных
   сигналов, исключения current vote из aggregate и восстановления.
6. Расширить `members.permissions_json` допустимым `interaction_review` через
   subset CHECK; active administrators migration получают право для пилота,
   остальные роли/status — нет.
7. Защитить resolution/evidence/appeal/sanction history от UPDATE/DELETE;
   PostgreSQL constraints запрещают вторую appeal, повторный resolution command,
   конфликтующие active status sanctions и penalty без alert outcome.

## Прикладные контракты

### Спор

- Queue показывает open disputes active moderator/administrator, result versions,
  immutable opening comment/evidence и safe parties; приватные данные не идут в
  outbox/log.
- Resolution revalidates actor role/status, conflict policy, current assignment,
  task origin/reserve и отсутствие другого resolution under lock.
- Конфликт: actor является creator/performer/community reviewer, пригласил сторону,
  ранее санкционировал сторону по связанному case или self-declared conflict.
- P-002 mapping применяется одним UoW через публичный economy batch. Для
  member-origin допустимы все коды. Для community-origin запрещены
  `creator_abuse` и `cancel_without_fault`; остальные коды используют system
  issuance/no-issuance без личного creator/refund. Неприменимый code отвергается
  до эффектов. Replay
  возвращает stored outcome; другой payload под command/update identity — отказ.
- Appeal доступна стороне один раз до `resolved_at + 7 days`; решает другой
  active administrator без конфликта. Она может выбрать любой применимый code.
  Previous economic effects сначала отменяются `resolution_reversal` со ссылкой
  на каждую исходную transaction, затем применяется новый resolution; fraud
  самого решения использует `fraud_reversal`. Если у получателя отменяемого
  credit/refund недостаточно незарезервированного баланса или опыта, команда
  возвращает `insufficient_reversible_balance` без изменения case/status/audit.
  Все эффекты применяются одной транзакцией.
- Единая matrix code × origin × previous outcome задаёт assignment status,
  ledger, effective reliability outcome, occupancy и risk signal. Reliability
  меняется append-only correction поверх immutable root. Slot, по которому когда-
  либо была полная/частичная выплата, остаётся занят навсегда даже после appeal;
  unpaid `cancel_without_fault` освобождает только member-origin slot.
- Для уже оплаченного `approved|partially_approved` assignment active
  administrator открывает отдельный fraud moderation case командой
  `OpenFraudCaseCommand`. Команда требует reason/evidence, использует тот же
  assignment-scoped case gate, exact command/update payload identity и создаёт
  immutable opening + current snapshot без изменения paid status. Повтор exact
  возвращает case, конфликт payload отклоняется. Только fraud resolution может
  применить к нему exact `fraud_reversal`; недостаточный незарезервированный
  credit/experience возвращает `insufficient_reversible_balance` без case,
  ledger, reliability, alert, audit или receipt effects. Открытие конкурирует с
  appeal/resolution под тем же gate, поэтому active case ровно один.

### Санкции

- `notice|warning` не меняют status или права; `ends_at` для них необязателен.
- `restriction` содержит непустой subset `create_task|accept_task|karma_vote` и
  обязательный будущий `ends_at`; moderator может ограничивать только
  `create_task|accept_task`, а `karma_vote` — только administrator с
  `karma_review`. Соответствующие application boundaries проверяют effective
  sanction policy.
- `suspension` временно переводит member в `suspended`; `ban` — в `banned`.
  Suspension требует будущий `ends_at`; ban бессрочен и создаётся только без
  `ends_at`. Revoke/expire восстанавливают previous status только если текущий
  status всё ещё поставлен этой sanction и нет другой active status sanction;
  `left|banned|restricted` и более новое состояние не перезаписываются.
- Все commands имеют reason, author, exact replay и audit. Единый
  `EffectiveMemberStatusResolver` используется каждым application path, где
  status влияет на authorization либо projection. Read вычисляет effective
  status из текущего member и active time-bounded sanctions, не доверяя
  физическому `suspended` после `ends_at`; mutation под member lock сначала
  idempotently пишет expiry event/восстанавливает допустимый status, затем
  выполняет status/permission gate. CB-15 только ускоряет тот же публичный expiry
  command; correctness read и mutation не зависит от scheduler.

### Interaction alerts

- Источник — уникальные assignment с нереверсированной положительной
  `task_reward_earned|partial_task_reward` по member-origin task в `(T-window,T]`.
- Settlement и любое resolution/appeal reversal recompute alert в том же UoW.
  Threshold/window
  читаются из exact active product config; `0` отключает новые episodes.
- Пока alert open, новые interactions обновляют latest count/config и links.
  После снижения count до threshold фиксируется rearm; новый episode появляется
  только при следующем crossing.
- Review принимает `legitimate|monitor|penalty_recommended`; meeting notes
  приватны. Penalty batch сначала canonical economy member locks, затем pair
  gate/revalidation, что совпадает с payout path и исключает lock inversion.

### Karma и fraud signals

- P-003 rules создают только приватные risk signals. Никаких credits/status
  effects автоматически нет.
- Active administrator с `karma_review` может exclude/restore exact vote
  revision; aggregate query исключает только active exclusion текущей revision,
  raw/history не меняются. Новая revision под тем же pair gate делает прежнее
  решение stale и снова учитывается до отдельного moderation command.
- Fraud resolution создаёт exact `fraud_reversal` для каждой выбранной исходной
  transaction максимум один раз; опыт и credits возвращаются зеркально, cache
  обновляется тем же economy UoW.

## Lock order и идемпотентность

1. Telegram mutation: update gate → exact receipt → actor identity gate.
2. Dispute: case advisory gate → assignment task gate → locked assignment/case →
   economy batch canonical members → resolution/audit/receipt → commit.
3. Sanction: target member gate/canonical member lock → lazy expiry → sanction row → status,
   audit/receipt → commit.
4. Interaction payout/review: existing task/member locks → canonical economy
   member locks → unordered pair gate → alert revalidation/effects → commit.
   Ни один alert flow не держит pair gate в ожидании member lock.
5. Stored command возвращается только при exact payload hash и actor/case identity.
   Partial commit, direct balance edit и Bot API внутри транзакции запрещены.
6. Karma vote и exclude/restore используют один unordered pair gate, затем
   current vote/revision lock. Risk-signal key равен exact rule + UTC bucket
   boundary + normalized pair либо target/comment fingerprint; raw comment в
   signal, outbox и logs не копируется.

## Telegram и приватность

- Команды/callbacks: moderation queue, dispute detail/evidence, resolution preview
  + confirm, appeal, sanction preview + confirm/revoke, interaction alert review,
  karma signal review.
- Callback содержит только compact action + UUID/revision; все права и entity
  state читаются с сервера. Приватные comments/evidence/meeting notes не входят в
  participant messages, logs или outbox payload.
- `/cancel` использует общий flow-aware dispatcher и не удаляет чужой flow.

## Документация и результат

Обновить `02_DOMAIN_RULES`, `05_BOT_INTERFACE`, `06_DATA_MODEL`,
`07_SECURITY_AND_PRIVACY`, `08_MODERATION_AND_ABUSE`, журнал решений после
подтверждения P-001–P-003 и handoff. Подготовить implementation report, один
independent final review, PR/CI/merge и провести CB-13 по Jira статусам.
