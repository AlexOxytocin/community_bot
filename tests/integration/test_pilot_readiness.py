"""Integration checks for pilot reporting and supported-schema readiness."""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import URL, make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from community_bot.application.pilot import PilotMetricsService
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    KarmaVoteHistoryModel,
    KarmaVoteModel,
    MemberModel,
)
from community_bot.infrastructure.db.pilot import PostgresPilotMetrics

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).parents[2]


@dataclass(frozen=True, slots=True)
class LegacySnapshot:
    """Exact representative rows inserted into supported revision 0009."""

    outbox_rows: dict[str, tuple[object, ...]]
    member_rows: tuple[tuple[object, ...], ...]
    transaction_rows: tuple[tuple[object, ...], ...]
    task_row: tuple[object, ...]
    assignment_row: tuple[object, ...]
    result_row: tuple[object, ...]
    karma_vote_row: tuple[object, ...]
    karma_history_rows: tuple[tuple[object, ...], ...]
    moderation_case_row: tuple[object, ...]
    resolution_row: tuple[object, ...]


def test_supported_schema_upgrade_preserves_outbox_semantics(
    postgresql_server_url: str,
) -> None:
    """Migration 0010 backfills old outbox rows and installs its DB guards."""
    server_url = make_url(postgresql_server_url)
    database_name = f"test_pilot_migration_{uuid4().hex}"
    asyncio.run(_database_command(server_url, f'CREATE DATABASE "{database_name}"'))
    database_url = server_url.set(database=database_name)
    try:
        _alembic(database_url, "0009")
        expected = asyncio.run(_seed_legacy_snapshot(database_url))
        _alembic(database_url, "head")
        asyncio.run(_assert_upgraded_snapshot(database_url, expected))
        _alembic(database_url, "head")
        asyncio.run(_assert_upgraded_snapshot(database_url, expected))
    finally:
        asyncio.run(_database_command(server_url, f'DROP DATABASE "{database_name}" WITH (FORCE)'))


def test_empty_database_cycles_and_restores_catalog_seed(database_url: str) -> None:
    """An empty database returns to head with the canonical eight-by-eight seed."""
    url = make_url(database_url)
    _alembic(url, "base", downgrade=True)
    _alembic(url, "head")
    counts = asyncio.run(_catalog_counts(url))
    assert counts == (8, 8, "0015")


@pytest.mark.asyncio
async def test_pilot_report_is_ledger_authoritative_and_contains_no_member_data(
    database_url: str,
) -> None:
    """The real adapter ignores caches and emits only privacy-safe aggregates."""
    database = Database(database_url)
    now = datetime.datetime.now(datetime.UTC)
    members = [
        MemberModel(
            telegram_user_id=9_910_000 + index,
            display_name=f"Private Pilot Member {index}",
            timezone="UTC",
            role="member",
            status="active",
            approved_at=now - datetime.timedelta(hours=2),
            credit_balance_cached=999,
            experience_total_cached=999,
        )
        for index in range(3)
    ]
    async with database.session_factory.begin() as session:
        session.add_all(members)
        await session.flush()
        session.add_all(
            AccountTransactionModel(
                member_id=member.id,
                credit_delta=10,
                experience_delta=0,
                transaction_type="starting_grant",
                idempotency_key=f"pilot-ledger:{member.id}",
                payload_hash="0" * 64,
            )
            for member in members
        )
    report = await PilotMetricsService(PostgresPilotMetrics(database.session_factory)).report(
        from_at=now - datetime.timedelta(days=1),
        to_at=now + datetime.timedelta(days=1),
        generated_at=now,
    )
    payload = report.model_dump_json()
    assert report.current_active_members == 3
    assert [cell.model_dump() for cell in report.credit_distribution.cells] == [
        {"label": "10-19", "count": 3}
    ]
    assert [cell.model_dump() for cell in report.experience_distribution.cells] == [
        {"label": "0", "count": 3}
    ]
    assert "Private Pilot Member" not in payload
    assert "991000" not in payload
    assert all(str(member.id) not in payload for member in members)
    await database.dispose()


