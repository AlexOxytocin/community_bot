# CB-99 — план уровня 2

## Причина повышения уровня

Первоначально задача была принята как малый UI-баг уровня `1B`. Независимое
ревью показало, что рабочие периоды меняют канонический контракт лидерборда
между UI, API, application service и PostgreSQL projection. Поэтому перед PR
задача переведена на уровень 2; миграция, новая архитектура и ADR не нужны.

## Область

1. Переиспользовать существующий ledger и leaderboard owner, добавив только
   `week|month|all` и rolling cutoffs 7/30 суток для основного XP-показателя.
2. Сделать P01/P05 компактными, сохранить отдельные views, history и member
   detail, исключить гонки ответов периодов.
3. Удалить leaderboard из P06, сохранить authoritative profile projection и
   вывести согласованные агрегаты completed/created, karma и reliability.
4. Убрать дублирующие видимые headings; сохранить доступные имена, native search
   submit, pencil action и mobile touch targets.
5. Не менять schema, ledger semantics, tie-breakers, privacy, роли, mutation
   contracts, framework и зависимости.

## Проверка

- integration: rolling periods, stable order/cursor, member search и P06
  active-or-paused owner contract;
- browser: 375×812 и 430×932, exact density 4/5, periods/query/data, cached-period
  race, profile mapping/null, pencil/back и отсутствие старого DOM;
- Ruff format/lint, `ty`, non-browser pytest, browser pytest, secret/diff check;
- независимый final review, затем PR/CI/merge и post-merge delivery по ADR-0019.

## Риски

- Период ограничивает только XP; существующие tie-breakers остаются all-time и
  это явно фиксируется в доменных правилах.
- Длинные публичные строки ограничиваются ellipsis без раскрытия новых полей.
