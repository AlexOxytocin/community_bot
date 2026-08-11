# CB-33 — тест-план

1. CLI на базе без active config и с одним administrator создаёт ровно одну version,
   одну activation, active pointer и десять levels.
2. Точный повтор CLI возвращает success и сохраняет те же counts/identity.
3. CLI без active administrator и при нескольких active administrators fail-closed.
4. Readiness возвращает `product_config_incomplete` при нулевом pointer, неполной
   шкале или active member со stale/null config version.
5. После coordinator backfill readiness становится `ready` при свежем heartbeat и
   отсутствии failed outbox.
6. Operational contract проверяет packaged config и точный deploy order.
7. Команды:

   ```text
   uv run pytest -ra tests/unit/test_operations.py tests/unit/test_runtime_operations.py tests/integration/test_economy.py tests/integration/test_notifications.py
   uv run ruff format --check .
   uv run ruff check .
   uv run ty check
   uv build
   uv run community-bootstrap-product-config --help
   uv run community-bot --check
   uv run community-worker --check
   ```

Полный regression выполняется один раз в CB-29 после слияния всего Bug-пакета.
