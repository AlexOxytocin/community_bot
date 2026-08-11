# CB-14 — план целевой проверки

## Предусловия

- Проверяется один staged snapshot ветки `task/CB-14` относительно `main`.
- ADR-0008 принят владельцем с исключениями, отражёнными в Jira.
- Проверка документальная; full pytest и общая регрессия не запускаются.

## Сценарии

| № | Сценарий | Ожидаемый результат |
|---:|---|---|
| 1 | Найти Q-001 и описание аудитории во всех MVP-документах | Нет TBD; везде одна ниша и 20–30 взрослых приглашённых участников |
| 2 | Сверить onboarding/access/4–6 weeks с PRD и bot flow | Invite, rules, manual approval и длительность не противоречат реализации |
| 3 | Сверить runtime ADR, TECH_STACK и implementation plan | Render Pro: `bot`, `worker`, PostgreSQL 18 в одном project/region |
| 4 | Проверить release/secret/database boundary | Новый worker digest выполняет единственный pre-deploy; previous/new smoke на expanded schema; outcomes migration/worker/bot failure; rollback без downgrade; GHCR previous digest 30 дней |
| 5 | Проверить retention numbers | Runtime logs 14 дней, Sentry error events максимум 30 дней |
| 6 | Искать запрещённые поля в logging/error-reporting contract | Telegram payload, secrets, invite, evidence и private comments запрещены |
| 7 | Проверить backup параметры | Managed Render PITR, recovery window 7 дней, RPO 24h, RTO 4h и restore drill каждые 4 недели |
| 8 | Пройти restore oracle по runbook contract | Новая изолированная БД, head migration, invariants, smoke, controlled switch |
| 9 | Проверить scope exclusions | R2/daily external backup отсутствуют; object storage/webhook не решены и остаются открытыми вне CB-14 |
| 10 | Проверить статус и ссылки ADR | `Принято`, дата/причина/alternatives/consequences и рабочие ссылки |
| 11 | Проверить русский язык и отсутствие секретов | Смысловой текст русский; нет credentials, DSN, token или приватных данных |
| 12 | Выполнить link scan и `git diff --check` | Все локальные Markdown links существуют, diff-check exit 0 |

## Ограничения

Фактическое provisioning, доставка уведомлений, Sentry event и PITR restore
выполняются в CB-15. CB-14 не включает external backup, object storage или
webhook и не заявляет, что облачная среда уже создана.