@pytest.mark.asyncio
async def test_karma_history_keeps_actor_active_across_weekly_revisions(
    database_url: str,
) -> None:
    """Every immutable karma revision contributes its own activity timestamp."""
    database = Database(database_url)
    to_at = datetime.datetime(2026, 8, 15, tzinfo=datetime.UTC)
    previous_week = to_at - datetime.timedelta(days=10)
    current_week = to_at - datetime.timedelta(days=2)
    rater = MemberModel(
        telegram_user_id=9_920_001,
        display_name="Retention actor",
        timezone="UTC",
        role="member",
        status="active",
        approved_at=previous_week - datetime.timedelta(days=1),
    )
    target = MemberModel(
        telegram_user_id=9_920_002,
        display_name="Retention target",
        timezone="UTC",
        role="member",
        status="active",
        approved_at=previous_week - datetime.timedelta(days=1),
    )
    async with database.session_factory.begin() as session:
        session.add_all((rater, target))
        await session.flush()
        vote = KarmaVoteModel(
            rater_id=rater.id,
            target_id=target.id,
            value=1,
            comment="Current revision",
            revision=2,
            last_command_id=uuid4(),
            created_at=previous_week,
            updated_at=current_week,
        )
        session.add(vote)
        await session.flush()
        session.add_all(
            (
                KarmaVoteHistoryModel(
                    karma_vote_id=vote.id,
                    revision=1,
                    old_value=None,
                    new_value=-1,
                    old_comment=None,
                    new_comment="Previous revision",
                    command_id=uuid4(),
                    actor_member_id=rater.id,
                    created_at=previous_week,
                ),
                KarmaVoteHistoryModel(
                    karma_vote_id=vote.id,
                    revision=2,
                    old_value=-1,
                    new_value=1,
                    old_comment="Previous revision",
                    new_comment="Current revision",
                    command_id=uuid4(),
                    actor_member_id=rater.id,
                    created_at=current_week,
                ),
            )
        )

    facts = await PostgresPilotMetrics(database.session_factory).load_facts(to_at=to_at)
    report = await PilotMetricsService(PostgresPilotMetrics(database.session_factory)).report(
        from_at=to_at - datetime.timedelta(days=7),
        to_at=to_at,
        generated_at=to_at,
    )

    assert {(item.member_id, item.occurred_at) for item in facts.karma_activities} == {
        (rater.id, previous_week),
        (rater.id, current_week),
    }
    assert report.weekly_retention_rate.model_dump() == {
        "numerator": 1,
        "denominator": 1,
        "rate": "1.0000",
    }
    await database.dispose()


