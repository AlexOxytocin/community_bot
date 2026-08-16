"""Report the exact single Alembic head packaged in the release image."""

from __future__ import annotations

import re
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory

_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ERROR_MESSAGE = "Packaged migration graph must have exactly one valid head."


def single_migration_head() -> str:
    """Return the sole valid head from the packaged Alembic graph."""
    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    if len(heads) != 1 or _REVISION_RE.fullmatch(heads[0]) is None:
        raise ValueError(_ERROR_MESSAGE)
    return heads[0]


def main() -> int:
    """Print one packaged head or fail closed without graph details."""
    try:
        head = single_migration_head()
    except Exception:  # noqa: BLE001 - release CLI must expose one safe failure.
        sys.stderr.write(f"{_ERROR_MESSAGE}\n")
        return 1
    sys.stdout.write(f"{head}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
