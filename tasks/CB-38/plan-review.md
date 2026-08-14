# CB-38 - история проверки плана

## Проверка 1

**Статус:** changes_requested

Обязательные замечания: полная branch protection, доказательство равенства synthetic
merge и actual merge tree, release-aware readiness, строгий forced-command контракт,
защита от устаревшего deploy, синхронизация standing intent, статус ADR `Предложено` и
конкретная двухпользовательская Telegram-приемка.

## Проверка 2

**Статус:** changes_requested

После устранения первого набора остались четыре пробела: `GITHUB_RUN_ID` не является
монотонным; digest не отличает повторный запуск; не были зафиксированы SSH user и pinned
host verification; provenance не задавал однозначное сопоставление PR/base/head/run и
GitHub Actions App для required checks.

## Консолидированное исправление

- Порядок deploy определяется парой `GITHUB_RUN_NUMBER`/`GITHUB_RUN_ATTEMPT` одного
  неизменяемого release workflow.
- Readiness требует release и heartbeat не старше времени начала deployment.
- Deploy выполняется как `root` отдельным forced-command key с pinned `known_hosts` и
  `StrictHostKeyChecking=yes`.
- Provenance содержит PR/base/head/merge/tree/workflow/run identity и принимается только
  при единственном полном совпадении; required checks привязаны к GitHub Actions App.

Следующая независимая проверка является проверкой после problem escalation. При новом
`changes_requested` реализация останавливается для решения владельца.

## Проверка после эскалации

**Статус:** approved

Все прежние замечания закрыты; новых обязательных замечаний нет. Владелец принял
направление явной командой `делай`, ADR переведен в статус `Принято`.
