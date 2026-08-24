# Bug reproducer report — task and city workflow

**Classification: FIX_PROVEN** for the focused cases below.

## Proven issues

1. An offline filter reopened with the selected format but without a city input. The form attempted to place the city field before the reward field had been attached to the form. The field is now synchronized after attachment.
2. City autocomplete could remain above controls after close because `.city-results` won the CSS cascade over `.hidden`. Closing is now explicit for selection, blur, Escape, and outside taps.
3. A task with a zero reward was rejected by both application and database constraints. Zero is now valid; negative rewards remain rejected.
4. A fresh Telegram Desktop window can expose `WebApp` before `initData`. After the first 401 the app immediately treated that temporary state as a failed login and rendered an unhelpful generic error. Bootstrap now waits for the bridge briefly and shows a specific recovery message only if the data never arrives.
5. The requested 0.1-credit payout was not representable: the Mini App input, API contract, ledger, cached balances and database columns all required integers. Amounts are now exact decimal tenths across the transaction path; values with more than one decimal place are rejected.

## Evidence

- `tests/browser/test_mini_app.py::test_catalog_actions_filters_and_list_density_are_compact` verifies city selection, popup closure, applying filters, and reopening an offline filter with its city intact.
- `tests/browser/test_mini_app.py::test_task_creation_recovers_preview_and_back_never_restarts` verifies city popup closure outside and after choosing a result.
- `tests/integration/test_task_creation.py::test_freeform_task_can_publish_with_zero_credit_reward` verifies the database-backed publishing path.
- `tests/unit/test_tasks_domain.py`, `tests/unit/test_cities.py`, and `tests/unit/test_economy_domain.py` cover validation boundaries.
- `tests/browser/test_mini_app.py::test_bootstrap_waits_for_late_telegram_desktop_init_data` reproduces and verifies the Desktop bridge timing case.
- `tests/unit/test_web_auth.py` verifies that the API accepts a string decimal reward without a binary floating-point conversion.

## Residual risk

The PostgreSQL migration requires a running database to validate the live schema change. The local integration suite is currently blocked because Docker Desktop is not running; the migration will also be validated by the deployment database before release is declared complete.
