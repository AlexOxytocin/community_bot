from __future__ import annotations

import datetime
from dataclasses import replace
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from community_bot.domain.members import (
    ADMINISTRATOR_MANAGEMENT_PERMISSION,
    ADMINISTRATOR_PERMISSIONS,
    COMMUNITY_TASK_CREATE_PERMISSION,
    COMMUNITY_TASK_REVIEW_PERMISSION,
    DISPUTE_MODERATION_PERMISSION,
    MEMBER_BLOCKING_PERMISSION,
    MEMBER_INVITATION_PERMISSION,
    SUPERADMINISTRATOR_PERMISSION,
    AuthorizationError,
    ChangeKind,
    Member,
    MemberRole,
    MemberStatus,
    StartOutcome,
    assign_administrator,
    can_create_community_task,
    can_edit_administrator,
    can_read_member,
    can_review_community_task,
    change_member,
    demote_administrator,
    route_start,
    update_administrator_permissions,
)


def member(
    *,
    role: MemberRole = MemberRole.MEMBER,
    status: MemberStatus = MemberStatus.ACTIVE,
    permissions: frozenset[str] = frozenset(),
) -> Member:
    return Member(
        id=uuid4(),
        telegram_user_id=1,
        role=role,
        status=status,
        permissions=permissions,
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (MemberStatus.PENDING, StartOutcome.REGISTRATION_PENDING),
        (MemberStatus.ACTIVE, StartOutcome.MAIN_MENU),
        (MemberStatus.PAUSED, StartOutcome.ACCOUNT_UNAVAILABLE),
        (MemberStatus.RESTRICTED, StartOutcome.ACCOUNT_UNAVAILABLE),
        (MemberStatus.SUSPENDED, StartOutcome.ACCOUNT_UNAVAILABLE),
        (MemberStatus.LEFT, StartOutcome.ACCOUNT_UNAVAILABLE),
        (MemberStatus.BANNED, StartOutcome.ACCOUNT_UNAVAILABLE),
    ],
)
def test_start_route_covers_every_member_status(
    status: MemberStatus,
    expected: StartOutcome,
) -> None:
    assert route_start(member(status=status)) is expected


def test_start_route_requires_invitation_for_unknown_member() -> None:
    assert route_start(None) is StartOutcome.REGISTRATION_REQUIRED


@given(st.sampled_from(list(MemberStatus)))
def test_start_route_is_deterministic_for_every_generated_status(status: MemberStatus) -> None:
    snapshot = member(status=status)

    assert route_start(snapshot) is route_start(snapshot)


@pytest.mark.parametrize("role", list(MemberRole))
@pytest.mark.parametrize("status", list(MemberStatus))
def test_only_active_administrator_can_read_another_member(
    role: MemberRole,
    status: MemberStatus,
) -> None:
    actor = member(role=role, status=status)
    target = member()

    assert can_read_member(actor=actor, target=target) is (
        role is MemberRole.ADMINISTRATOR and status is MemberStatus.ACTIVE
    )


@pytest.mark.parametrize("role", [MemberRole.MEMBER, MemberRole.MODERATOR])
def test_active_non_administrator_can_read_only_self(role: MemberRole) -> None:
    actor = member(role=role)

    assert can_read_member(actor=actor, target=actor)
    assert not can_read_member(actor=actor, target=member())


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (MemberRole.MEMBER, MemberRole.MODERATOR),
        (MemberRole.MODERATOR, MemberRole.MEMBER),
    ],
)
@pytest.mark.parametrize("status", [MemberStatus.ACTIVE, MemberStatus.PAUSED])
def test_allowed_role_transitions(
    current: MemberRole,
    requested: MemberRole,
    status: MemberStatus,
) -> None:
    actor = member(role=MemberRole.ADMINISTRATOR)
    target = member(role=current, status=status)

    changed = change_member(
        actor=actor,
        target=target,
        kind=ChangeKind.ROLE,
        requested_value=requested.value,
    )

    assert changed.role is requested
    assert changed.status is status


