# CB-27 — план проверки

1. Немедленная доставка проходит независимо от фактического wall clock runner.
2. Три obsolete reminder получают `failed`, а не остаются `pending` из-за
   переноса в следующее окно.
3. Readiness test завершается без вторичных unclosed-resource warnings.
4. Весь notification integration file проходит без skip/deselect.
5. Ruff, ty, diff-check и GitHub PostgreSQL CI успешны.
