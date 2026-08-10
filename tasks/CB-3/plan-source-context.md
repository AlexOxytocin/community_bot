# CB-3 — пакет источников плана

## Jira

- `CB-3` — «Создать каркас модульного монолита и базовый CI».
- Тип: `Задание`; приоритет: `Medium`; статус на 2026-08-10: `К выполнению`.
- Родитель: эпик `CB-2` — «Реализовать и подготовить к пилоту Community Bot MVP».
- Входящих блокирующих связей нет. `CB-3` блокирует `CB-6`.
- Комментарии, вложения и исполнитель отсутствуют.
- Доступные переходы: `К выполнению`, `В работе`, `На проверке`, `Готово`. Отдельного статуса планирования нет, поэтому во время подготовки плана задача остаётся в `К выполнению`.

## Канонические правила проекта

- `AGENTS.md`.
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`.
- `docs/AGENT_WORKFLOW.md`.
- `docs/JIRA_WORKFLOW.md`.
- `docs/adr/0004-risk-tiered-development-workflow.md`.
- `agents/developer/instruction.md` и `agents/developer/procedures.md`.
- `agents/plan-reviewer/instruction.md`.
- `agents/final-review/instruction.md` и `agents/final-review/procedures.md`.

## Продуктовые и архитектурные источники

- `docs/mvp/README.md`.
- `docs/mvp/TECH_STACK.md`.
- `docs/mvp/09_IMPLEMENTATION_PLAN.md`, этап 0.
- `docs/mvp/10_TEST_PLAN.md`.
- `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md`, решение `D-010`.
- `docs/adr/0005-mvp-technology-stack.md`.
- `docs/ARCHITECTURE.md`.

## Инструкции Modern Python

- `C:/Users/User/.codex/skills/modern-python/SKILL.md`.
- `references/pyproject.md`.
- `references/ruff-config.md`.
- `references/testing.md`.

Применимые правила: зависимости добавляются через `uv add`, dev/test-инструменты хранятся в PEP 735 dependency groups, используется `uv_build`, Ruff, ty и pytest; код, docstrings, комментарии, логи и сообщения разработчика пишутся на английском.

## Актуальные официальные источники

- uv installation: `https://docs.astral.sh/uv/getting-started/installation/`.
- uv managed Python: `https://docs.astral.sh/uv/guides/install-python/`.
- uv projects and dependencies: `https://docs.astral.sh/uv/guides/projects/`.
- uv GitHub Actions: `https://docs.astral.sh/uv/guides/integration/github/`.
- на 2026-08-10 последний release `actions/checkout` — `v7.0.1`, commit `3d3c42e5aac5ba805825da76410c181273ba90b1`;
- на 2026-08-10 последний release `astral-sh/setup-uv` — `v9.0.0`, commit `c771a70e6277c0a99b617c7a806ffedaca235ff9`.

## Состояние репозитория и окружения

- `main` синхронизирован с `origin/main` на `c13f2d8`;
- рабочее дерево до планирования чистое;
- `src/` и `tests/` содержат только `.gitkeep`;
- `pyproject.toml`, `uv.lock`, `.python-version`, Alembic, Docker Compose и `.github/workflows/` отсутствуют;
- системный Python: `3.14.3`, что не соответствует принятому Python 3.13;
- `uv` отсутствует в `PATH`;
- Docker и Docker Compose отсутствуют в локальном окружении.

## Следствия для проверки

- uv устанавливается официальным способом, после чего управляемый Python 3.13 загружается через uv; системный Python 3.14 не используется для проектного lock-файла и проверок;
- отсутствие локального Docker не меняет требуемый `compose.yaml`, но PostgreSQL migration и integration checks должны обязательно пройти на GitHub-hosted runner до merge;
- реальные Telegram-токены и отправки для scaffold не нужны и запрещены;
- задача не закрывает продуктовые `TBD` и не добавляет функции этапов 1–10.