@pytest.mark.parametrize("current", list(MemberRole))
@pytest.mark.parametrize("requested", list(MemberRole))
def test_role_transition_matrix_denies_every_unlisted_pair(
    current: MemberRole,
    requested: MemberRole,
) -> None:
    if (current, requested) in {
        (MemberRole.MEMBER, MemberRole.MODERATOR),
        (MemberRole.MODERATOR, MemberRole.MEMBER),
    }:
        return
    actor = member(role=MemberRole.ADMINISTRATOR)
    target = member(role=current)

    with pytest.raises(AuthorizationError):
        change_member(
            actor=actor,
            target=target,
            kind=ChangeKind.ROLE,
            requested_value=requested.value,
        )


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (MemberStatus.ACTIVE, MemberStatus.PAUSED),
        (MemberStatus.PAUSED, MemberStatus.ACTIVE),
    ],
)
@pytest.mark.parametrize("role", [MemberRole.MEMBER, MemberRole.MODERATOR])
def test_allowed_status_transitions(
    current: MemberStatus,
    requested: MemberStatus,
    role: MemberRole,
) -> None:
    changed = change_member(
        actor=member(role=MemberRole.ADMINISTRATOR),
        target=member(role=role, status=current),
        kind=ChangeKind.STATUS,
        requested_value=requested.value,
    )

    assert changed.status is requested


def test_only_superadministrator_can_promote_regular_member_to_admin() -> None:
    actor = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset({SUPERADMINISTRATOR_PERMISSION}),
    )
    target = member(role=MemberRole.MODERATOR)

    changed = change_member(
        actor=actor,
        target=target,
        kind=ChangeKind.ROLE,
        requested_value=MemberRole.ADMINISTRATOR.value,
    )

    assert changed.role is MemberRole.ADMINISTRATOR
    assert changed.permissions == ADMINISTRATOR_PERMISSIONS
    assert SUPERADMINISTRATOR_PERMISSION not in changed.permissions


def test_superadministrator_can_demote_regular_admin_and_strip_admin_permissions() -> None:
    actor = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset({SUPERADMINISTRATOR_PERMISSION}),
    )
    target = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=ADMINISTRATOR_PERMISSIONS,
    )

    changed = change_member(
        actor=actor,
        target=target,
        kind=ChangeKind.ROLE,
        requested_value=MemberRole.MEMBER.value,
    )

    assert changed.role is MemberRole.MEMBER
    assert changed.permissions == frozenset()


def test_superadministrator_can_pause_regular_admin() -> None:
    actor = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset({SUPERADMINISTRATOR_PERMISSION}),
    )
    target = member(role=MemberRole.ADMINISTRATOR)

    changed = change_member(
        actor=actor,
        target=target,
        kind=ChangeKind.STATUS,
        requested_value=MemberStatus.PAUSED.value,
    )

    assert changed.status is MemberStatus.PAUSED


@pytest.mark.parametrize("current", list(MemberStatus))
@pytest.mark.parametrize("requested", list(MemberStatus))
def test_status_transition_matrix_denies_every_unlisted_pair(
    current: MemberStatus,
    requested: MemberStatus,
) -> None:
    if (current, requested) in {
        (MemberStatus.ACTIVE, MemberStatus.PAUSED),
        (MemberStatus.PAUSED, MemberStatus.ACTIVE),
    }:
        return

    with pytest.raises(AuthorizationError):
        change_member(
            actor=member(role=MemberRole.ADMINISTRATOR),
            target=member(status=current),
            kind=ChangeKind.STATUS,
            requested_value=requested.value,
        )


@pytest.mark.parametrize("role", [MemberRole.MEMBER, MemberRole.MODERATOR])
@pytest.mark.parametrize("status", list(MemberStatus))
def test_non_administrator_or_inactive_actor_is_denied(
    role: MemberRole,
    status: MemberStatus,
) -> None:
    with pytest.raises(AuthorizationError):
        change_member(
            actor=member(role=role, status=status),
            target=member(),
            kind=ChangeKind.STATUS,
            requested_value=MemberStatus.PAUSED.value,
        )


def test_self_target_is_denied() -> None:
    actor = member(role=MemberRole.ADMINISTRATOR)

    with pytest.raises(AuthorizationError):
        change_member(
            actor=actor,
            target=actor,
            kind=ChangeKind.STATUS,
            requested_value=MemberStatus.PAUSED.value,
        )


@pytest.mark.parametrize("kind", list(ChangeKind))
def test_administrator_target_is_denied(kind: ChangeKind) -> None:
    with pytest.raises(AuthorizationError):
        change_member(
            actor=member(role=MemberRole.ADMINISTRATOR),
            target=member(role=MemberRole.ADMINISTRATOR),
            kind=kind,
            requested_value="paused",
        )


@pytest.mark.parametrize("kind", list(ChangeKind))
def test_superadministrator_target_is_denied(kind: ChangeKind) -> None:
    with pytest.raises(AuthorizationError):
        change_member(
            actor=member(
                role=MemberRole.ADMINISTRATOR,
                permissions=frozenset({SUPERADMINISTRATOR_PERMISSION}),
            ),
            target=member(
                role=MemberRole.ADMINISTRATOR,
                permissions=frozenset({SUPERADMINISTRATOR_PERMISSION}),
            ),
            kind=kind,
            requested_value=MemberRole.MEMBER.value
            if kind is ChangeKind.ROLE
            else MemberStatus.PAUSED.value,
        )


