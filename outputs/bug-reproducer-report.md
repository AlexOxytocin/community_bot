# Bug reproducer report — task and city workflow

**Classification: FIX_PROVEN** for the focused cases below.

## Proven issues

1. An offline filter reopened with the selected format but without a city input. The form attempted to place the city field before the reward field had been attached to the form. The field is now synchronized after attachment.
2. City autocomplete could remain above controls after close because `.city-results` won the CSS cascade over `.hidden`. Closing is now explicit for selection, blur, Escape, and outside taps.
3. A task with a zero reward was rejected by both application and database constraints. Zero is now valid; negative rewards remain rejected.

## Evidence

- `tests/browser/test_mini_app.py::test_catalog_actions_filters_and_list_density_are_compact` verifies city selection, popup closure, applying filters, and reopening an offline filter with its city intact.
- `tests/browser/test_mini_app.py::test_task_creation_recovers_preview_and_back_never_restarts` verifies city popup closure outside and after choosing a result.
- `tests/integration/test_task_creation.py::test_freeform_task_can_publish_with_zero_credit_reward` verifies the database-backed publishing path.
- `tests/unit/test_tasks_domain.py`, `tests/unit/test_cities.py`, and `tests/unit/test_economy_domain.py` cover validation boundaries.

## Residual risk

The system uses whole-credit integer storage. Supporting a literal `0.1` reward needs a fixed-point currency migration across the ledger, API and displays; it is intentionally not emulated by a browser input step.
