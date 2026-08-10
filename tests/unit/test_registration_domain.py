from __future__ import annotations

from uuid import uuid4

import pytest

from community_bot.domain.members import Member, MemberRole, MemberStatus
from community_bot.domain.registration import (
    ProfileField,
    RegistrationError,
    RegistrationStep,
    normalize_profile_value,
    normalize_registration_answer,
    require_invitation_manager,
    require_registration_moderator,
)


def member(*, role: MemberRole, status: MemberStatus = MemberStatus.ACTIVE) -> Member:
    return Member(id=uuid4(), telegram_user_id=1, role=role, status=status)


def test_registration_answers_follow_the_complete_order() -> None:
    cases = [
        (RegistrationStep.CONSENT, "да", "consent", RegistrationStep.DISPLAY_NAME),
        (RegistrationStep.DISPLAY_NAME, "  Анна  ", "display_name", RegistrationStep.CITY),
        (RegistrationStep.CITY, "Москва", "city", RegistrationStep.TIMEZONE),
        (RegistrationStep.TIMEZONE, "Europe/Moscow", "timezone", RegistrationStep.SHORT_BIO),
        (
            RegistrationStep.SHORT_BIO,
            "Помогаю запускать продукты",
            "short_bio",
            RegistrationStep.CURRENT_GOAL,
        ),
        (
            RegistrationStep.CURRENT_GOAL,
            "Найти команду",
            "current_goal",
            RegistrationStep.HELP_CATEGORIES,
        ),
        (
            RegistrationStep.HELP_CATEGORIES,
            "Продукт, продукт, Тестирование",
            "help_categories",
            RegistrationStep.SKILL_TAGS,
        ),
        (
            RegistrationStep.SKILL_TAGS,
            "Python, SQL",
            "skill_tags",
            RegistrationStep.AVAILABILITY,
        ),
        (
            RegistrationStep.AVAILABILITY,
            "Два часа в неделю",
            "availability",
            RegistrationStep.PREVIEW,
        ),
    ]

    for step, raw_value, field, next_step in cases:
        answer = normalize_registration_answer(step, raw_value)
        assert answer.field == field
        assert answer.next_step is next_step


def test_profile_lists_are_trimmed_deduplicated_and_bounded() -> None:
    assert normalize_profile_value(
        ProfileField.SKILL_TAGS,
        " Python, python , SQL ",
    ) == ("Python", "SQL")
    with pytest.raises(RegistrationError):
        normalize_profile_value(ProfileField.HELP_CATEGORIES, "")
    with pytest.raises(RegistrationError):
        normalize_profile_value(ProfileField.TIMEZONE, "Mars/Olympus")


def test_invitation_and_moderation_authorization_are_distinct() -> None:
    administrator = member(role=MemberRole.ADMINISTRATOR)
    moderator = member(role=MemberRole.MODERATOR)
    regular = member(role=MemberRole.MEMBER)

    require_invitation_manager(administrator)
    require_registration_moderator(administrator)
    require_registration_moderator(moderator)
    with pytest.raises(PermissionError):
        require_invitation_manager(moderator)
    with pytest.raises(PermissionError):
        require_registration_moderator(regular)
    with pytest.raises(PermissionError):
        require_registration_moderator(
            member(role=MemberRole.ADMINISTRATOR, status=MemberStatus.PAUSED)
        )
