# Архитектурные решения (ADR)

ADR фиксируют значимые структурные и сквозные решения Community Bot.

## Правила

- Использовать шаблон `_template.md`.
- Нумеровать последовательно: `0001`, `0002`, …
- Не удалять и не перенумеровывать принятые ADR.
- Новый ADR создаётся со статусом `Предложено` во время планирования структурного или сквозного решения.
- `plan-reviewer` проверяет обоснование и последствия ADR, но не принимает решение за владельца.
- После успешной проверки владелец явно принимает решение до начала реализации; только после этого статус меняется на `Принято`.
- Заменённый ADR помечать `Статус: заменено ADR-XXXX`.
- Рутинные детали реализации ADR не требуют.

## Индекс

- [ADR-0001 — Русский язык смысловой документации](0001-russian-documentation-language.md)
- [ADR-0002 — Jira как инженерный коммуникационный слой](0002-jira-engineering-coordination.md)
- [ADR-0003 — Роли агентов вокруг ограниченных способностей](0003-capability-shaped-agents.md)
- [ADR-0004 — Пропорциональный процесс разработки и работа с Git](0004-risk-tiered-development-workflow.md)
- [ADR-0005 — Технологический стек MVP](0005-mvp-technology-stack.md)
- [ADR-0006 — Транзакционная граница обработки Telegram updates](0006-telegram-update-transaction-boundary.md)
- [ADR-0007 — Соразмерный цикл задач, ревью и регрессии MVP](0007-review-escalation-after-two-failures.md)
- [ADR-0008 — Runtime и эксплуатационный профиль пилота](0008-pilot-runtime-and-operations.md)
- [ADR-0009 — Самостоятельное размещение пилота](0009-self-hosted-pilot-runtime.md)
- [ADR-0010 — Быстрый путь малых багфиксов](0010-small-bugfix-fast-lane.md)
- [ADR-0011 — Защищенный release после одного полного CI](0011-protected-single-ci-release.md)
- [ADR-0012 — Python-скрипты эксплуатации и деплой из GitHub ref](0012-python-ops-and-git-deploy.md)
- [ADR-0013 — Изолированные live test runs в рабочем экземпляре](0013-isolated-live-test-runs.md)
- [ADR-0014 — Multi-interface архитектура Release 2](0014-multi-interface-release-2.md)
- [ADR-0015 — Бюджетная многопоточная оркестрация агентов](0015-cost-aware-multi-agent-orchestration.md)