async def _seed_legacy_snapshot(url: URL) -> LegacySnapshot:
    engine = create_async_engine(url)
    author_id, performer_id = uuid4(), uuid4()
    author_grant_id, performer_grant_id = uuid4(), uuid4()
    reserve_id, reward_id = uuid4(), uuid4()
    task_id, assignment_id, result_id = uuid4(), uuid4(), uuid4()
    vote_id, history_one_id, history_two_id = uuid4(), uuid4(), uuid4()
    case_id, resolution_id = uuid4(), uuid4()
    publish_command_id, terminal_command_id, submit_command_id = uuid4(), uuid4(), uuid4()
    vote_command_one, vote_command_two = uuid4(), uuid4()
    case_command_id, resolution_command_id = uuid4(), uuid4()
    unpublished_id, published_id, aggregate_id = uuid4(), uuid4(), uuid4()
    created_at = datetime.datetime(2026, 8, 1, 12, tzinfo=datetime.UTC)
    accepted_at = created_at + datetime.timedelta(hours=1)
    submitted_at = accepted_at + datetime.timedelta(hours=1)
    reviewed_at = submitted_at + datetime.timedelta(hours=1)
    deadline_at = created_at + datetime.timedelta(days=2)
    resolution_at = reviewed_at + datetime.timedelta(hours=1)
    published_at = created_at + datetime.timedelta(minutes=5)
    outbox_rows = {
        "pilot:pending": (unpublished_id, {"kind": "pending"}, created_at, None),
        "pilot:published": (published_id, {"kind": "published"}, created_at, published_at),
    }
    try:
        async with engine.begin() as connection:
            template = (
                await connection.execute(
                    text(
                        "SELECT id,category_id,version FROM task_templates "
                        "WHERE is_active ORDER BY code,version LIMIT 1"
                    )
                )
            ).one()
            await connection.execute(
                text(
                    "INSERT INTO members "
                    "(id,telegram_user_id,display_name,timezone,role,status,level_number,"
                    "credit_balance_cached,experience_total_cached,approved_at) VALUES "
                    "(:author_id,9921001,'Legacy Author','UTC','member','active',1,3,0,"
                    ":created_at),"
                    "(:performer_id,9921002,'Legacy Performer','UTC','member','active',1,7,2,"
                    ":created_at)"
                ),
                {
                    "author_id": author_id,
                    "performer_id": performer_id,
                    "created_at": created_at,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO account_transactions "
                    "(id,member_id,credit_delta,experience_delta,transaction_type,"
                    "idempotency_key,payload_hash,created_at) VALUES "
                    "(:author_grant,:author_id,5,0,'starting_grant','pilot:author:grant',"
                    ":grant_hash,:created_at),"
                    "(:performer_grant,:performer_id,5,0,'starting_grant',"
                    "'pilot:performer:grant',:grant_hash,:created_at)"
                ),
                {
                    "author_grant": author_grant_id,
                    "performer_grant": performer_grant_id,
                    "author_id": author_id,
                    "performer_id": performer_id,
                    "grant_hash": "1" * 64,
                    "created_at": created_at,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO tasks "
                    "(id,origin,template_id,template_version,creator_id,author_display_name,"
                    "category_id,title,description,completion_criteria,materials_json,"
                    "input_payload_json,credit_reward_per_performer,performer_slots,"
                    "reserved_credit_total,estimated_minutes,minimum_level,format,deadline_at,"
                    "status,safety_snapshot_json,publish_command_id,published_at,created_at,"
                    "updated_at) VALUES "
                    "(:task_id,'member',:template_id,:template_version,:author_id,"
                    "'Legacy Author',:category_id,'Representative task','Preserved description',"
                    "'Preserved criteria','[]'::jsonb,'{}'::jsonb,2,1,2,30,1,'online',"
                    ":deadline_at,'completed','{}'::jsonb,:publish_command_id,:created_at,"
                    ":created_at,:created_at)"
                ),
                {
                    "task_id": task_id,
                    "template_id": template.id,
                    "template_version": template.version,
                    "author_id": author_id,
                    "category_id": template.category_id,
                    "deadline_at": deadline_at,
                    "publish_command_id": publish_command_id,
                    "created_at": created_at,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO assignments "
                    "(id,task_id,performer_id,slot_number,status,accepted_at,submitted_at,"
                    "reviewed_at,terminal_command_id,terminal_outcome,slot_ever_paid) VALUES "
                    "(:assignment_id,:task_id,:performer_id,1,'approved',:accepted_at,"
                    ":submitted_at,:reviewed_at,:terminal_command_id,'approved',true)"
                ),
                {
                    "assignment_id": assignment_id,
                    "task_id": task_id,
                    "performer_id": performer_id,
                    "accepted_at": accepted_at,
                    "submitted_at": submitted_at,
                    "reviewed_at": reviewed_at,
                    "terminal_command_id": terminal_command_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO assignment_result_versions "
                    "(id,assignment_id,version,payload_json,submit_command_id,created_at) VALUES "
                    '(:result_id,:assignment_id,1,\'{"proof":"preserved"}\'::jsonb,'
                    ":submit_command_id,:submitted_at)"
                ),
                {
                    "result_id": result_id,
                    "assignment_id": assignment_id,
                    "submit_command_id": submit_command_id,
                    "submitted_at": submitted_at,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO account_transactions "
                    "(id,member_id,credit_delta,experience_delta,transaction_type,"
                    "idempotency_key,payload_hash,task_id,assignment_id,created_at) VALUES "
                    "(:reserve_id,:author_id,-2,0,'task_reward_reserved','pilot:author:reserve',"
                    ":reserve_hash,:task_id,NULL,:created_at),"
                    "(:reward_id,:performer_id,2,2,'task_reward_earned',"
                    "'pilot:performer:reward',:reward_hash,:task_id,:assignment_id,:reviewed_at)"
                ),
                {
                    "reserve_id": reserve_id,
                    "reward_id": reward_id,
                    "author_id": author_id,
                    "performer_id": performer_id,
                    "reserve_hash": "2" * 64,
                    "reward_hash": "3" * 64,
                    "task_id": task_id,
                    "assignment_id": assignment_id,
                    "created_at": created_at,
                    "reviewed_at": reviewed_at,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO karma_votes "
                    "(id,rater_id,target_id,value,comment,revision,last_command_id,created_at,"
                    "updated_at) VALUES (:vote_id,:author_id,:performer_id,1,'Current vote',2,"
                    ":vote_command_two,:created_at,:reviewed_at)"
                ),
                {
                    "vote_id": vote_id,
                    "author_id": author_id,
                    "performer_id": performer_id,
                    "vote_command_two": vote_command_two,
                    "created_at": created_at,
                    "reviewed_at": reviewed_at,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO karma_vote_history "
                    "(id,karma_vote_id,revision,old_value,new_value,old_comment,new_comment,"
                    "command_id,actor_member_id,created_at) VALUES "
                    "(:history_one_id,:vote_id,1,NULL,-1,NULL,'Initial vote',:command_one,"
                    ":author_id,:created_at),"
                    "(:history_two_id,:vote_id,2,-1,1,'Initial vote','Current vote',:command_two,"
                    ":author_id,:reviewed_at)"
                ),
                {
                    "history_one_id": history_one_id,
                    "history_two_id": history_two_id,
                    "vote_id": vote_id,
                    "command_one": vote_command_one,
                    "command_two": vote_command_two,
                    "author_id": author_id,
                    "created_at": created_at,
                    "reviewed_at": reviewed_at,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO moderation_cases "
                    "(id,assignment_id,case_type,status,opened_by_member_id,open_command_id,"
                    "open_payload_hash,reason,current_resolution_id,revision,opened_at) VALUES "
                    "(:case_id,:assignment_id,'fraud_review','open',:author_id,:case_command_id,"
                    ":payload_hash,'representative_fraud_review',NULL,0,:reviewed_at)"
                ),
                {
                    "case_id": case_id,
                    "assignment_id": assignment_id,
                    "author_id": author_id,
                    "case_command_id": case_command_id,
                    "payload_hash": "4" * 64,
                    "reviewed_at": reviewed_at,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO dispute_resolutions "
                    "(id,case_id,version,code,actor_member_id,command_id,payload_hash,reason,"
                    "effect_json,conflict_snapshot_json,created_at) VALUES "
                    "(:resolution_id,:case_id,1,'confirm_original',:author_id,"
                    ":resolution_command_id,:payload_hash,'representative_resolution',"
                    "CAST(:effect AS jsonb),CAST(:conflict AS jsonb),"
                    ":resolution_at)"
                ),
                {
                    "resolution_id": resolution_id,
                    "case_id": case_id,
                    "author_id": author_id,
                    "resolution_command_id": resolution_command_id,
                    "payload_hash": "5" * 64,
                    "effect": json.dumps({"outcome": "approved"}),
                    "conflict": json.dumps({"assignment_revision": 1}),
                    "resolution_at": resolution_at,
                },
            )
            await connection.execute(
                text(
                    "UPDATE moderation_cases SET current_resolution_id=:resolution_id,"
                    "status='resolved',revision=1,resolved_at=:resolution_at WHERE id=:case_id"
                ),
                {
                    "resolution_id": resolution_id,
                    "resolution_at": resolution_at,
                    "case_id": case_id,
                },
            )
            for business_key, (
                event_id,
                payload,
                event_created_at,
                event_published_at,
            ) in outbox_rows.items():
                await connection.execute(
                    text(
                        "INSERT INTO outbox_events "
                        "(id,event_type,aggregate_type,aggregate_id,payload_json,business_key,"
                        "created_at,published_at) VALUES "
                        "(:id,'pilot.event','pilot',:aggregate_id,CAST(:payload AS jsonb),"
                        ":business_key,:created_at,:published_at)"
                    ),
                    {
                        "id": event_id,
                        "aggregate_id": aggregate_id,
                        "payload": json.dumps(payload),
                        "business_key": business_key,
                        "created_at": event_created_at,
                        "published_at": event_published_at,
                    },
                )
    finally:
        await engine.dispose()
    return LegacySnapshot(
        outbox_rows=outbox_rows,
        member_rows=(
            (author_id, 9_921_001, "Legacy Author", "member", "active", 1, 3, 0, created_at),
            (
                performer_id,
                9_921_002,
                "Legacy Performer",
                "member",
                "active",
                1,
                7,
                2,
                created_at,
            ),
        ),
        transaction_rows=(
            (
                author_grant_id,
                "pilot:author:grant",
                author_id,
                5,
                0,
                "starting_grant",
                "1" * 64,
                None,
                None,
                created_at,
            ),
            (
                reserve_id,
                "pilot:author:reserve",
                author_id,
                -2,
                0,
                "task_reward_reserved",
                "2" * 64,
                task_id,
                None,
                created_at,
            ),
            (
                performer_grant_id,
                "pilot:performer:grant",
                performer_id,
                5,
                0,
                "starting_grant",
                "1" * 64,
                None,
                None,
                created_at,
            ),
            (
                reward_id,
                "pilot:performer:reward",
                performer_id,
                2,
                2,
                "task_reward_earned",
                "3" * 64,
                task_id,
                assignment_id,
                reviewed_at,
            ),
        ),
        task_row=(
            task_id,
            "member",
            template.id,
            template.version,
            author_id,
            "Legacy Author",
            template.category_id,
            "Representative task",
            "Preserved description",
            "Preserved criteria",
            [],
            {},
            2,
            1,
            2,
            30,
            1,
            "online",
            deadline_at,
            "completed",
            {},
            publish_command_id,
            created_at,
            created_at,
            created_at,
        ),
        assignment_row=(
            assignment_id,
            task_id,
            performer_id,
            1,
            "approved",
            True,
            accepted_at,
            submitted_at,
            reviewed_at,
            terminal_command_id,
            "approved",
        ),
        result_row=(
            result_id,
            assignment_id,
            1,
            {"proof": "preserved"},
            submit_command_id,
            submitted_at,
        ),
        karma_vote_row=(
            vote_id,
            author_id,
            performer_id,
            1,
            "Current vote",
            2,
            vote_command_two,
            created_at,
            reviewed_at,
        ),
        karma_history_rows=(
            (
                history_one_id,
                vote_id,
                1,
                None,
                -1,
                None,
                "Initial vote",
                vote_command_one,
                author_id,
                created_at,
            ),
            (
                history_two_id,
                vote_id,
                2,
                -1,
                1,
                "Initial vote",
                "Current vote",
                vote_command_two,
                author_id,
                reviewed_at,
            ),
        ),
        moderation_case_row=(
            case_id,
            assignment_id,
            None,
            "fraud_review",
            "resolved",
            author_id,
            case_command_id,
            "4" * 64,
            "representative_fraud_review",
            resolution_id,
            1,
            reviewed_at,
            resolution_at,
        ),
        resolution_row=(
            resolution_id,
            case_id,
            1,
            "confirm_original",
            author_id,
            resolution_command_id,
            "5" * 64,
            "representative_resolution",
            {"outcome": "approved"},
            {"assignment_revision": 1},
            resolution_at,
        ),
    )


