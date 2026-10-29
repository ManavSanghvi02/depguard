"""One parser per lockfile type. Each takes the file's bytes and returns a ParsedService."""

import re
from pathlib import PurePosixPath

from depguard.parsers.models import LockfileType

REQUIREMENTS_NAME = re.compile(r"requirements[^/]*\.txt")


def lockfile_type(path: str) -> LockfileType | None:
    """Which parser handles a repo path, or None if it isn't a supported lockfile."""
    file = PurePosixPath(path)
    name = file.name
    if name == "package-lock.json":
        return "package-lock"
    if name == "poetry.lock":
        return "poetry-lock"
    if name == "uv.lock":
        return "uv-lock"
    if REQUIREMENTS_NAME.fullmatch(name):
        return "requirements"
    # A requirements/ folder (e.g. requirements/base.txt), at any depth. .in files aren't pinned.
    if file.suffix == ".txt" and "requirements" in file.parts[:-1]:
        return "requirements"
    return None
