# CB-3 — независимое ревью плана

`community_bot.plan_review.verdict.v1`

Status: approved

## status

`approved`

## reviewed_sources

- Jira `CB-3`: описание, критерии приёмки, родитель, статус, приоритет, комментарии, вложения и актуальная связь `Blocks`.
- Jira `CB-2`: область и критерии успеха родительского эпика.
- Jira `CB-6`: статус, родитель и зеркальная сторона связи с `CB-3`.
- Jira `CB-3`–`CB-16`: родитель, статус и обе стороны всех связей `Blocks`; найдено 14 дочерних задач и 18 уникальных связей.
- `tasks/CB-3/plan.md`, `tasks/CB-3/plan-source-context.md`, `tasks/CB-3/test-plan.md`.
- `AGENTS.md`, `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`, `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md`.
- `docs/adr/0004-risk-tiered-development-workflow.md`, `docs/adr/0005-mvp-technology-stack.md`.
- `agents/developer/instruction.md`, `agents/developer/procedures.md`, `agents/plan-reviewer/instruction.md`, `agents/plan-reviewer/config.yaml`, `agents/final-review/instruction.md`, `agents/final-review/procedures.md`.
- `docs/mvp/README.md`, `docs/mvp/TECH_STACK.md`, `docs/mvp/09_IMPLEMENTATION_PLAN.md`, `docs/mvp/10_TEST_PLAN.md`, `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md`, `docs/ARCHITECTURE.md`.
- Modern Python: `SKILL.md`, `references/pyproject.md`, `references/ruff-config.md`, `references/testing.md`.
- Официальные документы uv по установке, управляемому Python, проектам и GitHub Actions; release-страницы `actions/checkout` и `astral-sh/setup-uv`.

## scope_findings

1. Актуальный Jira-граф согласован с пакетом источников: `CB-3` содержит одну исходящую связь `outwardIssue: CB-6`, то есть `CB-3 blocks CB-6`; входящих блокирующих связей у `CB-3` нет. На стороне `CB-6` та же связь представлена как `inwardIssue: CB-3`, то есть `CB-6 is blocked by CB-3`.
2. Дополнительная проверка `CB-3`–`CB-16` подтвердила 14 задач под родителем `CB-2`, 18 уникальных связей `Blocks` и статус `К выполнению` у каждой задачи. Незакрытых входящих зависимостей для начала `CB-3` нет.
3. Область плана соответствует этапу 0 и критериям Jira: каркас, точки запуска, PostgreSQL/Alembic, инструменты качества, CI и документация. Регистрация, экономика, каталог и другие продуктовые этапы явно исключены.
4. План не разрешает продуктовые `TBD` и не добавляет скрытых функций этапов 1–10.

## design_findings

1. Структура согласуется с принятым ADR-0005: один Python-пакет, процессы `bot` и `worker`, слои `transport`, `application`, `domain`, `infrastructure`, `bootstrap`, PostgreSQL как единственное транзакционное хранилище и без отдельного брокера.
2. План конкретен по Python 3.13, `src` layout, `uv_build`, `requires-python = ">=3.13,<3.14"`, `.python-version`, `uv.lock`, созданию зависимостей через `uv add` и PEP 735 dependency groups. Он не требует ручного редактирования списков зависимостей.
3. Границы импортов определены проверяемо: `domain` не зависит от aiogram, SQLAlchemy и внешних слоёв; `application` не зависит от transport, infrastructure, bootstrap и worker. AST-тест предусматривает положительные и отрицательные случаи.
4. Console scripts `community-bot` и `community-worker` с безопасным `--check` дают воспроизводимый smoke-запуск без Bot API token, БД и внешних отправок. Обычный режим до runtime-реализации завершается явной английской ошибкой и не создаёт ложного впечатления работающего сервиса.
5. Async Alembic environment, пустая начальная migration, PostgreSQL 18 в `compose.yaml`, health check, цикл `upgrade/downgrade/upgrade` и `SELECT 1` закрывают инфраструктурный контур без продуктовой схемы.
6. Ruff `ALL`, ограниченные исключения, английские docstrings, ty для Python 3.13, strict pytest и branch coverage не ниже 80% соответствуют Modern Python и правилам проекта.
7. Полные SHA `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` и `astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9` совпадают с актуальными официальными примерами uv для `v7.0.1` и `v9.0.0`.
8. Новый ADR не нужен: задача реализует уже принятое ADR-0005 и не предлагает нового структурного или сквозного решения.

## verification_findings

1. Матрица приёмки сопоставляет каждый критерий Jira с реализацией и проверкой: locked sync, Python 3.13.x, smoke entry points, Alembic/PostgreSQL, Ruff, ty, pytest, import boundaries и README.
2. План проверяет воспроизводимость повторным `uv sync --locked --all-groups` в чистом окружении и неизменностью `uv.lock`.
3. Проверки точек запуска доказывают код завершения 0 в `--check`, отсутствие токена и внешней отправки, а также безопасный отказ обычного режима.
4. Отсутствие локального Docker отражено честно. Локальное прохождение PostgreSQL не заявляется; Docker Compose, Alembic и database smoke остаются обязательным GitHub Actions-барьером на точном публикуемом commit до merge.
5. CI разделён на quality и PostgreSQL/Alembic jobs, запускается для pull request и push в `main`; план запрещает merge до зелёных обязательных jobs.
6. Предусмотрены проверки языка, секретов, отсутствия реальных Telegram-операций, покрытия, warnings, неизвестных markers, полной доступной регрессии и `git diff --check`.
7. `implementation-report.md` и независимый `final-review.md` должны представить фактическое доказательство каждого критерия; план не выдаёт будущие CI-результаты за уже выполненные.

## required_actions

- Обязательных исправлений плана до начала реализации нет.

## residual_risks

- Локальный Docker недоступен. Это не блокирует реализацию каркаса, но окончательное доказательство PostgreSQL 18, Alembic и database smoke должно быть получено зелёным CI на точном публикуемом commit; без него финальное `approved` и merge запрещены.
- SHA GitHub Actions зафиксированы, но фактическую версию установленного бинарника uv следует сохранить в `implementation-report.md`; при настройке workflow предпочтительно закрепить её через параметр `version` для воспроизводимой диагностики.
- Database integration smoke должен запускаться в PostgreSQL job явно и успешно; тихий skip обязательной проверки нельзя считать доказательством.
