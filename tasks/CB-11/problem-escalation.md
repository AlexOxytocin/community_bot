# CB-11 — эскалация двух непройденных plan review

Режим: `review_cycle`, фаза `plan`.

## Попытки

- `reviews/plan/attempt-01.md` — `Status: changes_requested`;
- `reviews/plan/attempt-02.md` — `Status: changes_requested`.

## Собранный результат

Первая попытка выявила пять противоречий схемы и публичных контрактов. Одно
консолидированное обновление закрыло replacement slot, повторные result versions,
durable dispute handoff и economy correlation. Вторая попытка локализовала один
остаток: backward-compatible identity/hash неизменённой product config v1.

## Одно финальное исправление

- для `config_version=1` loader принимает исходный документ без
  `assignment_policy`, а canonical hash projection полностью сохраняет прежнюю
  форму и прежний hash;
- для `config_version>=2` `assignment_policy` обязателен, входит в payload/hash и
  публичный snapshot;
- runtime read исторической активной v1 возвращает effective default `3`, не
  переписывая payload/hash;
- сценарий 21 повторно ingest-ит исходный v1 в существующую БД, затем проверяет
  v2 activation, accept-limit и rollback на v1.

После этого выполняется одна эскалационная контрольная проверка полного пакета.
Если она не approved, работа останавливается для решения владельца.

---

# Эскалация двух непройденных final review

Режим: `review_cycle`, фаза `final`.

## Попытки

- `reviews/final/attempt-01.md` — `Status: changes_requested`;
- `reviews/final/attempt-02.md` — `Status: changes_requested`.

## Общая причина

Первая реализация закрыла основной happy path, но не провела одну и ту же
aggregate identity через community settlement, lock order, свободные slots и
сохраняемый Telegram flow. Первое консолидированное исправление устранило эти
разрывы, однако оставило три соседних случая: identity нового terminal command,
следующую result version после завершённого draft и paid slot в многоместном
задании. Доказательная матрица при этом описывала больше, чем проверяла напрямую.

## Одно финальное исправление

- terminal replay допускается только для exact command identity; иной command
  отклоняется до receipt;
- после подтверждения создаётся новая durable submission identity для v2, stale
  callback не меняет состояние;
- slot занят как active, так и paid terminal assignment; replacement разрешён
  только после cancelled;
- synthetic Telegram доводит accept→preview→confirm→author full и проверяет v2,
  restart, exact/stale callback;
- недостающие boundary/concurrency/correlation/fault assertions сводятся в один
  targeted набор, `ty` запускается на всей рабочей области.

После этого допускается одна эскалационная контрольная final-проверка. Если она
не approved, работа останавливается для решения владельца. Полная регрессия
остаётся в CB-16.

## Решение владельца после контрольной проверки

10 августа 2026 года владелец явно подтвердил второй, уже реализованный вариант:
`approved` и `partially_approved` slot остаётся занятым; replacement разрешён
только после `cancelled`. Разрешено исправить противоречивую формулировку
канонической модели данных и выполнить точечную заключительную проверку без
повторного запуска зелёного кода и без расширения до регрессии CB-16.
