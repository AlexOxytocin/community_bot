"""Create an isolated local fixture for visual review of the task home screen."""

from __future__ import annotations

import asyncio
import datetime
import os
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url

from community_bot.application.economy import ProductConfigActivationCommand
from community_bot.domain.economy import LevelDefinition, ProductConfigCandidate
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.economy import (
    acquire_product_config_mutation_gate,
    activate_product_config_locked,
    ingest_product_config_locked,
)
from community_bot.infrastructure.db.models import (
    ActiveProductConfigModel,
    AssignmentModel,
    AssignmentResultVersionModel,
    LevelModel,
    MemberModel,
    ProductConfigVersionModel,
    TaskCancellationRequestModel,
    TaskCancellationResponseModel,
    TaskCategoryModel,
    TaskModel,
    TaskTemplateModel,
    TestRunModel,
    TestRunParticipantModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_DATABASE_URL = (
    "postgresql+asyncpg://community_bot_local:community_bot_local@"
    "127.0.0.1:55432/community_bot_local"
)
_REVIEW_TELEGRAM_USER_ID = 900000000001
_FIXTURE_MARKER_PREFIX = "TEST-LOCAL-TASK-HOME-"
_REQUIRED_ACTIVE_CAPACITY = 10


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", _DATABASE_URL)
    parsed = make_url(value)
    allowed_hosts = {"127.0.0.1", "localhost"}
    if (
        parsed.drivername != "postgresql+asyncpg"
        or parsed.host not in allowed_hosts
        or parsed.port != 55432
        or parsed.database != "community_bot_local"
    ):
        message = (
            "Refusing to seed anything except the local review database at "
            "127.0.0.1:55432/community_bot_local."
        )
        raise RuntimeError(message)
    return value


async def _member(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    display_name: str,
) -> MemberModel:
    member = await session.scalar(
        select(MemberModel).where(MemberModel.telegram_user_id == telegram_user_id)
    )
    if member is None:
        member = MemberModel(
            id=uuid.uuid4(),
            telegram_user_id=telegram_user_id,
            telegram_username=None,
            display_name=display_name,
            timezone="Europe/Moscow",
            role="member",
            status="active",
            level_number=1,
            credit_balance_cached=100,
            experience_total_cached=0,
            approved_at=datetime.datetime.now(datetime.UTC),
        )
        session.add(member)
        await session.flush()
    else:
        member.display_name = display_name
        member.status = "active"
        member.level_number = max(1, member.level_number)
    return member


async def _ensure_active_capacity(session: AsyncSession, *, actor_id: uuid.UUID) -> None:
    pointer = await session.get(ActiveProductConfigModel, True)
    if pointer is None:
        raise RuntimeError("The local database has no active product configuration.")
    active = await session.get(ProductConfigVersionModel, pointer.product_config_version_id)
    if active is None:
        raise RuntimeError("The active local product configuration is missing.")
    current_limit = int(
        active.payload_json.get("assignment_policy", {}).get("maximum_active_assignments", 3)
    )
    if current_limit >= _REQUIRED_ACTIVE_CAPACITY:
        return

    await acquire_product_config_mutation_gate(session)
    levels = tuple(
        LevelDefinition(
            level_number=item.level_number,
            experience_required=item.experience_required,
            display_name=item.display_name,
            description=item.description,
            level_up_message=item.level_up_message,
            permissions=item.permissions_json,
        )
        for item in (
            await session.scalars(
                select(LevelModel)
                .where(LevelModel.product_config_version_id == active.id)
                .order_by(LevelModel.level_number)
            )
        ).all()
    )
    maximum_version = int(
        await session.scalar(select(func.max(ProductConfigVersionModel.version))) or 0
    )
    payload = active.payload_json
    candidate = ProductConfigCandidate(
        schema_version=int(payload["schema_version"]),
        config_version=maximum_version + 1,
        levels=levels,
        interaction_alert_threshold=int(payload["interaction_alert_threshold"]),
        interaction_alert_window_days=int(payload["interaction_alert_window_days"]),
        maximum_active_assignments=_REQUIRED_ACTIVE_CAPACITY,
        assignment_policy_in_payload=True,
    )
    matching = await session.scalar(
        select(ProductConfigVersionModel).where(
            ProductConfigVersionModel.content_hash == candidate.content_hash
        )
    )
    target_version = (
        matching.version
        if matching is not None
        else (
            await ingest_product_config_locked(session, candidate=candidate, actor_id=actor_id)
        ).version
    )
    await activate_product_config_locked(
        session,
        ProductConfigActivationCommand(
            activation_command_id=uuid.uuid4(),
            target_config_version=target_version,
            actor_member_id=actor_id,
            reason="Local task-home UI review fixture.",
        ),
    )


async def _retire_previous_fixtures(
    session: AsyncSession, *, participant_ids: set[uuid.UUID]
) -> None:
    previous_run_ids = tuple(
        await session.scalars(
            select(TestRunModel.id).where(TestRunModel.marker.like(f"{_FIXTURE_MARKER_PREFIX}%"))
        )
    )
    now = datetime.datetime.now(datetime.UTC)
    if previous_run_ids:
        await session.execute(
            update(AssignmentModel)
            .where(
                AssignmentModel.task_id.in_(
                    select(TaskModel.id).where(TaskModel.test_run_id.in_(previous_run_ids))
                ),
                AssignmentModel.status.in_(
                    (
                        "accepted",
                        "submitted",
                        "rejected_pending_dispute",
                        "disputed",
                        "reviewer_required",
                    )
                ),
            )
            .values(status="cancelled", cancelled_at=now)
        )
        await session.execute(
            update(TestRunParticipantModel)
            .where(TestRunParticipantModel.run_id.in_(previous_run_ids))
            .values(is_active=False, left_at=now)
        )
        await session.execute(
            update(TestRunModel)
            .where(TestRunModel.id.in_(previous_run_ids))
            .values(status="completed", ended_at=now)
        )

    conflicting = (
        (
            await session.execute(
                select(TestRunModel.marker)
                .join(TestRunParticipantModel, TestRunParticipantModel.run_id == TestRunModel.id)
                .where(
                    TestRunParticipantModel.member_id.in_(participant_ids),
                    TestRunParticipantModel.is_active.is_(True),
                    ~TestRunModel.marker.like(f"{_FIXTURE_MARKER_PREFIX}%"),
                )
            )
        )
        .scalars()
        .all()
    )
    if conflicting:
        markers = ", ".join(sorted(set(conflicting)))
        raise RuntimeError(f"Refusing to replace unrelated active test runs: {markers}")


def _task(
    *,
    run_id: uuid.UUID,
    category: TaskCategoryModel,
    creator: MemberModel,
    author_name: str,
    title: str,
    reward: int,
    created_at: datetime.datetime,
    deadline_at: datetime.datetime,
    status: str = "published",
    template: TaskTemplateModel | None = None,
) -> TaskModel:
    return TaskModel(
        id=uuid.uuid4(),
        origin="member",
        test_run_id=run_id,
        template_id=None if template is None else template.id,
        template_version=None if template is None else template.version,
        creator_id=creator.id,
        author_display_name=author_name,
        category_id=category.id,
        time_size="s",
        title=title,
        description=f"Тестовое описание: {title}",
        completion_criteria="Результат приложен и соответствует описанию.",
        materials_json={},
        input_payload_json={},
        credit_reward_per_performer=reward,
        performer_slots=1,
        reserved_credit_total=reward,
        estimated_minutes=25,
        minimum_level=1,
        format="online",
        city=None,
        deadline_at=deadline_at,
        status=status,
        safety_snapshot_json={
            "category_name": category.name,
            "category_icon": category.icon,
            "task_kind": "solo",
            "time_size": "s",
            "performer_instructions": "Выполните задание и приложите результат.",
            "public_input_keys": [],
        },
        publish_command_id=uuid.uuid4(),
        published_at=created_at,
        cancelled_at=created_at if status == "cancelled" else None,
        closed_for_new_performers_at=(
            created_at if status == "closed_for_new_performers" else None
        ),
        created_at=created_at,
        updated_at=created_at,
    )


def _assignment(
    *,
    task: TaskModel,
    performer: MemberModel,
    status: str,
    accepted_at: datetime.datetime,
) -> AssignmentModel:
    submitted = status in {"submitted", "rejected_pending_dispute", "disputed"}
    rejected = status in {"rejected_pending_dispute", "disputed"}
    return AssignmentModel(
        id=uuid.uuid4(),
        task_id=task.id,
        performer_id=performer.id,
        slot_number=1,
        status=status,
        accepted_at=accepted_at,
        submitted_at=accepted_at + datetime.timedelta(minutes=15) if submitted else None,
        review_deadline_at=(
            accepted_at + datetime.timedelta(days=3) if submitted and not rejected else None
        ),
        rejected_at=accepted_at + datetime.timedelta(hours=1) if rejected else None,
        reject_dispute_deadline_at=(accepted_at + datetime.timedelta(days=3) if rejected else None),
        slot_ever_paid=False,
    )


async def _seed(session: AsyncSession) -> dict[str, object]:
    actor = await session.scalar(
        select(MemberModel).where(MemberModel.telegram_user_id == _REVIEW_TELEGRAM_USER_ID)
    )
    if actor is None:
        raise RuntimeError("Open /local-review once before seeding the local task-home fixture.")
    creator_one = await _member(
        session,
        telegram_user_id=900000000101,
        display_name="Сообщество",
    )
    creator_two = await _member(
        session,
        telegram_user_id=900000000102,
        display_name="Мария Орлова",
    )
    performer = await _member(
        session,
        telegram_user_id=900000000103,
        display_name="Тестовый участник",
    )
    participants = {actor.id, creator_one.id, creator_two.id, performer.id}
    await _retire_previous_fixtures(session, participant_ids=participants)
    await _ensure_active_capacity(session, actor_id=actor.id)

    now = datetime.datetime.now(datetime.UTC)
    run = TestRunModel(
        id=uuid.uuid4(),
        marker=(f"{_FIXTURE_MARKER_PREFIX}{now:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6].upper()}"),
        status="active",
        started_by_member_id=actor.id,
        started_at=now,
    )
    session.add(run)
    session.add_all(
        TestRunParticipantModel(run_id=run.id, member_id=member_id, is_active=True)
        for member_id in participants
    )

    category = await session.scalar(
        select(TaskCategoryModel)
        .where(TaskCategoryModel.is_active.is_(True))
        .order_by(TaskCategoryModel.sort_order)
    )
    template = await session.scalar(
        select(TaskTemplateModel)
        .where(TaskTemplateModel.is_active.is_(True))
        .order_by(TaskTemplateModel.created_at, TaskTemplateModel.id)
    )
    if category is None or template is None:
        raise RuntimeError("The local task catalog is not initialized.")

    available_titles = (
        "Проверить сценарий первого запуска",
        "Вычитать welcome-гайд",
        "Проверить форму создания задания",
        "Подготовить вопросы для интервью",
        "Протестировать уведомления Mini App",
        "Собрать обратную связь участников",
        "Проверить карточку профиля",
        "Обновить описание сообщества",
        "Проверить мобильную навигацию",
        "Сверить тексты системных сообщений",
        "Подготовить краткий чек-лист",
        "Проверить экран модерации",
    )
    available_tasks = [
        _task(
            run_id=run.id,
            category=category,
            creator=creator_one if index % 2 == 0 else creator_two,
            author_name="Сообщество" if index % 2 == 0 else "Мария Орлова",
            title=title,
            reward=(4, 3, 2, 1)[index % 4],
            created_at=now - datetime.timedelta(minutes=index),
            deadline_at=now + datetime.timedelta(days=2 + index),
        )
        for index, title in enumerate(available_titles)
    ]

    submit_task = _task(
        run_id=run.id,
        category=category,
        creator=creator_one,
        author_name=creator_one.display_name,
        title="Подготовить результат для проверки",
        reward=3,
        created_at=now - datetime.timedelta(hours=1),
        deadline_at=now + datetime.timedelta(days=3),
    )
    cancellation_task = _task(
        run_id=run.id,
        category=category,
        creator=creator_two,
        author_name=creator_two.display_name,
        title="Согласовать отмену группового задания",
        reward=2,
        created_at=now - datetime.timedelta(hours=2),
        deadline_at=now + datetime.timedelta(days=4),
        status="closed_for_new_performers",
        template=template,
    )
    submitted_task = _task(
        run_id=run.id,
        category=category,
        creator=creator_one,
        author_name=creator_one.display_name,
        title="Результат ожидает проверки автора",
        reward=4,
        created_at=now - datetime.timedelta(hours=3),
        deadline_at=now + datetime.timedelta(days=4),
        template=template,
    )
    disputed_task = _task(
        run_id=run.id,
        category=category,
        creator=creator_two,
        author_name=creator_two.display_name,
        title="Решение по результату ожидается",
        reward=3,
        created_at=now - datetime.timedelta(hours=4),
        deadline_at=now + datetime.timedelta(days=5),
    )
    review_task = _task(
        run_id=run.id,
        category=category,
        creator=actor,
        author_name=actor.display_name,
        title="Проверить работу тестового участника",
        reward=3,
        created_at=now - datetime.timedelta(hours=5),
        deadline_at=now + datetime.timedelta(days=3),
    )

    archive_statuses = ("completed", "cancelled", "expired", "partially_completed")
    archive_tasks = [
        _task(
            run_id=run.id,
            category=category,
            creator=actor,
            author_name=actor.display_name,
            title=f"Архивное задание {index + 1:02d}",
            reward=(index % 4) + 1,
            created_at=now - datetime.timedelta(days=60 + index),
            deadline_at=now - datetime.timedelta(days=30 + index),
            status=archive_statuses[index % len(archive_statuses)],
        )
        for index in range(18)
    ]
    session.add_all(
        [
            *available_tasks,
            submit_task,
            cancellation_task,
            submitted_task,
            disputed_task,
            review_task,
            *archive_tasks,
        ]
    )
    await session.flush()

    submit_assignment = _assignment(
        task=submit_task,
        performer=actor,
        status="accepted",
        accepted_at=now - datetime.timedelta(minutes=50),
    )
    cancellation_assignment = _assignment(
        task=cancellation_task,
        performer=actor,
        status="accepted",
        accepted_at=now - datetime.timedelta(hours=1, minutes=30),
    )
    submitted_assignment = _assignment(
        task=submitted_task,
        performer=actor,
        status="submitted",
        accepted_at=now - datetime.timedelta(hours=3),
    )
    disputed_assignment = _assignment(
        task=disputed_task,
        performer=actor,
        status="rejected_pending_dispute",
        accepted_at=now - datetime.timedelta(hours=4),
    )
    review_assignment = _assignment(
        task=review_task,
        performer=performer,
        status="submitted",
        accepted_at=now - datetime.timedelta(hours=5),
    )
    session.add_all(
        (
            submit_assignment,
            cancellation_assignment,
            submitted_assignment,
            disputed_assignment,
            review_assignment,
        )
    )
    await session.flush()

    session.add_all(
        AssignmentResultVersionModel(
            id=uuid.uuid4(),
            assignment_id=assignment.id,
            version=1,
            payload_json={"result": summary},
            submit_command_id=uuid.uuid4(),
            created_at=now - datetime.timedelta(minutes=10),
        )
        for assignment, summary in (
            (submitted_assignment, "Ссылка на готовый результат и короткое описание."),
            (disputed_assignment, "Исправленный результат после замечаний."),
            (review_assignment, "Макет проверен на мобильном устройстве."),
        )
    )

    cancellation_request = TaskCancellationRequestModel(
        id=uuid.uuid4(),
        task_id=cancellation_task.id,
        requested_by_member_id=creator_two.id,
        status="pending",
        created_at=now - datetime.timedelta(minutes=20),
    )
    session.add(cancellation_request)
    await session.flush()
    session.add(
        TaskCancellationResponseModel(
            id=uuid.uuid4(),
            request_id=cancellation_request.id,
            assignment_id=cancellation_assignment.id,
            performer_id=actor.id,
            status="pending",
        )
    )
    await session.flush()
    return {
        "run_id": run.id,
        "marker": run.marker,
        "actor_id": actor.id,
    }


async def _main() -> None:
    database = Database(_database_url())
    try:
        async with database.session_factory.begin() as session:
            result = await _seed(session)
    finally:
        await database.dispose()
    print(f"Local task-home fixture active: {result['marker']} ({result['run_id']})")
    print(
        "Expected task-home counters: attention 1/1/1, available 12, "
        "active 2, waiting 2, archive 18."
    )


if __name__ == "__main__":
    asyncio.run(_main())
