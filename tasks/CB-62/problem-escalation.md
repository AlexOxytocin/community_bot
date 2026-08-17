# CB-62 — escalation после двух plan review

**Дата:** 17.08.2026.

## Что произошло

Первый review нашёл реальные риски: test-run data quarantine, потерю core
transaction tests, неизменность migrations и смешение deploy с backup/restore.
Они закрыты одним консолидированным исправлением.

Повторный review подтвердил эти исправления, но оставил `changes_requested` по
двум связанным требованиям доказуемости destructive manifest:

1. одинаковые basenames и смысловые категории tests/docs/config не дают
   однозначного exact path decision для каждого tracked файла;
2. карта переноса core tests не перечисляет точные pytest node IDs, поэтому
   нельзя машинно доказать, что каждый критический invariant пережил удаление.

## Варианты владельца

### A — один post-escalation remediation

Добавить минимальный deterministic contract:

- default rule: любой tracked path, не указанный exact path/glob в manifest,
  остаётся `keep`;
- exact path lists для `delete` и `replace`, без basename-only записей;
- exact pytest node IDs для ledger/audit/rollback/concurrency/exactly-once
  scenarios и целевой файл после переноса;
- одна финальная независимая проверка полного пакета.

Это рекомендуемый вариант: он не добавляет runtime framework и нужен только
как страховка перед массовым удалением.

### B — сузить CB-62

Удалить только полностью изолированные bot/ops paths, а mixed tests/docs и
часть старых artifacts оставить до CB-51–CB-56. Риск ниже, но цель владельца
«убрать всё старое сейчас» закрывается не полностью.

### C — остановить CB-62

Не выполнять destructive cleanup и оставить текущее дерево без изменений.

## Текущее состояние

- runtime и исторические migrations не изменены;
- staged только proposed ADR и planning package;
- оба review attempts сохранены;
- реализация, commit, push и Telegram/production действия не выполнялись.
