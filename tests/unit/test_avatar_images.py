from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from community_bot.infrastructure.avatar_images import (
    InvalidProfileAvatarError,
    normalize_profile_avatar,
)


def _jpeg(width: int, height: int, *, exif: bool = False) -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (width, height), (78, 112, 214))
    metadata = Image.Exif()
    if exif:
        metadata[0x010E] = "private profile metadata"
    image.save(output, "JPEG", quality=94, exif=metadata)
    return output.getvalue()


def test_normalize_profile_avatar_is_square_bounded_and_strips_metadata() -> None:
    normalized = normalize_profile_avatar(_jpeg(900, 600, exif=True))

    assert len(normalized) < 512 * 1024
    with Image.open(BytesIO(normalized)) as image:
        assert image.format == "JPEG"
        assert image.size == (512, 512)
        assert not image.getexif()


@pytest.mark.parametrize("content", [b"not-an-image", _jpeg(120, 800)])
def test_normalize_profile_avatar_rejects_invalid_or_too_small_sources(content: bytes) -> None:
    with pytest.raises(InvalidProfileAvatarError):
        normalize_profile_avatar(content)