async def _assert_upgraded_snapshot(
    url: URL,
    expected: LegacySnapshot,
) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT id,payload_json,created_at,published_at,status,attempt_count,"
                        "next_attempt_at FROM outbox_events ORDER BY business_key"
                    )
                )
            ).all()
            assert len(rows) == 2
            pending, published = rows
            for row, business_key in zip(rows, sorted(expected.outbox_rows), strict=True):
                event_id, payload, created_at, published_at = expected.outbox_rows[business_key]
                assert tuple(row[:4]) == (event_id, payload, created_at, published_at)
                assert row.attempt_count == 0
                assert row.next_attempt_at is not None
            assert pending.status == "pending"
            assert published.status == "materialized"
            await _assert_preserved_domain(connection, expected)
            constraints = set(
                await connection.scalars(
                    text(
                        "SELECT conname FROM pg_constraint WHERE conrelid IN "
                        "('outbox_events'::regclass,'notifications'::regclass)"
                    )
                )
            )
            indexes = set(
                await connection.scalars(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE tablename IN "
                        "('outbox_events','notifications')"
                    )
                )
            )
            assert {
                "ck_outbox_status",
                "ck_outbox_lease_state",
                "ck_outbox_materialized_at",
                "ck_outbox_failed_error",
                "ck_notifications_status",
                "ck_notifications_lease_state",
            } <= constraints
            assert {"ix_outbox_due", "ix_notifications_due"} <= indexes
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version")) == "0015"
            )
            invalid_states = (
                "UPDATE outbox_events SET status='processing' WHERE business_key='pilot:pending'",
                (
                    "UPDATE outbox_events SET status='failed',last_error_code=NULL "
                    "WHERE business_key='pilot:pending'"
                ),
                (
                    "UPDATE outbox_events SET status='materialized',published_at=NULL "
                    "WHERE business_key='pilot:pending'"
                ),
            )
            for statement in invalid_states:
                savepoint = await connection.begin_nested()
                with pytest.raises(DBAPIError):
                    await connection.execute(text(statement))
                await savepoint.rollback()
    finally:
        await engine.dispose()


