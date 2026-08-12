# Эскалационная финальная проверка CB-30 — попытка 3

Status: changes_requested

Проверка выполнена на staged tree
`603bb22529b5fd275c13d12c459b0ca7380e66c0`. Прежние M-001/M-002 закрыты, но
production `PostgresAssignmentDeadlineSource` выбирал первые 25 просроченных задач
только по deadline и статусу `published|settling`, не требуя `accepted` assignment.

Из-за этого 25 старых `settling`-задач с `submitted`, `disputed`,
`rejected_pending_dispute` или `reviewer_required` могли бесконечно занимать одну и ту
же пачку. Следующее просроченное задание с `accepted` assignment не попадало в воркер,
не получало `no_show` и возврат резерва.

Автоматическая работа была остановлена. Владелец выбрал минимальное исправление:
source должен включать в bounded-пачку только задачи с фактическим `accepted`
assignment и подтвердить продвижение очереди прямым PostgreSQL oracle.
