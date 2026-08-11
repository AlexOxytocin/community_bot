# CB-29 — план полной пользовательской регрессии

## Цель

Один раз пройти собранный MVP целиком от приглашения и регистрации до оплаты,
спора, модерации и кармы. Сначала собрать полный список дефектов на одном
production snapshot, затем исправить весь пакет отдельными Jira Bug/ветками и
повторить ту же матрицу на опубликованном release.

## Принцип

Зелёный handler-level тест не считается E2E. Для каждого UI-перехода следующий
текст кнопки, message id или inline-кнопка берутся только из фактического
предыдущего ответа Telegram/fake Bot API. UUID и callback, полученные из БД или
собранные вручную, допустимы только в целевом integration-тесте обработчика.

## Фаза 1. Заморозить исходный снимок

1. Сохранить release commit/image digest, Alembic revision и health процессов.
2. Снять только агрегированные production-инварианты: active config, seed,
   роли/статусы, ledger totals, задачи, assignments, moderation cases, outbox.
3. Проверить последние очищенные runtime errors без Telegram payload.
4. Не менять production-данные во время диагностического прохода.

## Фаза 2. Инвентаризация достижимости

1. Сопоставить каждую кнопку главного/admin menu с реальным router/service.
2. Найти команды, для которых нет видимого UI, и UI, который ведёт в общий
   fallback «недоступно».
3. Для каждого шага зафиксировать один из исходов:
   `reachable`, `handler-only`, `missing`, `blocked-by-provisioning`, `defect`.
4. Результат хранить в `tasks/CB-29/journey-matrix.md` без персональных данных.

## Фаза 3. Полный прогон до исправлений

### Реальный Telegram

Через канонический коннектор пройти доступные owner/admin ветки, выбирая только
видимые элементы предыдущего ответа:

- `/start` и главное меню;
- собственная карточка, баланс, статистика, лидерборд, участники;
- каталог и создание задания до безопасной границы;
- администрирование, приглашения, очередь заявок, очередь модерации;
- повторные входы и `/cancel` без изменения чужих данных.

11 августа 2026 года владелец явно расширил границу: текущая серверная база является
тестовой, разрешено создавать синтетических участников всех ролей и выполнять
полные durable-write цепочки, включая задания, расчёты, споры, карму, санкции и
алерты. При этом используются только синтетические идентификаторы и application
services; реальные пользовательские переписки не читаются, секреты не сохраняются,
immutable audit/receipts не удаляются. Прямая запись в БД допустима только для
подготовки синтетической роли или продолжения discovery после уже зафиксированного
дефекта, когда эквивалентного публичного application path нет.

### Изолированный production-composed контур

На настоящей PostgreSQL и production Dispatcher пройти роли administrator,
moderator, author и performer:

1. приглашение → согласие → анкета → submit → admin approval → один grant;
2. каталог → шаблон → черновик → preview → publish → резерв;
3. список заданий → accept → result draft/version → submit;
4. full/partial применяются немедленно; только reject открывает dispute в
   `[rejected_at, rejected_at + 24h)`;
5. dispute → moderation preview → resolution → однократная appeal/reversal в
   `[resolved_at, resolved_at + 7d)`;
6. баланс/history/level/leaderboard после каждого экономического исхода;
7. member catalog/profile/privacy → karma create/change/raw history;
8. cancellation, deadline/no-show, notification retry и restart/resume;
9. community task и interaction alert там, где UI заявлен документацией.

### Автоматический gate

- полный `uv run pytest` на PostgreSQL 18 без skip/deselect;
- Ruff format/check и `ty`;
- Alembic empty + supported populated migration cycle;
- build и entrypoint checks;
- ledger/cache reconciliation и orphan/FK checks;
- production bootstrap/readiness oracle для active config и catalog seed.

Падение одного сценария не останавливает остальные независимые сценарии. Все
дефекты собираются до начала исправлений.

## Фаза 4. Jira triage полного пакета

1. Для каждого подтверждённого дефекта выполнить поиск дубликата в Jira.
2. Создать отдельный `Баг` с `cb16-regression`, ровно одной severity label и
   `Relates CB-29`; critical/high дополнительно блокирует `CB-24`.
3. Один root cause с несколькими симптомами — один Bug. Независимые root causes —
   разные Bugs.
4. В Jira хранить только обезличенные шаги, ожидаемое/фактическое поведение,
   release и агрегированный impact.
5. Полный discovery set задаётся одним JQL:
   `project = CB AND labels = cb16-regression ORDER BY key`.
6. Каждый `defect` из `journey-matrix.md` имеет ровно один Jira key либо явную
   ссылку на найденный duplicate; implementation report сверяет множество
   matrix defects с JQL result без пропусков.
7. До итогового повтора open critical/high отсутствуют. Каждый open medium/low
   имеет отдельное решение владельца `accepted` или `deferred`; по умолчанию
   дефект остаётся незакрытым, а не маскируется общей заметкой.

## Фаза 5. Исправить пакет

1. Каждый Bug исправлять в своей ветке `task/<BUG-KEY>` от актуального `main`.
2. Использовать минимальный общий root-cause fix: существующий service/router,
   bootstrap coordinator или readiness gate; не создавать параллельную систему.
3. После targeted tests и независимого final review: PR → CI → merge.
4. Не выполнять полную регрессию после каждого Bug. Полный повтор только после
   слияния всего найденного пакета.

## Фаза 6. Итоговый повтор

1. Повторить неизменённую `journey-matrix.md` на новом immutable image.
2. Пройти owner/admin positive smoke через реальный Telegram.
3. Повторить A–D и все ролевые/negative ветки в изолированном контуре.
4. Сверить production provisioning, ledger/cache, audit/outbox и отсутствие
   открытых severity-critical/high Bugs, связанных с CB-29.
5. Обновить правила проекта и короткий smoke-runbook.

## Изменения в ветке CB-29

- `tests/e2e/test_pilot_scenarios.py` и общий test driver: output-driven UI
  actions без ручных UUID/callback в E2E;
- минимальные regression/readiness тесты, которые воспроизводят найденные
  системные пробелы;
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` и `docs/AGENT_WORKFLOW.md`: реальный
  Telegram-smoke как финальный gate пользовательской задачи;
- `docs/operations/USER_GUIDE.md`/smoke-runbook при расхождении интерфейса;
- `journey-matrix.md`, `implementation-report.md`, `final-review.md`.

Production-код исправляется только в отдельных Bug-ветках, не в CB-29.

## Не входит

- новая веб-админка;
- отдельный E2E framework или новая зависимость;
- изменение несинтетических пользовательских данных и чтение чужих переписок;
- нагрузочное тестирование выше масштаба пилота;
- расширение продуктовых требований.

## Риски и меры

- **Одна реальная Telegram-роль:** остальные роли проверяются production
  Dispatcher + fake Bot на PostgreSQL; это явно маркируется.
- **Production mutation:** только синтетические test fixtures и штатные application
  services; все вынужденные прямые fixture/repair операции перечисляются в матрице.
- **Ложный E2E:** каждый переход обязан ссылаться на предыдущий Bot response.
- **Много дефектов:** сначала полный сбор, затем один последовательный пакет
  Bug-веток, без повторной широкой регрессии между ними.
