"""PyPI versions are PEP 440 (the packaging library): 1.0 == 1.0.0, 2.0.0-rc.1 == 2.0.0rc1."""

from packaging.utils import canonicalize_version
from packaging.version import InvalidVersion, Version


def parse(version: str) -> Version | None:
    try:
        return Version(version)
    except InvalidVersion:
        return None


def normalize(version: str) -> str:
    # One spelling per version, so equal versions match as text (1.0.0 -> 1, 2.0.0-rc.1 -> 2rc1).
    # Invalid versions come back unchanged.
    return canonicalize_version(version, strip_trailing_zero=True)


def is_major_bump(installed: Version, fixed: Version) -> bool:
    return installed.major != fixed.major
