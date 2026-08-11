# CB-29 — контекст источников

## Jira

- `CB-29` — крупная регрессионная задача под эпиком `CB-2`.
- Связана с `CB-24` (пилот) и закрытым дефектом `CB-28`.
- Критерии требуют непрерывных пользовательских цепочек, реального Telegram-smoke
  владельца/администратора и отдельных Jira Bug для каждого подтверждённого
  production-дефекта.

## Канонические документы

- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` — Jira/Git-процесс, отдельные Bugs после
  регрессии, специальные проверки Telegram.
- `docs/AGENT_WORKFLOW.md` — отдельная общая регрессия после готовности MVP.
- `docs/JIRA_WORKFLOW.md` — размер задач и жизненный цикл.
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md` — возможности участника и администратора.
- `docs/mvp/02_DOMAIN_RULES.md` — экономика, уровни, карма, надёжность, споры.
- `docs/mvp/03_USER_FLOWS.md` — пользовательские цепочки от регистрации до спора.
- `docs/mvp/05_BOT_INTERFACE.md` — видимые меню, команды и карточки.
- `docs/mvp/08_MODERATION_AND_ABUSE.md` — исходы споров, санкции и апелляции.
- `docs/mvp/10_TEST_PLAN.md` — общая матрица MVP.
- `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md` — D-011–D-025.
- `docs/mvp/TECH_STACK.md` и ADR-0005/ADR-0009 — PostgreSQL, production Dispatcher,
  self-hosted runtime и release gate.

## Фактический production snapshot перед регрессией

- release commit: `829f170ad0a1316b597e037d8d4d006f448774c0`;
- immutable image: `sha256:25919f762838ccd8b18a67f3bea78738cb1740bff8056d9d4663d80ab20a66dc`;
- `bot`, `worker`, PostgreSQL: healthy;
- аккаунты: один active administrator, один active member, два pending member;
- `starting_grant`: одна операция `+5 credits`, `+0 experience`;
- `active_product_config=0`, `product_config_versions=0`, `levels=0`;
- заданий, назначений и дел модерации пока нет.

## Уже воспроизведённые наблюдения, ещё не исправления

1. Реальный Telegram: `Участники` отвечает «Участники сейчас недоступны».
2. Реальный Telegram: `Моя карточка` и `Баланс` для bootstrap administrator отвечают
   «недоступно»; у bootstrap administrator нет заполненной participant-проекции.
3. Реальный Telegram: `Найти задание` и `Создать задание` приводят к
   `ProductConfigError: No active product configuration exists`.
4. Лидерборд доступен, но placeholder-имя bootstrap administrator отображается
   повреждённым текстом.
5. Production deploy не имеет команды первого bootstrap/activation продуктовой
   конфигурации и не проверяет наличие активной версии readiness-gate.

Эти наблюдения фиксируют исходный снимок. Окончательная группировка по Jira Bug
выполняется только после полного прохода матрицы.

## Пробел старого доказательства

`tests/e2e/test_pilot_scenarios.py` проходит production Dispatcher, но часть
переходов выполняет скрытыми командами, UUID из БД и вручную собранными callback:

- `registration:consent`, `registration:submit`, `registration:approve:<uuid>`;
- `/task_create <template_uuid>` и `task:accept:<task_uuid>`;
- `/assignment_submit <uuid>`, `/assignment_dispute <uuid>`;
- `assign:review:<uuid>:...`, `/karma <member_uuid>`.

Это доказывает прикладные обработчики, но не достижимость действий человеком.

## Безопасная граница

- Канонический пользовательский коннектор:
  `C:\Users\User\.codex\tools\telegram.ps1`.
- Реальные чужие заявки, оценки, задания и решения не изменяются автоматически.
- Реальный Telegram используется для read-only и собственных тестовых действий.
- Ролевые и разрушающие ветки выполняются в изолированной PostgreSQL через тот же
  production Dispatcher и fake Bot API.
- В Jira и артефакты не попадают Telegram ID, токены, callback payload, тексты
  приватных анкет и session data.
