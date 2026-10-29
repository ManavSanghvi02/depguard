"""Which locked versions a Poetry dependency points to.

poetry.lock names a dependency's package but not its version. When the lock holds several
versions of that package (usually one per Python version), the dependency's version constraint
and markers normally pick one. Every narrowing step is skipped if it would leave nothing, so an
edge is never lost; if more than one version is still left, the edges are marked ambiguous.

Markers are checked against a fixed set of test environments (Python 2.7 and 3.6–3.14 on Linux,
Windows and macOS, with each extra the marker names), so the result never depends on the machine
DepGuard runs on.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from packaging.markers import InvalidMarker, Marker, UndefinedComparison, UndefinedEnvironmentName
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

# Old Pythons too: a lock can hold a version kept only for them, and dropping it would hide it.
TEST_PYTHONS = ["2.7"] + [f"3.{minor}" for minor in range(6, 15)]
EXTRA_NAME = re.compile(r"""extra\s*==\s*["']([^"']+)["']""")
TEST_PLATFORMS = [
    {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix"},
    {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt"},
    {"sys_platform": "darwin", "platform_system": "Darwin", "os_name": "posix"},
]


@dataclass(frozen=True)
class Locked:
    key: str
    version: str
    python_versions: str  # the package's own "python-versions", e.g. ">=3.9" or "*"


@dataclass(frozen=True)
class Constraint:
    version: str = "*"
    markers: str = ""
    python: str = "*"  # older Poetry wrote `python = "<3.8"` instead of a marker


def constraints(spec: Any) -> list[Constraint]:
    """A dependency is a string, a table, or a list of tables (one per marker branch)."""
    result = []
    for item in spec if isinstance(spec, list) else [spec]:
        if isinstance(item, str):
            result.append(Constraint(version=item))
        elif isinstance(item, dict):
            result.append(
                Constraint(
                    version=str(item.get("version", "*")),
                    markers=str(item.get("markers", "")),
                    python=str(item.get("python", "*")),
                )
            )
    return result or [Constraint()]


def pick_versions(spec: Any, candidates: list[Locked]) -> dict[str, bool]:
    """The locked keys this dependency points to, each with True if the choice is ambiguous.

    Different marker branches choosing different versions (numpy<2 on old Pythons, numpy>=2 on
    new ones) are both real, so neither edge is ambiguous.
    """
    picked: dict[str, bool] = {}
    for constraint in constraints(spec):
        chosen = resolve(constraint, candidates)
        for locked in chosen:
            picked[locked.key] = picked.get(locked.key, True) and len(chosen) > 1
    return picked


def resolve(constraint: Constraint, candidates: list[Locked]) -> list[Locked]:
    chosen = narrow(candidates, lambda c: allows(constraint.version, c.version))
    return narrow(chosen, lambda c: in_some_environment(constraint, c))


def narrow(candidates: list[Locked], keep: Callable[[Locked], bool]) -> list[Locked]:
    return [c for c in candidates if keep(c)] or candidates


def allows(spec: str, version: str) -> bool:
    """Does a PEP 440 constraint allow this version? True if we can't tell (Poetry's ^1.2)."""
    spec = spec.strip()
    if spec in ("", "*"):
        return True
    try:
        if spec[0] not in "<>=!~":
            spec = f"=={spec}"  # Poetry writes a bare version for an exact pin
        return SpecifierSet(spec).contains(Version(version), prereleases=True)
    except (InvalidSpecifier, InvalidVersion):
        return True


def in_some_environment(constraint: Constraint, locked: Locked) -> bool:
    for python in TEST_PYTHONS:
        if not (allows(locked.python_versions, python) and allows(constraint.python, python)):
            continue
        for platform in TEST_PLATFORMS:
            if marker_true(constraint.markers, {**platform, "python_version": python}):
                return True
    return False


def marker_true(markers: str, environment: dict[str, str]) -> bool:
    if not markers:
        return True
    python = environment["python_version"]
    full_environment = {
        **environment,
        "python_full_version": f"{python}.0",
        "implementation_name": "cpython",
        "implementation_version": f"{python}.0",
        "platform_python_implementation": "CPython",
        "platform_machine": "x86_64",
        "platform_release": "",
        "platform_version": "",
    }
    try:
        marker = Marker(markers)
        # `extra == "socks"` is true only when that extra is installed: try with each one named.
        extras = [""] + EXTRA_NAME.findall(markers)
        return any(marker.evaluate({**full_environment, "extra": extra}) for extra in extras)
    except (InvalidMarker, UndefinedComparison, UndefinedEnvironmentName):
        return True
