from __future__ import annotations

from uuid import uuid4

import pytest

from community_bot.domain.members import Member, MemberRole, MemberStatus
from community_bot.domain.registration import (
    ProfileField,
    ProfileLinkAction,
    ProfileLinkCommand,
    ProfileListItemLengthError,
    ProfileListSizeError,
    RegistrationError,
    RegistrationStep,
    normalize_profile_link_command,
    normalize_profile_value,
    normalize_registration_answer,
    require_invitation_manager,
    require_registration_moderator,
    resolve_timezone,
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
    with pytest.raises(ProfileListSizeError):
        normalize_profile_value(ProfileField.HELP_CATEGORIES, "")
    with pytest.raises(ProfileListItemLengthError):
        normalize_profile_value(ProfileField.HELP_CATEGORIES, "x" * 81)
    with pytest.raises(RegistrationError):
        normalize_profile_value(ProfileField.TIMEZONE, "Mars/Olympus")


def test_profile_link_commands_normalize_and_reject_unsafe_shapes() -> None:
    created = normalize_profile_link_command(
        ProfileLinkCommand(
            ProfileLinkAction.CREATE, label="  My   site ", url="https://example.com/a#b"
        )
    )
    assert (created.label, created.url, created.link_id) == (
        "My site",
        "https://example.com/a#b",
        None,
    )
    link_id = uuid4()
    assert (
        normalize_profile_link_command(
            ProfileLinkCommand(ProfileLinkAction.DELETE, link_id=link_id)
        ).link_id
        == link_id
    )
    for command in (
        ProfileLinkCommand(
            ProfileLinkAction.CREATE, link_id=link_id, label="x", url="https://x.io"
        ),
        ProfileLinkCommand(ProfileLinkAction.UPDATE, label="x", url="https://x.io"),
        ProfileLinkCommand(ProfileLinkAction.DELETE, link_id=link_id, label="x"),
        ProfileLinkCommand(ProfileLinkAction.CREATE, label="x", url="http://example.com"),
        ProfileLinkCommand(ProfileLinkAction.CREATE, label="x", url="https://u:p@example.com"),
        ProfileLinkCommand(ProfileLinkAction.CREATE, label="x", url="https://example.com/\n"),
        ProfileLinkCommand(ProfileLinkAction.CREATE, label="x" * 33, url="https://example.com"),
        ProfileLinkCommand(
            ProfileLinkAction.CREATE, label="x", url="https://example.com/" + "x" * 2040
        ),
    ):
        with pytest.raises(RegistrationError):
            normalize_profile_link_command(command)


def test_help_categories_accept_human_sized_descriptions() -> None:
    assert normalize_profile_value(
        ProfileField.HELP_CATEGORIES,
        (
            "В вопросах финансов и планирования, работа с криптовалютами, "  # noqa: RUF001 - exact Russian user input.
            "психологические консультации в сфере семьи и личностного роста, "
            "администрирование и общение с клиентами онлайн"  # noqa: RUF001 - exact Russian user input.
        ),
    ) == (
        "В вопросах финансов и планирования",  # noqa: RUF001 - exact Russian user input.
        "работа с криптовалютами",  # noqa: RUF001 - exact Russian user input.
        "психологические консультации в сфере семьи и личностного роста",
        "администрирование и общение с клиентами онлайн",  # noqa: RUF001 - exact Russian user input.
    )


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Москва", "Europe/Moscow"),
        ("Буэнос-Айрес", "America/Argentina/Buenos_Aires"),
        ("Buenos Aires", "America/Argentina/Buenos_Aires"),
        ("South America/Buenos-Aires", "America/Argentina/Buenos_Aires"),
        ("Europe/Moscow", "Europe/Moscow"),
    ],
)
def test_timezone_resolver_accepts_human_city_names(location: str, expected: str) -> None:
    assert resolve_timezone(location) == expected
    assert normalize_profile_value(ProfileField.TIMEZONE, location) == expected


def test_timezone_resolver_does_not_guess_unknown_or_ambiguous_locations() -> None:
    assert resolve_timezone("Совсем Неизвестный Город") is None
    assert resolve_timezone("Mountain") is None
    assert resolve_timezone("Eastern") is None
    assert resolve_timezone("West") is None


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
