"""Strict loading of non-secret product configuration candidates."""

from __future__ import annotations

import json
import re
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from community_bot.domain.economy import (
    LevelDefinition,
    ProductConfigCandidate,
    ProductConfigError,
)

if TYPE_CHECKING:
    from pathlib import Path

_CYRILLIC_PATTERN = re.compile("[\u0410-\u044f\u0401\u0451]")


class LevelCandidateModel(BaseModel):
    """Strict serializable level candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    level_number: int = Field(ge=1)
    experience_required: int = Field(ge=0)
    display_name: str = Field(min_length=1)
    description: str | None = None
    level_up_message: str | None = None
    permissions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        """Require a meaningful Russian display name."""
        normalized = value.strip()
        if not normalized or _CYRILLIC_PATTERN.search(normalized) is None:
            message = "Level display name must contain Cyrillic text."
            raise ValueError(message)
        return normalized

    @field_validator("description", "level_up_message")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Normalize optional user-facing text."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProductConfigCandidateModel(BaseModel):
    """Strict schema-v1 product configuration candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    config_version: int = Field(gt=0)
    levels: list[LevelCandidateModel]
    interaction_alert_threshold: int = Field(ge=0)
    interaction_alert_window_days: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_level_scale(self) -> ProductConfigCandidateModel:
        """Require exactly ten sequential levels with increasing thresholds."""
        ordered = sorted(self.levels, key=lambda level: level.level_number)
        if [level.level_number for level in ordered] != list(range(1, 11)):
            message = "Product configuration must contain levels 1 through 10 exactly once."
            raise ValueError(message)
        thresholds = [level.experience_required for level in ordered]
        if thresholds[0] != 0:
            message = "Level 1 must start at zero experience."
            raise ValueError(message)
        if any(current >= following for current, following in pairwise(thresholds)):
            message = "Level experience thresholds must be strictly increasing."
            raise ValueError(message)
        return self

    def to_domain(self) -> ProductConfigCandidate:
        """Convert validated transport data to immutable domain values."""
        return ProductConfigCandidate(
            schema_version=self.schema_version,
            config_version=self.config_version,
            levels=tuple(
                LevelDefinition(
                    level_number=level.level_number,
                    experience_required=level.experience_required,
                    display_name=level.display_name,
                    description=level.description,
                    level_up_message=level.level_up_message,
                    permissions=level.permissions,
                )
                for level in sorted(self.levels, key=lambda item: item.level_number)
            ),
            interaction_alert_threshold=self.interaction_alert_threshold,
            interaction_alert_window_days=self.interaction_alert_window_days,
        )


def load_product_config_candidate(path: Path) -> ProductConfigCandidate:
    """Load one UTF-8 JSON candidate and reject invalid schema before database work."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        model = ProductConfigCandidateModel.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        message = f"Product configuration candidate is invalid: {path}"
        raise ProductConfigError(message) from error
    return model.to_domain()
