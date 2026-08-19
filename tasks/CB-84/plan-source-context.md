# CB-84 — исходный контекст плана

- Jira `CB-84`, parent `CB-48`: цель, критерии, ceiling и delivery gate.
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`: Jira-first, Mini App-only,
  Ponytail, level 2 artifacts и post-merge delivery.
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md`, пункт 4.8: участник может отказаться от
  задания по существующим правилам.
- `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md`, D-032: free-form создание —
  основной пользовательский путь; template не заменяет его.
- `src/community_bot/application/assignments.py:775`: фактический owner
  `AssignmentService.cancel` уже проверяет reason, owner, `accepted` status и
  выполняет slot/task/economy/outbox/receipt effects.
- `src/community_bot/transport/web.py:848` и
  `src/community_bot/transport/static/app.js:736`: active assignment list/detail
  уже есть, mutation отказа отсутствует.
- `src/community_bot/application/tasks.py:451`: template/community start
  существует, но Web free-form owner на строках 537–614 намеренно исключает
  `template_id` и `origin != member`; community дополнительно требует reviewer
  и возможный superadmin publication approval.
- `docs/adr/0017-lean-community-mini-app-core.md`: UI должен быть тонким слоем
  поверх сохранённого полного движка без новой архитектуры.
