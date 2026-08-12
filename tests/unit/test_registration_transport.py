from __future__ import annotations

from community_bot.domain.registration import (
    ProfileListItemLengthError,
    ProfileListSizeError,
    ProfileTextLengthError,
    RegistrationStep,
)
from community_bot.transport.telegram.registration import _STEP_PROMPTS, _friendly_error


def test_registration_prompts_explain_list_limits() -> None:
    assert "до 10 пунктов" in _STEP_PROMPTS[RegistrationStep.HELP_CATEGORIES]
    assert "до 80 символов" in _STEP_PROMPTS[RegistrationStep.HELP_CATEGORIES]
    assert "до 20 навыков" in _STEP_PROMPTS[RegistrationStep.SKILL_TAGS]
    assert "до 50 символов" in _STEP_PROMPTS[RegistrationStep.SKILL_TAGS]


def test_registration_validation_errors_explain_exact_reason() -> None:
    assert _friendly_error(ProfileTextLengthError(label="short bio", minimum=10, maximum=500)) == (
        "Не удалось сохранить данные: длина ответа должна быть от 10 до 500 символов."  # noqa: RUF001 - exact Russian user-facing text.
    )
    assert _friendly_error(ProfileListItemLengthError(maximum_item_length=80)) == (
        "Не удалось сохранить данные: один из пунктов слишком длинный. "  # noqa: RUF001 - exact Russian user-facing text.
        "Максимум 80 символов на пункт."
    )
    assert _friendly_error(ProfileListSizeError(maximum_items=10)) == (
        "Не удалось сохранить данные: укажите от 1 до 10 пунктов через запятую."  # noqa: RUF001 - exact Russian user-facing text.
    )
