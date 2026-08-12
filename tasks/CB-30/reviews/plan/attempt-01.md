# CB-30 — архив plan-review attempt 01

Status: changes_requested

## Обязательные замечания

1. Community task не сохраняла канонические `created_by_admin_id` и
   `reviewer_admin_id`, не обеспечивала independent reviewer,
   `reviewer_required` и безопасную replacement-команду.
2. Несколько предметных draft stores конкурировали за свободный текст без
   единственного durable owner в `conversation_states`.
3. Post-payment fraud и административные raw-karma read/exclude/restore
   оставались скрытыми командами без output-driven UI, privacy и permission E2E.

## Результат исправления

Все три пункта закрыты одним обновлением plan/test/source-context: добавлены
канонический community reviewer contract, единый text-flow owner и полные
fraud/raw-karma цепочки.