@pytest.mark.parametrize("kind", list(ChangeKind))
def test_unknown_requested_value_is_denied(kind: ChangeKind) -> None:
    with pytest.raises(AuthorizationError):
        change_member(
            actor=member(role=MemberRole.ADMINISTRATOR),
            target=member(),
            kind=kind,
            requested_value="owner",
        )


def test_owner_can_appoint_with_exact_individual_permissions() -> None:
    owner = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset({SUPERADMINISTRATOR_PERMISSION}),
    )
    target = member(role=MemberRole.MODERATOR)

    changed = assign_administrator(
        actor=owner,
        target=target,
        permissions=frozenset({DISPUTE_MODERATION_PERMISSION, ADMINISTRATOR_MANAGEMENT_PERMISSION}),
        appointed_at=datetime.datetime.now(datetime.UTC),
    )

    assert changed.role is MemberRole.ADMINISTRATOR
    assert changed.permissions == frozenset(
        {"member_read", DISPUTE_MODERATION_PERMISSION, ADMINISTRATOR_MANAGEMENT_PERMISSION}
    )
    assert changed.administrator_appointed_by_member_id == owner.id


def test_community_task_permissions_are_opt_in_except_for_owner() -> None:
    ordinary = member(role=MemberRole.ADMINISTRATOR, permissions=ADMINISTRATOR_PERMISSIONS)
    creator = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset({COMMUNITY_TASK_CREATE_PERMISSION}),
    )
    reviewer = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset({COMMUNITY_TASK_REVIEW_PERMISSION}),
    )
    owner = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset({SUPERADMINISTRATOR_PERMISSION}),
    )

    assert not can_create_community_task(ordinary)
    assert not can_review_community_task(ordinary)
    assert can_create_community_task(creator)
    assert not can_review_community_task(creator)
    assert not can_create_community_task(reviewer)
    assert can_review_community_task(reviewer)
    assert can_create_community_task(owner)
    assert can_review_community_task(owner)


def test_delegated_manager_can_grant_only_own_ordinary_rights() -> None:
    manager = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset(
            {
                ADMINISTRATOR_MANAGEMENT_PERMISSION,
                DISPUTE_MODERATION_PERMISSION,
                MEMBER_INVITATION_PERMISSION,
            }
        ),
    )
    target = member()

    with pytest.raises(AuthorizationError):
        assign_administrator(
            actor=manager,
            target=target,
            permissions=frozenset({ADMINISTRATOR_MANAGEMENT_PERMISSION}),
            appointed_at=datetime.datetime.now(datetime.UTC),
        )
    with pytest.raises(AuthorizationError):
        assign_administrator(
            actor=manager,
            target=target,
            permissions=frozenset({MEMBER_BLOCKING_PERMISSION}),
            appointed_at=datetime.datetime.now(datetime.UTC),
        )

    appointed = assign_administrator(
        actor=manager,
        target=target,
        permissions=frozenset({DISPUTE_MODERATION_PERMISSION, MEMBER_INVITATION_PERMISSION}),
        appointed_at=datetime.datetime.now(datetime.UTC),
    )
    assert appointed.administrator_appointed_by_member_id == manager.id


def test_manager_can_edit_only_their_appointee_and_owner_is_immutable() -> None:
    manager = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset({ADMINISTRATOR_MANAGEMENT_PERMISSION, DISPUTE_MODERATION_PERMISSION}),
    )
    appointed = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset({DISPUTE_MODERATION_PERMISSION}),
    )
    appointed = replace(appointed, administrator_appointed_by_member_id=manager.id)
    foreign = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset({DISPUTE_MODERATION_PERMISSION}),
    )
    owner = member(
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset({SUPERADMINISTRATOR_PERMISSION}),
    )

    assert can_edit_administrator(actor=manager, target=appointed)
    assert not can_edit_administrator(actor=manager, target=foreign)
    assert not can_edit_administrator(actor=manager, target=owner)
    updated = update_administrator_permissions(
        actor=manager,
        target=appointed,
        permissions=frozenset({DISPUTE_MODERATION_PERMISSION}),
    )
    demoted = demote_administrator(actor=manager, target=updated)
    assert demoted.role is MemberRole.MEMBER
    assert demoted.permissions == frozenset()
    assert demoted.administrator_appointed_by_member_id is None
