# CB-62 — карта переноса проверок

Файл с transport imports нельзя удалять, пока перечисленный core invariant не
имеет зелёного transport-free теста.

| Исходный pytest node ID | Обязательное доказательство после очистки |
| --- | --- |
| `tests/integration/test_member_foundation.py::test_concurrent_duplicate_admin_update_commits_one_effect` | exactly-once/audit |
| `tests/integration/test_member_foundation.py::test_fault_between_member_save_and_audit_rolls_back_then_retries` | rollback |
| `tests/integration/test_initial_admin.py::test_concurrent_bootstrap_has_one_persisted_winner[True]` | concurrency |
| `tests/integration/test_catalog.py::test_database_immutability_and_migration_cycle` | immutability/migration |
| `tests/integration/test_registration.py::test_invitation_is_hashed_and_concurrent_last_use_is_atomic` | invitation concurrency |
| `tests/integration/test_registration.py::test_concurrent_moderation_creates_one_grant_and_active_profile` | grant exactly-once |
| `tests/integration/test_registration.py::test_fault_after_grant_flush_rolls_back_full_approval` | ledger rollback |
| `tests/integration/test_task_creation.py::test_persistent_preview_publish_replay_and_cancel` | publish replay |
| `tests/integration/test_task_creation.py::test_publish_business_retry_concurrent_cancel_and_private_listing` | race/business identity |
| `tests/integration/test_task_creation.py::test_publish_fault_injection_rolls_back_every_staged_slice` | ledger/outbox rollback |
| `tests/integration/test_assignments.py::test_full_exchange_is_atomic_and_exactly_once` | settlement ledger exactly-once |
| `tests/integration/test_assignments.py::test_concurrent_accept_serializes_last_slot_and_active_limit` | slot concurrency |
| `tests/integration/test_assignments.py::test_assignment_fault_checkpoints_roll_back_and_retry[outbox]` | outbox rollback |
| `tests/integration/test_moderation.py::test_paid_fraud_reversal_is_admin_only_atomic_and_replayable` | reversal ledger/replay |
| `tests/integration/test_moderation.py::test_resolution_fault_rolls_back_ledger_case_audit_and_receipt` | ledger/audit rollback |
| `tests/integration/test_moderation.py::test_concurrent_resolution_has_one_winner_and_no_second_receipt` | moderation concurrency |
| `tests/integration/test_output_driven_flows.py::test_multislot_cancellation_waits_for_every_performer_and_replays` | cancellation replay; перенос в `test_core_workflows.py` |
| `tests/integration/test_output_driven_flows.py::test_community_provenance_survives_exact_migration_cycle` | provenance/migration; перенос в `test_core_workflows.py` |
| `tests/e2e/test_pilot_scenarios.py::test_full_exchange` | end-to-end ledger reconciliation; перенос в `test_core_workflows.py` |
| `tests/e2e/test_pilot_scenarios.py::test_dispute_partial_resolution` | dispute ledger/audit; перенос в `test_core_workflows.py` |
| `tests/e2e/test_pilot_scenarios.py::test_karma_after_paid_interaction` | administrative audit fact; перенос в `test_core_workflows.py` |

Правило выполнения:

1. Transport-only tests и helpers удаляются из смешанного файла.
2. Прямые application/DB tests остаются в исходном файле либо переносятся в
   `tests/integration/test_core_workflows.py` с сохранённым assertion set.
3. Для каждого ряда запускается exact source node ID до удаления. Если исходный
   файл удаляется, implementation report фиксирует новый exact node ID и
   assertion parity в `test_core_workflows.py`.
4. Итоговый diff review сверяет эту таблицу с удалёнными test names. Coverage
   является дополнительным gate и не заменяет invariant map.

Отдельный `test_legacy_test_run_quarantine.py` seed-ит active и completed run,
test task/assignment и pending outbox. Обычные queries не видят test rows, а
worker адресует test notification только participant set. Это post-removal
свойство сохраняется без управляющего CLI.
