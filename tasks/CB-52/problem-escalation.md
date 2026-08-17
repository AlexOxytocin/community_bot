# CB-52 — process escalation после двух plan review

Schema: `community_bot.problem_escalation.v1`

Status: resolved_plan_approved

## Триггер

Две последовательные независимые попытки plan review завершились
`changes_requested`. По workflow дальнейшая итерация допускается только после
сохранения обеих попыток, явного разбора причины и одной консолидированной
коррекции перед терминальным review.

## Причина

Первый draft оставлял слишком много wire/security деталей неявными. После их
исправления план всё ещё придумал более строгую cursor-семантику, чем
существующий task owner, и пропустил уже действующий нижний предел member
search. Обе ошибки были не runtime-дефектами, а расхождением плана с
фактическими contracts baseline.

## Решение

- Сохранить task catalog UUID cursor без codec/version registry: malformed UUID
  получает transport `422`, а валидный missing/hidden/stale UUID начинает с
  первой видимой страницы по текущему owner contract.
- Сохранить member search normalization: blank — без фильтра; normalized
  непустое значение — `3..80`; `1..2` — stable `422`.
- Не добавлять `db/tasks.py` в ownership и не расширять production ceiling.
- Не добавлять domain mutation, operation framework или новый ADR.

## Следующий gate

Один новый независимый critical reviewer выполняет терминальную проверку
полного пакета. Runtime implementation запрещена до `Status: approved` и
явного решения владельца.

## Терминальный review и ответ

Терминальный reviewer завершил разрешённый run с `Status: changes_requested`:
потребовал включить фактический own-profile DB owner и четыре существующих test
call-site файла, полностью описать member normalization, зафиксировать
CSPRNG/base64url/SHA-256 token contract и concurrent logout oracle. Все четыре
пункта внесены одной консолидированной правкой в `plan.md` без расширения route,
table или dependency scope.

По retry policy новый reviewer не запускается. Следующее решение принимает
владелец: принять исправленный план либо вернуть конкретную коррекцию; runtime
остаётся запрещён до этого решения.

## Решение владельца

Владелец подтвердил дословно:
«Принимаю исправленный план CB-52, разрешаю финальный recheck и после approved —
runtime implementation».

Это разрешает ровно один дополнительный независимый final recheck полного
исправленного плана. Runtime остаётся запрещён до точного
`Status: approved`; любой другой verdict является terminal blocker.

## Owner-authorized final recheck

Единственный разрешённый final recheck завершён
`Status: changes_requested`. Три прежних correction и Pareto scope reviewer
подтвердил закрытыми. Остался один exact contract blocker: план считает
`query="@"` blank/unfiltered, но baseline
`normalize_member_search_query("@")` (как и `"@   "`) после удаления leading
`@` получает пустое normalized значение и выбрасывает `ValueError`. Фактический
owner contract должен быть `422 invalid_member_query`.

По owner gate runtime implementation не начинается. Следующая коррекция и
любой дополнительный review требуют нового решения владельца.

## Решение владельца по `@`

Владелец подтвердил:
«Принимаю @ → 422, разрешаю исправить план CB-52 и провести ещё один recheck;
после approved — runtime».

План исправлен по фактическому owner contract: только omitted, empty и
whitespace-only raw query дают unfiltered list; непустой input, который после
удаления leading `@` нормализовался в пустую строку, получает
`422 invalid_member_query`. Разрешён ровно один следующий независимый recheck;
runtime по-прежнему запрещён до `Status: approved`.

## Итог recheck

Последний owner-authorized независимый recheck завершён `Status: approved`.
Обязательных исправлений нет; runtime implementation разрешена в утверждённом
Pareto scope.
