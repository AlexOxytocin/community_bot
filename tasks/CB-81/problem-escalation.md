# CB-81 — эскалация после двух plan reviews

## Причина

Два последовательных plan review получили `Status: changes_requested`, поэтому
достигнут предел `failed_reviews_before_escalation: 2`.

## Попытка 1

Staged profile conversation reuse был небезопасен: отсутствовал revision/replay
contract и существовал риск потери чужого active text flow. Owner заменил его
на one-shot actor-native command, который не обращается к conversation state.

## Попытка 2

Технический contract одобрен по существу. Осталась одна процессная неточность:
план перечислял два обязательных test files и один условный при фактическом
минимуме четыре existing test files, включая Telegram compatibility и literal
closed route set.

## Консолидированное исправление

План теперь явно содержит 5 existing production files и 4 existing test files.
Owner trigger `>5 production/test files` применяется отдельно к каждой категории;
обе остаются внутри ceiling. Объединение разных уровней tests ради искусственного
file count отклонено как ухудшение source locality. Новых implementation/test
files, dependencies, schema или domain mechanisms нет.

## Последний допустимый review

По policy разрешён ровно один `post_escalation_reviews: 1`. Он проверяет только
полный исправленный пакет. Новый `changes_requested` или `blocked` останавливает
CB-81 для owner decision; `approved` открывает runtime implementation.
