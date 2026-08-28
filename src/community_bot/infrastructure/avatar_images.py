"""Validate and normalize untrusted profile images before persistence."""

from __future__ import annotations

import warnings
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

_AVATAR_EDGE_PX = 512
_MIN_SOURCE_EDGE_PX = 128
_MAX_SOURCE_PIXELS = 24_000_000
_MAX_NORMALIZED_BYTES = 512 * 1024


class InvalidProfileAvatarError(ValueError):
    """The supplied bytes cannot become a safe profile avatar."""


def normalize_profile_avatar(content: bytes) -> bytes:
    """Return a metadata-free square JPEG with bounded dimensions and size."""
    if not content:
        raise InvalidProfileAvatarError
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as source:
                if source.width * source.height > _MAX_SOURCE_PIXELS:
                    raise InvalidProfileAvatarError
                source.load()
                image = ImageOps.exif_transpose(source)
                if min(image.size) < _MIN_SOURCE_EDGE_PX:
                    raise InvalidProfileAvatarError
                normalized = ImageOps.fit(
                    image.convert("RGB"),
                    (_AVATAR_EDGE_PX, _AVATAR_EDGE_PX),
                    method=Image.Resampling.LANCZOS,
                )
                output = BytesIO()
                normalized.save(
                    output,
                    format="JPEG",
                    quality=86,
                    optimize=True,
                    progressive=True,
                )
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise InvalidProfileAvatarError from error
    except (OSError, UnidentifiedImageError) as error:
        raise InvalidProfileAvatarError from error
    result = output.getvalue()
    if not result or len(result) > _MAX_NORMALIZED_BYTES:
        raise InvalidProfileAvatarError
    return result
