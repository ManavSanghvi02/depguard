"""npm versions are SemVer 2.0 (python-semver). Build metadata (+abc) doesn't affect order."""

import semver


def parse(version: str) -> semver.Version | None:
    try:
        return semver.Version.parse(version)
    except ValueError:
        return None


def normalize(version: str) -> str:
    parsed = parse(version)
    return str(parsed) if parsed is not None else version


def is_major_bump(installed: semver.Version, fixed: semver.Version) -> bool:
    # npm's caret rule: the first non-zero number is the breaking one (^0.2.4 stops before 0.3.0,
    # ^0.0.1 before 0.0.2).
    if installed.major == 0 and fixed.major == 0:
        if installed.minor == 0 and fixed.minor == 0:
            return installed.patch != fixed.patch
        return installed.minor != fixed.minor
    return installed.major != fixed.major
