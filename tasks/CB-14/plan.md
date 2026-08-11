# CB-14 — план реализации

## Цель и уровень риска

Один крупный Level 3 документальный срез: закрыть Q-001 и входящие в актуальную
Jira вопросы hosting, error reporting/log retention и PostgreSQL recovery,
чтобы CB-15 получила один проверяемый профиль пилота.
Структурное решение оформлено ADR-0008 и принято владельцем 11 августа 2026
года с явным исключением Cloudflare R2, application object storage и webhook.

## Предлагаемое решение

### Пилотная когорта

- Ниша: закрытое межпрофессиональное сообщество практической взаимопомощи для
  взрослых участников, которые обмениваются проверяемыми небольшими заданиями,
  навыками и обратной связью.
- Первая когорта: 20–30 лично приглашённых участников с разными практическими и
  профессиональными навыками; автоматической публичной регистрации нет.
- Доступ: одноразовое приглашение, заявка, принятие правил и ручное одобрение
  администратора. Пилот длится 4–6 недель и оценивается по уже принятым метрикам
  и stop conditions.

### Runtime и данные

- Один Render Pro workspace, один project и один регион. `bot` и `worker`
  являются двумя image-backed background workers; платный managed Render
  PostgreSQL использует PostgreSQL 18 в том же регионе.
- GitHub Actions один раз собирает `linux/amd64` image из reviewed commit,
  публикует его в GHCR и фиксирует SHA-256 digest. Worker pre-deploy command,
  `bot` и `worker` используют один и тот же `ghcr.io/...@sha256:...`; mutable
  tag или независимая пересборка сервисами запрещены.
- Сервисы используют private database URL, environment secrets и одинаковую
  конфигурацию. Auto-deploy выключен. Новый digest сначала назначается
  image-backed `worker`; его единственный Render pre-deploy command из нового
  image берёт PostgreSQL advisory lock и выполняет `alembic upgrade head`.
  `bot` не имеет migration command. Alembic version table делает retry на уже
  достигнутом head безэффектным.
- Каждая release-миграция является expand-only и совместима с предыдущим
  digest: новые nullable/defaulted columns/tables/indexes допустимы, rename/drop
  и обязательное немедленное чтение только нового поля запрещены. CI после
  upgrade запускает smoke предыдущего digest и targeted smoke нового digest на
  одной схеме. Contract cleanup возможен лишь будущим release после rollback
  window.
- После успешного pre-deploy сначала переключается `worker`, затем `bot`. При
  migration или worker deploy failure оба старых процесса продолжают работу на
  совместимой расширенной схеме. При bot deploy failure выполняется retry; если
  он неуспешен, `worker` откатывается на предыдущий GHCR digest без downgrade
  схемы. Предыдущий digest хранится минимум 30 дней и до успешного следующего
  release.
- Процессный liveness контролирует Render. Прикладная готовность доказывается
  DB-readiness и heartbeat `bot`/`worker`; CB-15 задаёт degraded/failed границы
  и безопасное отображение без публичного административного API.

### Наблюдаемость и хранение

- Структурированные JSON-логи остаются в Render Pro 14 дней. В production
  `DEBUG` выключен; payload Telegram, токены, invite-коды, приватные комментарии,
  evidence и meeting notes не логируются.
- Sentry принимает только необработанные исключения и безопасные технические
  tags (`service`, release, environment, error code, correlation UUID). User
  content, Telegram update payload, DSN и database URL не попадают в event.
  Error events хранятся максимум 30 дней; более длительная история — агрегатные
  метрики и доменный audit в PostgreSQL.
- CB-15 добавляет локально тестируемый scrubber и негативные проверки утечек.

### Backup и восстановление

- Цели пилота: `RPO <= 24h`, `RTO <= 4h` в рабочее время владельца.
- Единственный backup-механизм CB-14 — непрерывный PITR платного Render
  PostgreSQL Pro с семидневным recovery window. External daily dump и отдельное
  backup object storage не используются.
- Перед пилотом и затем не реже одного раза в четыре недели владелец выполняет
  restore drill из PITR в новую изолированную Render PostgreSQL. Восстановление
  за пределами доступного PITR window не обещается.
- Успех восстановления: миграция до head, reconciliation ledger/cache, counts
  ключевых таблиц, отсутствие orphan FK и smoke `bot --check`/`worker --check`.
  Переключение выполняется только после проверки; исходная БД не перезаписывается.

### Исключённые решения

Application object storage и webhook не выбираются и не отклоняются в CB-14.
Они остаются отдельными открытыми техническими вопросами и не входят в контракт
CB-15 без новой Jira-задачи и решения владельца.

## Изменяемые документы

1. Зафиксировать принятый ADR-0008 и решение владельца.
2. Добавить D-024 в `11_DECISIONS_AND_OPEN_QUESTIONS.md`, закрыть Q-001 и убрать
   только закрытые технические вопросы; object storage/webhook оставить открытыми.
3. Синхронизировать `01_PRODUCT_REQUIREMENTS`, `TECH_STACK`,
   `07_SECURITY_AND_PRIVACY`, `09_IMPLEMENTATION_PLAN`, `10_TEST_PLAN`,
   `HANDOFF` и `PROJECT_CONTEXT`.
4. Подготовить `implementation-report.md`, выполнить один targeted document
   gate и одно независимое final review. Полный pytest не запускать: поведение
   приложения не меняется, регрессия остаётся CB-16.

## Вне области

- deployment manifest, image publication, Sentry SDK, outbox
  delivery, heartbeat tables и runbook;
  это реализация CB-15;
- покупка тарифа, создание облачных ресурсов и production secrets;
- webhook, object storage, external backup storage, публичная admin panel и
  общая регрессия.

## Матрица приёмки

| Критерий Jira | Результат | Проверка |
|---|---|---|
| Ниша, размер и доступ утверждены | D-024 и PRD содержат один точный профиль | Сценарии 1–2 |
| Runtime `bot`/`worker`/PostgreSQL описан | Render Pro, GHCR digest, PostgreSQL 18, worker pre-deploy gate и partial rollback | Сценарии 3–4 |
| Error reporting, retention и privacy согласованы | Sentry 30 дней, Render logs 14 дней, закрытый payload contract | Сценарии 5–6 |
| RPO/RTO и backup измеримы | Render PITR, recovery window 7 дней, 24h/4h и restore drill | Сценарии 7–8 |
| Документы и ADR согласованы | Закрытые решения согласованы, исключённые вопросы остались открытыми | Сценарии 9–12 |

## Риски и меры

- Провайдер изменит тариф/retention: числовые продуктовые цели отделены от
  текущего плана; несоответствие перед provisioning блокирует запуск пилота.
- Restore существует только на бумаге: CB-15 обязана провести реальный drill до
  production readiness.
- Sentry соберёт лишние данные: deny-by-default event processor и негативные
  тесты являются обязательным gate CB-15.
- Слишком широкая ниша даст шумные метрики: вход остаётся ручным, а первая
  когорта намеренно небольшая; решение пересматривается после 4–6 недель.

## Условие начала реализации

Владелец явно принял обновлённую область. Контрольный `plan-review.md` должен
подтвердить, что исключения синхронизированы с Jira и не оставили ложных
обещаний реализации.
