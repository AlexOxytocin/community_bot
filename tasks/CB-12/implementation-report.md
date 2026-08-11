# CB-12 — отчёт о реализации

## Статус

Реализация завершена и готова к независимой финальной проверке. Полная регрессия
MVP не запускалась и остаётся отдельной задачей CB-16.

## Реализовано

- добавлена миграция `0008` с текущими оценками кармы, неизменяемой историей,
  runtime-разрешениями, revision диалогов и ограничениями цепочек надёжности;
- реализован возобновляемый и идемпотентный диалог кармы с постоянным допуском
  только после исходной положительной выплаты member-origin assignment;
- административный raw-view возвращает текущую оценку и полную неизменяемую
  историю revisions; permission policy, audit и exact replay применяются вместе;
- реализованы safe-профиль, keyset-каталог active-участников, личная статистика,
  агрегатная карма и аудит административного чтения raw-кармы;
- реализованы расчёт надёжности по terminal root и responsibility chain, а также
  ledger-authoritative лидерборд с полным детерминированным cursor;
- уровень в профиле и каталоге разрешается по активной версии product config, а
  не по потенциально устаревшему cache;
- добавлены Telegram-команды `/profile`, `/members`, `/stats`, `/leaderboard`,
  `/karma`, `/karma_comment`, `/cancel` и безопасные callback-обработчики;
- `/cancel` использует update gate/receipt/audit, а чужой conversation flow
  передаётся следующему flow-owner через transport dispatcher;
- синхронизированы доменные правила, интерфейс бота и модель данных.

## Критерии Jira

Все восемь критериев закрыты:

1. self и пары без оплаченного member-взаимодействия не могут создать оценку;
2. на пару хранится одна текущая оценка и append-only история её версий;
3. переход `+1 → -1` изменяет агрегат на `-2`, дальнейшие версии пересчитываются
   от фактического прежнего значения;
4. участник и moderator получают только анонимный aggregate без автора и текста;
5. raw-карма доступна только по точной permission/status policy, каждый просмотр
   имеет audit и идемпотентный receipt;
6. надёжность учитывает полный/частичный результат, no-show и действующую цепочку
   ответственности, а rate публикуется только при достаточной выборке;
7. основной лидерборд строится по опыту из ledger и утверждённым tie-breakers;
8. недоступные, inactive и forged profile targets дают единый безопасный отказ.

## Матрица целевого test-plan

Сценарии 1–25 пройдены. В PostgreSQL подтверждены migration/backfill/trigger
барьеры, постоянный eligibility, последовательные и конкурентные версии кармы,
fault rollback без persistent effects, replay, permission/status cross-product,
непустая raw history, safe keyset-каталог с одинаковыми именами и stale status,
полная terminal reliability matrix, граница sample `4/5`, member/community
статистика, все leaderboard tie-breakers, полный cursor и direct SQL guards.
Synthetic aiogram выполняет все профильные и karma routes, включая stale/forged
callbacks и передачу чужого `/cancel` следующему router-у.

## Воспроизводимые проверки

- PostgreSQL 18: контейнер healthy;
- Alembic: `upgrade head → downgrade 0007 → upgrade head` — успешно;
- `uv run pytest -q tests/unit tests/integration` — `281 passed`, без
  skip/deselect, coverage `80.82%` при пороге `80%`;
- `uv run ruff format --check src tests migrations` — успешно;
- `uv run ruff check src tests migrations` — успешно;
- `uv run ty check src` — успешно;
- `uv build` — sdist и wheel собраны;
- `uv run community-bot --check` и `uv run community-worker --check` — успешно;
- `git diff --check` — успешно.

## Границы

Санкции, dispute/fraud-инструменты и управление разрешениями остаются CB-13;
фоновые уведомления — CB-15; полная регрессия готового MVP — CB-16. Дефекты,
найденные до этого финального среза, исправлены внутри CB-12 и отдельными bug
issues не оформлялись.
