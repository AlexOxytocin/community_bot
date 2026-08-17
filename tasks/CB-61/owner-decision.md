# CB-61 — решение владельца после эскалации

Дата: 2026-08-16.

Контекст: post-escalation plan review обнаружил два исполняемых источника
execution budgets — глобальные профили Codex и планируемый project YAML.

Решение владельца: **«глобальные бюджеты канонические»**.

Практическое следствие:

- execution budgets хранятся в одной глобальной политике Codex;
- Community Bot ссылается на policy id и global profile ids без копирования
  model-call/time/concurrency/follow-up/polling чисел;
- репозиторий остаётся источником project-specific routing, process, packet и
  output budgets;
- global validator и project CI отвечают за разные границы контракта.

