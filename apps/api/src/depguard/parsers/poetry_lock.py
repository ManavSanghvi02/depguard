"""poetry.lock, plus the pyproject.toml beside it (the lock doesn't record direct dependencies).

Dev vs. production is read from which fields are present, not from the lock-version (ADR-0002):
`category = "dev"` (older Poetry) or `groups` without "main" (Poetry 2.1+) = dev;
neither = production.
"""

from collections import defaultdict
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement

from depguard.parsers.common import load_toml, sorted_edges
from depguard.parsers.models import Entry, ParsedService, ParseError, SkippedPackage
from depguard.parsers.names import normalize_pypi_name, pypi_key

NOT_REGISTRY_SOURCES = {"git", "directory", "file", "url"}


def is_dev(package: dict[str, Any]) -> bool:
    if package.get("category") == "dev":
        return True
    groups = package.get("groups")
    return isinstance(groups, list) and "main" not in groups


def parse_poetry_lock(
    content: bytes, lockfile_path: str, pyproject: bytes | None = None
) -> ParsedService:
    packages = load_toml(content).get("package", [])
    if not isinstance(packages, list):
        raise ParseError("invalid poetry.lock: 'package' is not a list")

    entries: dict[str, Entry] = {}
    keys_by_name: dict[str, list[str]] = defaultdict(list)
    dependencies: dict[str, list[str]] = {}
    skipped: list[SkippedPackage] = []

    for package in packages:
        if not isinstance(package, dict) or not package.get("name"):
            raise ParseError("invalid poetry.lock: package without a name")
        name = normalize_pypi_name(str(package["name"]))
        source = package.get("source") or {}
        if source.get("type") in NOT_REGISTRY_SOURCES:
            spec = str(source.get("url", source.get("type")))
            skipped.append(SkippedPackage(name=name, spec=spec, reason="not_from_registry"))
            continue
        if not package.get("version"):
            skipped.append(SkippedPackage(name=name, spec="", reason="version_unknown"))
            continue
        key = pypi_key(name, str(package["version"]))
        entries[key] = Entry(
            key=key, name=name, version=str(package["version"]), dev=is_dev(package), direct=False
        )
        keys_by_name[name].append(key)
        dependencies[key] = [normalize_pypi_name(dep) for dep in package.get("dependencies", {})]

    # Dependencies name a package, not a version. If the lock holds two versions of it (one per
    # Python version), we link to both, because the lock doesn't say which one this parent uses.
    edges: set[tuple[str | None, str]] = set()
    for parent, names in dependencies.items():
        for dep in names:
            edges.update((parent, child) for child in keys_by_name.get(dep, []))

    warnings: list[str] = []
    if pyproject is not None:
        direct_names = direct_dependency_names(load_toml(pyproject))
        for dep in direct_names:
            edges.update((None, child) for child in keys_by_name.get(dep, []))
    else:
        # Fallback: a package nothing depends on must have been asked for directly.
        warnings.append("pyproject.toml not found next to poetry.lock; direct dependencies guessed")
        has_parent = {child for _, child in edges}
        edges.update((None, key) for key in entries if key not in has_parent)

    direct = {child for parent, child in edges if parent is None}
    return ParsedService(
        lockfile_path=lockfile_path,
        lockfile_type="poetry-lock",
        ecosystem="PyPI",
        entries=[e.model_copy(update={"direct": e.key in direct}) for e in entries.values()],
        edges=sorted_edges(edges),
        skipped=skipped,
        warnings=warnings,
    )


def direct_dependency_names(pyproject: dict[str, Any]) -> set[str]:
    """Every package the project asks for itself: main, extras and all groups (any layout)."""
    names: set[str] = set()
    project = pyproject.get("project", {})
    requirement_lists: list[Any] = [project.get("dependencies", [])]
    requirement_lists += list(project.get("optional-dependencies", {}).values())
    requirement_lists += list(pyproject.get("dependency-groups", {}).values())
    for requirements in requirement_lists:
        for requirement in requirements:
            if isinstance(
                requirement, str
            ):  # dependency-groups may also hold {include-group = ...}
                try:
                    names.add(normalize_pypi_name(Requirement(requirement).name))
                except InvalidRequirement:
                    continue

    poetry = pyproject.get("tool", {}).get("poetry", {})
    tables = [poetry.get("dependencies", {}), poetry.get("dev-dependencies", {})]
    tables += [group.get("dependencies", {}) for group in poetry.get("group", {}).values()]
    for table in tables:
        names.update(normalize_pypi_name(name) for name in table if name != "python")
    return names