async def _assert_preserved_domain(
    connection: AsyncConnection,
    expected: LegacySnapshot,
) -> None:
    counts = (
        await connection.execute(
            text(
                "SELECT (SELECT count(*) FROM members),"
                "(SELECT count(*) FROM account_transactions),"
                "(SELECT count(*) FROM tasks),"
                "(SELECT count(*) FROM assignments),"
                "(SELECT count(*) FROM assignment_result_versions),"
                "(SELECT count(*) FROM karma_votes),"
                "(SELECT count(*) FROM karma_vote_history),"
                "(SELECT count(*) FROM moderation_cases),"
                "(SELECT count(*) FROM dispute_resolutions)"
            )
        )
    ).one()
    assert tuple(counts) == (2, 4, 1, 1, 1, 1, 2, 1, 1)
    rows = (
        await connection.execute(
            text(
                "SELECT id,telegram_user_id,display_name,role,status,level_number,"
                "credit_balance_cached,experience_total_cached,approved_at "
                "FROM members WHERE telegram_user_id IN (9921001,9921002) "
                "ORDER BY telegram_user_id"
            )
        )
    ).all()
    assert tuple(tuple(row) for row in rows) == expected.member_rows
    rows = (
        await connection.execute(
            text(
                "SELECT id,idempotency_key,member_id,credit_delta,experience_delta,"
                "transaction_type,payload_hash,task_id,assignment_id,created_at "
                "FROM account_transactions "
                "WHERE idempotency_key LIKE 'pilot:%' ORDER BY idempotency_key"
            )
        )
    ).all()
    assert tuple(tuple(row) for row in rows) == expected.transaction_rows
    assert (
        tuple(
            (
                await connection.execute(
                    text(
                        "SELECT id,origin,template_id,template_version,creator_id,"
                        "author_display_name,category_id,title,description,completion_criteria,"
                        "materials_json,input_payload_json,credit_reward_per_performer,"
                        "performer_slots,reserved_credit_total,estimated_minutes,minimum_level,"
                        "format,deadline_at,status,safety_snapshot_json,publish_command_id,"
                        "published_at,created_at,updated_at FROM tasks WHERE id=:id"
                    ),
                    {"id": expected.task_row[0]},
                )
            ).one()
        )
        == expected.task_row
    )
    assert (
        tuple(
            (
                await connection.execute(
                    text(
                        "SELECT id,task_id,performer_id,slot_number,status,slot_ever_paid,"
                        "accepted_at,submitted_at,reviewed_at,terminal_command_id,terminal_outcome "
                        "FROM assignments WHERE id=:id"
                    ),
                    {"id": expected.assignment_row[0]},
                )
            ).one()
        )
        == expected.assignment_row
    )
    assert (
        tuple(
            (
                await connection.execute(
                    text(
                        "SELECT id,assignment_id,version,payload_json,submit_command_id,created_at "
                        "FROM assignment_result_versions WHERE id=:id"
                    ),
                    {"id": expected.result_row[0]},
                )
            ).one()
        )
        == expected.result_row
    )
    assert (
        tuple(
            (
                await connection.execute(
                    text(
                        "SELECT id,rater_id,target_id,value,comment,revision,last_command_id,"
                        "created_at,updated_at FROM karma_votes WHERE id=:id"
                    ),
                    {"id": expected.karma_vote_row[0]},
                )
            ).one()
        )
        == expected.karma_vote_row
    )
    rows = (
        await connection.execute(
            text(
                "SELECT id,karma_vote_id,revision,old_value,new_value,old_comment,new_comment,"
                "command_id,actor_member_id,created_at FROM karma_vote_history "
                "WHERE karma_vote_id=:vote_id ORDER BY revision"
            ),
            {"vote_id": expected.karma_vote_row[0]},
        )
    ).all()
    assert tuple(tuple(row) for row in rows) == expected.karma_history_rows
    assert (
        tuple(
            (
                await connection.execute(
                    text(
                        "SELECT id,assignment_id,dispute_id,case_type,status,opened_by_member_id,"
                        "open_command_id,open_payload_hash,reason,current_resolution_id,revision,"
                        "opened_at,resolved_at FROM moderation_cases WHERE id=:id"
                    ),
                    {"id": expected.moderation_case_row[0]},
                )
            ).one()
        )
        == expected.moderation_case_row
    )
    assert (
        tuple(
            (
                await connection.execute(
                    text(
                        "SELECT id,case_id,version,code,actor_member_id,command_id,payload_hash,"
                        "reason,effect_json,conflict_snapshot_json,created_at "
                        "FROM dispute_resolutions WHERE id=:id"
                    ),
                    {"id": expected.resolution_row[0]},
                )
            ).one()
        )
        == expected.resolution_row
    )
    orphan_counts = (
        await connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM account_transactions t LEFT JOIN members m "
                "ON m.id=t.member_id LEFT JOIN tasks task ON task.id=t.task_id "
                "LEFT JOIN assignments a ON a.id=t.assignment_id WHERE m.id IS NULL OR "
                "(t.task_id IS NOT NULL AND task.id IS NULL) OR "
                "(t.assignment_id IS NOT NULL AND a.id IS NULL)),"
                "(SELECT count(*) FROM assignments a LEFT JOIN tasks t ON t.id=a.task_id "
                "LEFT JOIN members m ON m.id=a.performer_id WHERE t.id IS NULL OR m.id IS NULL),"
                "(SELECT count(*) FROM assignment_result_versions r LEFT JOIN assignments a "
                "ON a.id=r.assignment_id WHERE a.id IS NULL),"
                "(SELECT count(*) FROM karma_vote_history h LEFT JOIN karma_votes v "
                "ON v.id=h.karma_vote_id LEFT JOIN members m ON m.id=h.actor_member_id "
                "WHERE v.id IS NULL OR m.id IS NULL),"
                "(SELECT count(*) FROM moderation_cases c LEFT JOIN assignments a "
                "ON a.id=c.assignment_id LEFT JOIN members m ON m.id=c.opened_by_member_id "
                "LEFT JOIN dispute_resolutions r ON r.id=c.current_resolution_id "
                "AND r.case_id=c.id WHERE a.id IS NULL OR m.id IS NULL OR r.id IS NULL),"
                "(SELECT count(*) FROM dispute_resolutions r LEFT JOIN moderation_cases c "
                "ON c.id=r.case_id LEFT JOIN members m ON m.id=r.actor_member_id "
                "WHERE c.id IS NULL OR m.id IS NULL)"
            )
        )
    ).one()
    assert tuple(orphan_counts) == (0, 0, 0, 0, 0, 0)


async def _catalog_counts(url: URL) -> tuple[int, int, str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            categories = await connection.scalar(text("SELECT count(*) FROM task_categories"))
            templates = await connection.scalar(text("SELECT count(*) FROM task_templates"))
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            return int(categories or 0), int(templates or 0), str(revision)
    finally:
        await engine.dispose()


def _alembic(url: URL, revision: str, *, downgrade: bool = False) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = url.render_as_string(hide_password=False)
    subprocess.run(  # noqa: S603 - fixed interpreter and Alembic arguments.
        [sys.executable, "-m", "alembic", "downgrade" if downgrade else "upgrade", revision],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
    )


async def _database_command(server_url: URL, command: str) -> None:
    maintenance_url = server_url.set(database="postgres")
    engine = create_async_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(command))
    finally:
        await engine.dispose()
