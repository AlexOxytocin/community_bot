# CB-5 — финальная эскалационная проверка плана

Status: approved

Схема: `community_bot.plan_review.verdict.v1`.

## Проверенные источники

- актуальная Jira `CB-5`, повторно прочитанная напрямую через Atlassian Rovo
  API: описание, пять критериев приёмки, статус `В работе`, родитель `CB-2`,
  отсутствие комментариев и вложений, связь `CB-5 blocks CB-12`;
- явные решения владельца по Q-005/Q-006/Q-011, необратимому eligibility и
  последующему уточнению: после terminal payout не моделируются late dispute и
  refund, допустимы только экономические correction/reversal;
- полный актуальный пакет `plan-source-context.md`, `problem-escalation.md`,
  `needs-info.md`, `plan.md`, `test-plan.md`;
- сохранённые исторические попытки `reviews/plan/attempt-01.md` и
  `attempt-02.md`;
- `agents/plan-reviewer/instruction.md`,
  `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`;
- канонические `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md`,
  `01_PRODUCT_REQUIREMENTS.md`, `02_DOMAIN_RULES.md`, `03_USER_FLOWS.md`,
  `05_BOT_INTERFACE.md`, `07_SECURITY_AND_PRIVACY.md`, `10_TEST_PLAN.md`;
- фактический полный набор `MemberStatus` и принятый assignment lifecycle.

Непрочитанных источников, вложений, внешних блокеров и секретов нет. Новый ADR
не требуется: решения уточняют продуктовые права внутри уже принятой
архитектуры, ролей и серверной авторизации.

## Область задачи

План соответствует Jira и остаётся документационным. Он закрывает Q-005,
Q-006, Q-011 и синхронизирует журнал решений, PRD, доменные правила,
пользовательские сценарии, интерфейс, безопасность и тест-план. Python-код,
схема БД, миграции, Telegram runtime и реализация профилей/кармы корректно
оставлены `CB-12`.

Входящих Jira-блокеров у CB-5 нет. Исходящая связь с CB-12 согласована с
областью: утверждённая документация должна стать её продуктовым контрактом.

## Логика решения

### Q-005 — право оценивать

- Eligibility создаёт первая валидная ненулевая full/partial выплата по
  assignment участника между парой в любом направлении.
- Community-task, cancelled, rejected, unresolved dispute и `no_show` права не
  создают; самооценка запрещена, administrator не обходит eligibility для
  личного vote.
- Eligibility является необратимым историческим фактом. После terminal payout
  late dispute и refund не моделируются; последующие допустимые
  correction/reversal его не удаляют.
- Любая karma mutation независимо требует актуального `active` у автора и
  получателя, сохраняет одну current vote и append-only revisions.

Контракт больше не заставляет CB-12 угадывать, отзывается ли право при
финансовой коррекции и какое lifecycle-событие допустимо после выплаты.

### Q-006 — комментарий и raw karma

- Получатель видит только aggregate/count без текста, автора, timestamp и
  истории.
- Автор видит собственную current vote/comment.
- Любой moderator получает только participant projection и никогда не читает
  raw data, независимо от переданного клиентом permission token.
- Raw author/comment/history доступны только active administrator с
  `karma_review`; каждый просмотр создаёт audit event.
- План явно требует согласовать этим правилом D-005, безусловные пункты PRD и
  security matrix.

### Q-011 — профили

- Active member, moderator и administrator видят safe projection всех active
  profiles.
- Foreign `pending`, `paused`, `restricted`, `suspended`, `left`, `banned`
  скрыты и из каталога, и при прямом UUID/callback.
- Собственная обычная карточка доступна `active` и `paused`; `restricted` не
  получает безусловный self-read, его индивидуальные разрешения остаются в
  существующей модерационной политике вне CB-5.
- Active administrator с `member_read` читает non-active profile только через
  ограниченную admin projection без баланса, ledger, Telegram ID, raw karma,
  страйков и административного аудита.
- List, pagination, callback и get-by-id используют одну актуальную серверную
  policy; отказ не подтверждает существование скрытой записи.

Полный канонический набор статусов используется без несуществующего `blocked`.

## Проверка эскалационного пакета

Все обязательные замечания закрыты:

1. M-001: статусная матрица приведена к реальному `MemberStatus`.
2. M-002: D-005 и PRD включены в явную permission-gated синхронизацию.
3. M-003/E-001: владелец выбрал необратимость; активные source-context,
   needs-info, plan и test oracle используют только correction/reversal после
   payout. Финальное решение в `problem-escalation.md` явно уточняет, что late
   dispute/refund после terminal payout не вводятся.
4. E-002: безусловный self-read `restricted` удалён.
5. E-003: raw read moderator запрещён безусловно во всех активных контрактах и
   сценариях.
6. E-004: две неуспешные попытки сохранены, `problem-escalation.md` создан,
   решения владельца записаны, финальная коррекция проведена полным пакетом.

Исторические reviews и варианты эскалации сохраняют исходные формулировки как
аудит процесса. Они не противоречат активному контракту, потому что раздел
«Решение владельца» явно фиксирует последующее уточнение и имеет приоритет над
описанием альтернатив.

## Стратегия проверки

Сценарии 1–17 достаточны для документационной задачи и будущей реализации:

- закрытие Q проверяется без запрета их исторического упоминания;
- self-vote, отсутствие eligibility, full/partial settlement,
  correction/reversal и community exclusion имеют точные oracle;
- конкуренция first vote/update проверяет одну current vote, immutable revisions
  и корректный aggregate;
- participant, moderator и administrator projections проверяются позитивно и
  негативно, включая audit;
- полный набор статусов, direct UUID, forged callback, stale cursor и status
  race проверяются одной server-side policy с нераскрывающим отказом;
- согласованность семи документов, русский смысловой текст, локальные ссылки,
  отсутствие секретоподобных значений и `git diff --check` входят в барьер.

Отказ от полного `pytest` обоснован отсутствием runtime-изменений. После
реализации документации остаются обязательными `implementation-report.md` и
одно независимое final review всего diff.

## Обязательные исправления

Нет. Плановый пакет одобрен для реализации документационной области CB-5.

## Остаточные риски

- Необратимый eligibility сохраняется после fraud/economic reversal. Это
  осознанное решение владельца; возможность mutation отдельно ограничивается
  актуальным статусом аккаунта.
- Каталог всех active profiles увеличивает внутреннюю видимость сообщества;
  safe projection и единая list/get policy являются обязательным барьером
  реализации CB-12.
- `karma_review` и `member_read` должны получить одну серверную семантику во
  всех канонических документах и будущем коде; клиентские данные права не дают.
- `Status: approved` разрешает документационную реализацию, но не подтверждает
  её фактическое выполнение: результаты ещё должны пройти `test-plan.md`,
  implementation report и final review.
