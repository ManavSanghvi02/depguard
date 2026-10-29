"""Version logic per ecosystem (npm: SemVer, PyPI: PEP 440). Deterministic code, never the LLM.

`first_fixed` reads an OSV advisory's `affected` list:
https://ossf.github.io/osv-schema/#affectedranges-field
"""

from collections.abc import Callable, Iterable
from typing import Any

import semver
from packaging.version import Version

from depguard.parsers.models import Ecosystem
from depguard.parsers.names import normalize_pypi_name
from depguard.versions import npm, pypi


def parse(ecosystem: Ecosystem, version: str) -> semver.Version | Version | None:
    return npm.parse(version) if ecosystem == "npm" else pypi.parse(version)


def normalize(ecosystem: Ecosystem, version: str) -> str:
    """One spelling per version, so equal versions match as text. Unparseable ones stay as-is."""
    return npm.normalize(version) if ecosystem == "npm" else pypi.normalize(version)


def is_major_bump(ecosystem: Ecosystem, installed: str, fixed: str) -> bool:
    old, new = parse(ecosystem, installed), parse(ecosystem, fixed)
    if isinstance(old, semver.Version) and isinstance(new, semver.Version):
        return npm.is_major_bump(old, new)
    if isinstance(old, Version) and isinstance(new, Version):
        return pypi.is_major_bump(old, new)
    return False  # unparseable: no warning rather than a wrong one


def first_fixed(
    affected: list[dict[str, Any]], ecosystem: Ecosystem, name: str, installed: str
) -> str | None:
    """The smallest fixed version above the installed one, as the advisory spells it.

    Only this package's ranges count (an advisory can list lodash and lodash-es). None if no
    range that affects the installed version has a fix (e.g. only `last_affected`).
    """
    if ecosystem == "npm":
        npm_version = npm.parse(installed)
        if npm_version is None:
            return None
        return _first_fixed(affected, ecosystem, name, npm_version, npm.parse)
    pypi_version = pypi.parse(installed)
    if pypi_version is None:
        return None
    return _first_fixed(affected, ecosystem, name, pypi_version, pypi.parse)


# One function for both ecosystems; mypy checks it once per version type.
def _first_fixed[V: (semver.Version, Version)](
    affected: list[dict[str, Any]],
    ecosystem: Ecosystem,
    name: str,
    current: V,
    parse_version: Callable[[str], V | None],
) -> str | None:
    fixes: list[tuple[V, str]] = []
    for item in affected:
        package = item.get("package", {})
        if package.get("ecosystem") != ecosystem or not same_name(
            ecosystem, package.get("name", ""), name
        ):
            continue
        for version_range in item.get("ranges", []):
            if version_range.get("type") not in ("SEMVER", "ECOSYSTEM"):
                continue  # GIT ranges are commit hashes
            fix = range_fix(version_range.get("events", []), current, parse_version)
            if fix is not None:
                fixes.append(fix)
    return min(fixes, key=lambda fix: fix[0])[1] if fixes else None


def same_name(ecosystem: Ecosystem, a: str, b: str) -> bool:
    if ecosystem == "PyPI":
        return normalize_pypi_name(a) == normalize_pypi_name(b)
    return a == b


def range_fix[V: (semver.Version, Version)](
    events: list[dict[str, str]], current: V, parse_version: Callable[[str], V | None]
) -> tuple[V, str] | None:
    """Walk the range's events in version order. If the installed version is affected and the next
    event above it is `fixed`, that's this range's fix."""
    lowest: list[tuple[str, str]] = []  # introduced "0": below every version
    points: list[tuple[V, str, str]] = []  # (version, kind, text)
    for event in events:
        for kind in ("introduced", "fixed", "last_affected"):
            if kind not in event:
                continue
            text = event[kind]
            if text == "0":
                lowest.append((kind, text))
                continue
            version = parse_version(text)
            if version is None:
                return None  # an unparseable bound: we can't place the installed version
            points.append((version, kind, text))
    points.sort(key=lambda point: point[0])

    affected = any(kind == "introduced" for kind, _ in lowest)
    for version, kind, text in points:
        if version > current:
            # The first event above the installed version decides.
            return (version, text) if affected and kind == "fixed" else None
        if kind == "introduced":
            affected = True
        elif kind == "fixed":
            affected = False  # fixed at or below the installed version
        elif version == current:
            return None  # last_affected is the installed version: affected, no known fix
        else:
            affected = False
    return None


def highest(ecosystem: Ecosystem, candidates: Iterable[str]) -> str | None:
    """The highest version as spelled; unparseable ones are ignored. None if none parse."""
    if ecosystem == "npm":
        return _highest(candidates, npm.parse)
    return _highest(candidates, pypi.parse)


def _highest[V: (semver.Version, Version)](
    candidates: Iterable[str], parse_version: Callable[[str], V | None]
) -> str | None:
    parsed = [(version, text) for text in candidates if (version := parse_version(text))]
    return max(parsed, key=lambda pair: pair[0])[1] if parsed else None
