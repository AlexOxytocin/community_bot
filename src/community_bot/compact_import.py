"""Fail-closed provenance classification for the compact database import."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from community_bot.infrastructure.db.models import Base

if TYPE_CHECKING:
    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncConnection

Provenance = Literal["public", "synthetic", "ambiguous"]
RowKey = tuple[object, ...]
Rows = Mapping[str, Sequence[Mapping[str, object]]]

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
)
_ENTITY_TABLES = {
    "account_transaction": "account_transactions",
    "assignment": "assignments",
    "interaction_alert": "interaction_alerts",
    "invitation": "invitations",
    "member": "members",
    "moderation_case": "moderation_cases",
    "product_config_version": "product_config_versions",
    "task": "tasks",
    "task_cancellation_request": "task_cancellation_requests",
    "task_cancellation_response": "task_cancellation_responses",
    "task_category": "task_categories",
    "task_draft": "task_creation_drafts",
    "task_template": "task_templates",
    "test_run": "test_runs",
}
_OPAQUE_MEMBER_COLUMNS = {
    "conversation_states": ("member_id",),
    "interaction_alerts": ("first_member_id", "second_member_id"),
    "karma_votes": ("rater_id", "target_id"),
    "member_sanctions": ("target_member_id", "author_member_id"),
    "moderation_risk_signals": ("target_member_id",),
    "notifications": ("member_id",),
    "processed_telegram_updates": ("actor_member_id",),
}
_RANK: dict[Provenance, int] = {"public": 0, "ambiguous": 1, "synthetic": 2}


@dataclass(frozen=True)
class ProvenanceInventory:
    """Classification of every source primary key."""

    states: dict[str, dict[RowKey, Provenance]]

    def counts(self) -> dict[str, dict[Provenance, int]]:
        """Return stable per-table public/synthetic/ambiguous counts."""
        return {
            table: {
                state: sum(value == state for value in rows.values())
                for state in ("public", "synthetic", "ambiguous")
            }
            for table, rows in sorted(self.states.items())
        }

    def require_unambiguous(self) -> None:
        """Stop the import if any row lacks defensible provenance."""
        ambiguous = {
            table: count["ambiguous"]
            for table, count in self.counts().items()
            if count["ambiguous"]
        }
        if ambiguous:
            message = f"Ambiguous source rows block import: {ambiguous}"
            raise ValueError(message)


async def inventory_database(database_url: str) -> dict[str, object]:
    """Read and classify one source database that is read-only by role default."""
    engine = create_async_engine(database_url, pool_pre_ping=False)
    try:
        async with engine.connect() as connection, connection.begin():
            default_read_only = await connection.scalar(text("SHOW default_transaction_read_only"))
            transaction_read_only = await connection.scalar(text("SHOW transaction_read_only"))
            if default_read_only != "on" or transaction_read_only != "on":
                message = "Source database role must default every transaction to read-only."
                raise ValueError(message)
            database = await connection.scalar(text("SELECT current_database()"))
            revisions = tuple(
                await connection.scalars(text("SELECT version_num FROM alembic_version"))
            )
            if len(revisions) != 1:
                message = "Source database must contain exactly one Alembic head."
                raise ValueError(message)
            before = await _read_all_rows(connection)
            before_signatures = logical_signatures(before)
            provenance = classify_rows(before)
            after = await _read_all_rows(connection)
            after_signatures = logical_signatures(after)
    finally:
        await engine.dispose()
    if before_signatures != after_signatures:
        message = "Source database changed during read-only inventory."
        raise ValueError(message)
    return {
        "schema": "community_bot.compact_inventory.v1",
        "source": {
            "database": database,
            "alembic_head": revisions[0],
            "tables": before_signatures,
        },
        "provenance": provenance.counts(),
        "quarantine": logical_signatures(before, provenance=provenance, state="synthetic"),
    }


async def _read_all_rows(connection: AsyncConnection) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    for table_name, table in sorted(Base.metadata.tables.items()):
        rows = await connection.execute(select(table))
        result[table_name] = [dict(row) for row in rows.mappings()]
    return result


def logical_signatures(
    rows: Rows,
    *,
    provenance: ProvenanceInventory | None = None,
    state: Provenance | None = None,
) -> dict[str, dict[str, object]]:
    """Return order-independent counts and logical SHA-256 checksums."""
    signatures: dict[str, dict[str, object]] = {}
    for table_name, table_rows in sorted(rows.items()):
        table = Base.metadata.tables[table_name]
        selected = [
            row
            for row in table_rows
            if provenance is None
            or state is None
            or provenance.states[table_name][_row_key(table, row)] == state
        ]
        encoded = sorted(
            json.dumps(row, default=str, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for row in selected
        )
        digest = hashlib.sha256("\n".join(encoded).encode()).hexdigest()
        signatures[table_name] = {"count": len(selected), "sha256": digest}
    return signatures


def classify_rows(source: Rows) -> ProvenanceInventory:
    """Classify a small community snapshot by explicit roots and stored links."""
    tables = Base.metadata.tables
    unknown = set(source) - set(tables)
    if unknown:
        message = f"Unknown legacy tables: {sorted(unknown)}"
        raise ValueError(message)
    rows = {name: list(source.get(name, ())) for name in tables}
    states: dict[str, dict[RowKey, Provenance]] = {
        name: {_row_key(table, row): "public" for row in rows[name]}
        for name, table in tables.items()
    }
    _seed_synthetic(rows, states, tables)
    while _propagate(rows, states, tables):
        pass
    return ProvenanceInventory(states)


def _row_key(table: Table, row: Mapping[str, object]) -> RowKey:
    return tuple(row[column.name] for column in table.primary_key.columns)


def _set_state(
    states: dict[str, dict[RowKey, Provenance]],
    table: str,
    key: RowKey,
    state: Provenance,
) -> bool:
    current = states[table][key]
    if _RANK[state] <= _RANK[current]:
        return False
    states[table][key] = state
    return True


def _seed_synthetic(
    rows: dict[str, list[Mapping[str, object]]],
    states: dict[str, dict[RowKey, Provenance]],
    tables: Mapping[str, Table],
) -> None:
    for table_name in ("test_runs", "test_run_participants"):
        for row in rows[table_name]:
            _set_state(states, table_name, _row_key(tables[table_name], row), "synthetic")
    for table_name in ("task_creation_drafts", "tasks"):
        for row in rows[table_name]:
            if row.get("test_run_id") is not None:
                _set_state(states, table_name, _row_key(tables[table_name], row), "synthetic")


def _column_states(
    rows: dict[str, list[Mapping[str, object]]],
    states: dict[str, dict[RowKey, Provenance]],
    tables: Mapping[str, Table],
) -> dict[tuple[str, str], dict[object, Provenance]]:
    result: dict[tuple[str, str], dict[object, Provenance]] = {}
    targets = {
        (foreign_key.column.table.name, foreign_key.column.name)
        for table in tables.values()
        for column in table.columns
        for foreign_key in column.foreign_keys
    }
    for table_name, table in tables.items():
        for column in table.columns:
            if (table_name, column.name) not in targets:
                continue
            values: dict[object, Provenance] = {}
            for row in rows[table_name]:
                value = row.get(column.name)
                if value is None:
                    continue
                state = states[table_name][_row_key(table, row)]
                previous = values.get(value, "public")
                if _RANK[state] > _RANK[previous]:
                    values[value] = state
                else:
                    values.setdefault(value, previous)
            result[(table_name, column.name)] = values
    return result


def _propagate(
    rows: dict[str, list[Mapping[str, object]]],
    states: dict[str, dict[RowKey, Provenance]],
    tables: Mapping[str, Table],
) -> bool:
    changed = False
    columns = _column_states(rows, states, tables)
    for table_name, table in tables.items():
        for row in rows[table_name]:
            key = _row_key(table, row)
            for column in table.columns:
                for foreign_key in column.foreign_keys:
                    state = columns[(foreign_key.column.table.name, foreign_key.column.name)].get(
                        row.get(column.name), "public"
                    )
                    changed |= _set_state(states, table_name, key, state)
    changed |= _propagate_alert_parent(rows, states, tables)
    changed |= _classify_polymorphic(rows, states, tables)
    changed |= _classify_payloads(rows, states, tables)
    changed |= _classify_opaque_members(rows, states, tables)
    return changed


def _propagate_alert_parent(
    rows: dict[str, list[Mapping[str, object]]],
    states: dict[str, dict[RowKey, Provenance]],
    tables: Mapping[str, Table],
) -> bool:
    changed = False
    association = tables["interaction_alert_assignments"]
    alerts = tables["interaction_alerts"]
    for row in rows["interaction_alert_assignments"]:
        state = states[association.name][_row_key(association, row)]
        if state == "public":
            continue
        for alert in rows["interaction_alerts"]:
            if alert["id"] == row["alert_id"]:
                changed |= _set_state(states, alerts.name, _row_key(alerts, alert), state)
    return changed


def _classify_polymorphic(
    rows: dict[str, list[Mapping[str, object]]],
    states: dict[str, dict[RowKey, Provenance]],
    tables: Mapping[str, Table],
) -> bool:
    changed = False
    for table_name, type_column, id_column in (
        ("outbox_events", "aggregate_type", "aggregate_id"),
        ("audit_events", "entity_type", "entity_id"),
    ):
        table = tables[table_name]
        for row in rows[table_name]:
            target = _ENTITY_TABLES.get(str(row[type_column]))
            state: Provenance = "ambiguous"
            if target is not None:
                state = _state_for_identifier(rows, states, tables[target], row[id_column])
            changed |= _set_state(states, table_name, _row_key(table, row), state)
    return changed


def _state_for_identifier(
    rows: dict[str, list[Mapping[str, object]]],
    states: dict[str, dict[RowKey, Provenance]],
    table: Table,
    identifier: object,
) -> Provenance:
    matches = [
        states[table.name][_row_key(table, row)]
        for row in rows[table.name]
        if any(str(row[column.name]) == str(identifier) for column in table.primary_key.columns)
    ]
    if not matches:
        return "ambiguous"
    return max(matches, key=_RANK.__getitem__)


def _leaf_identifiers(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {item for nested in value.values() for item in _leaf_identifiers(nested)}
    if isinstance(value, (list, tuple, set)):
        return {item for nested in value for item in _leaf_identifiers(nested)}
    text = str(value)
    return {text, *_UUID_RE.findall(text)}


def _all_identifier_states(
    rows: dict[str, list[Mapping[str, object]]],
    states: dict[str, dict[RowKey, Provenance]],
    tables: Mapping[str, Table],
) -> dict[str, Provenance]:
    result: dict[str, Provenance] = {}
    for table_name, table in tables.items():
        for row in rows[table_name]:
            state = states[table_name][_row_key(table, row)]
            for column in table.primary_key.columns:
                identifier = str(row[column.name])
                previous = result.get(identifier, "public")
                result[identifier] = max((previous, state), key=_RANK.__getitem__)
    return result


def _classify_payloads(
    rows: dict[str, list[Mapping[str, object]]],
    states: dict[str, dict[RowKey, Provenance]],
    tables: Mapping[str, Table],
) -> bool:
    changed = False
    identifiers = _all_identifier_states(rows, states, tables)
    for table_name, columns in (
        ("notifications", ("payload_json", "deduplication_key")),
        ("moderation_risk_signals", ("entity_key", "details_json")),
    ):
        table = tables[table_name]
        for row in rows[table_name]:
            references = {item for column in columns for item in _leaf_identifiers(row.get(column))}
            matched = [identifiers[item] for item in references if item in identifiers]
            if matched:
                changed |= _set_state(
                    states,
                    table_name,
                    _row_key(table, row),
                    max(matched, key=_RANK.__getitem__),
                )
    return changed


def _classify_opaque_members(
    rows: dict[str, list[Mapping[str, object]]],
    states: dict[str, dict[RowKey, Provenance]],
    tables: Mapping[str, Table],
) -> bool:
    participant_ids = {row["member_id"] for row in rows["test_run_participants"]}
    changed = False
    for table_name, columns in _OPAQUE_MEMBER_COLUMNS.items():
        table = tables[table_name]
        for row in rows[table_name]:
            key = _row_key(table, row)
            if states[table_name][key] == "public" and any(
                row.get(column) in participant_ids for column in columns
            ):
                changed |= _set_state(states, table_name, key, "ambiguous")
    return changed
