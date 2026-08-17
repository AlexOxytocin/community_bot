# CB-52 — сохранённая попытка plan review 02

Schema: `community_bot.plan_review.attempt.v1`

Status: changes_requested

## Контекст

Тот же независимый reviewer повторно сверил исправленный план с application и
database owners. Замечания первой попытки подтверждены закрытыми; runtime,
Jira и remote state не изменялись.

## Оставшиеся обязательные замечания

1. План ошибочно требовал `422` для валидного UUID отсутствующей/скрытой task,
   тогда как существующий owner начинает с первой видимой страницы. Это
   вынуждало бы лишнее изменение `infrastructure/db/tasks.py` и нарушало
   ownership/simplicity gate.
2. План не фиксировал сохранённую нормализацию member search: blank означает
   отсутствие фильтра, непустой normalized query имеет длину `3..80`, а
   `1..2` получает stable `422`.

## Результат попытки

Замечания объединены в одну correction: принять фактические contracts owners,
не добавлять новый слой и покрыть boundary cases в уже запланированном
integration test.
