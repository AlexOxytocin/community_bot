# CB-62 — источники плана

- Решение владельца в текущей задаче: продукт ведётся только в направлении
  Telegram Mini App; полноценный старый bot UI не нужен.
- Jira CB-62: удалить legacy presentation/operations, сохранить общее ядро,
  migration history и минимальный Telegram shell только при необходимости.
- Jira CB-51: после уточнения 17.08.2026 не требует dual-write или rollback
  bridge старого bot image.
- `docs/adr/0014-multi-interface-release-2.md`: сохраняются модульный монолит,
  FastAPI boundary, internal actor, operation receipts, SPA и PlatformBridge;
  bot fallback/parity заменяются proposed ADR-0016.
- `docs/mvp/TECH_STACK.md`: сохраняются Python 3.13, PostgreSQL 18, SQLAlchemy,
  Alembic, outbox, worker и CI; long polling и R1 deployment перестают быть
  текущей runtime topology.
- Репозиторий на `21a4b4c`: 12 Telegram transport файлов, bot entrypoint,
  R1 release workflow/ops, pilot/test-run surfaces, 284 task artifacts.
- `src/community_bot/infrastructure/outbox/telegram.py` зависит от старого
  callback и reply keyboard; adapter можно сузить до plain notifications без
  удаления outbox или Bot API dependency.

При конфликте источников более позднее прямое решение владельца и Jira CB-62
задают продуктовую область; новый ADR делает это изменение долговременным.
