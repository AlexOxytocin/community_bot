# CB-71 — escalation проверки плана

## Причина

Достигнут предел двух failed plan review. Первый verdict исправил исходную
точность orchestration boundary; второй появился после final-review finding,
который потребовал согласовать legacy ADR-0019 consumers со strict standing
delivery rule.

## Консолидированное решение

- удалить внутреннее противоречие по exact mapping;
- везде использовать predicate `product task OR any runtime diff`;
- разрешать skip только process/docs-only задаче без runtime diff;
- запрещать Jira `Done` без green public smoke и без waiver;
- описывать amended slice без устаревшего счётчика файлов.

## Следующий и последний gate

Одна независимая post-escalation проверка полного amended plan. Она завершилась
`Status: changes_requested`: positive predicate не везде записан как
`product_task OR any_runtime_diff`. Работа остановлена для owner decision;
дальнейшие циклы без явного разрешения не допускаются.

## Требуемое решение владельца

Разрешить либо отклонить один дополнительный консолидированный цикл:

1. заменить product-only/finite runtime taxonomy на единый `any_runtime_diff`
   во всех active/canonical/machine-readable consumers;
2. обновить exact architecture test;
3. повторить plan и final review ровно по одному разу.

## Решение владельца

Разрешён ровно один дополнительный консолидированный fix и одна независимая
проверка. Positive predicate заменён на единый
`product_task OR any_runtime_diff` во всех active/canonical/config/workflow
boundaries и exact test. Любой non-approved verdict теперь terminal; следующий
fix/review cycle запрещён.
