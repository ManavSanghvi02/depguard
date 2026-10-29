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
from depguard.parsers.poetry_constraints import Locked, pick_versions

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
    locked_by_name: dict[str, list[Locked]] = defaultdict(list)
    dependencies: dict[str, dict[str, Any]] = {}  # parent key -> {dependency name: constraint}
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
        version = str(package["version"])
        key = pypi_key(name, version)
        entries[key] = Entry(key=key, name=name, version=version, dev=is_dev(package), direct=False)
        python_versions = str(package.get("python-versions", "*"))
        locked_by_name[name].append(
            Locked(key=key, version=version, python_versions=python_versions)
        )
        package_dependencies = table(package.get("dependencies", {}), "poetry.lock dependencies")
        dependencies[key] = {
            normalize_pypi_name(dep): spec for dep, spec in package_dependencies.items()
        }

    # Dependencies name a package, not a version; pick_versions chooses which locked version(s).
    edges: dict[tuple[str | None, str], bool] = {}  # (parent, child) -> ambiguous

    def add_edges(parent: str | None, name: str, spec: Any) -> None:
        for child, ambiguous in pick_versions(spec, locked_by_name.get(name, [])).items():
            edges[(parent, child)] = edges.get((parent, child), True) and ambiguous

    for parent, specs in dependencies.items():
        for name, spec in specs.items():
            add_edges(parent, name, spec)

    warnings: list[str] = []
    if pyproject is not None:
        for name, direct_specs in direct_dependency_constraints(load_toml(pyproject)).items():
            add_edges(None, name, direct_specs)
    else:
        # Fallback: a package nothing depends on must have been asked for directly.
        warnings.append("pyproject.toml not found next to poetry.lock; direct dependencies guessed")
        has_parent = {child for _, child in edges}
        edges.update({(None, key): False for key in entries if key not in has_parent})

    direct = {child for parent, child in edges if parent is None}
    return ParsedService(
        lockfile_path=lockfile_path,
        lockfile_type="poetry-lock",
        ecosystem="PyPI",
        entries=[e.model_copy(update={"direct": e.key in direct}) for e in entries.values()],
        edges=sorted_edges(set(edges), {edge for edge, ambiguous in edges.items() if ambiguous}),
        skipped=skipped,
        warnings=warnings,
    )


def direct_dependency_constraints(pyproject: dict[str, Any]) -> dict[str, list[Any]]:
    """Every package the project asks for itself (main, extras, all groups, any layout), with
    its constraints in poetry.lock's shape, so pick_versions can read both."""
    found: dict[str, list[Any]] = defaultdict(list)
    project = table(pyproject.get("project", {}), "pyproject [project]")
    requirement_lists: list[Any] = [project.get("dependencies", [])]
    requirement_lists += list(table(project.get("optional-dependencies", {}), "extras").values())
    requirement_lists += list(table(pyproject.get("dependency-groups", {}), "groups").values())
    for requirements in requirement_lists:
        if not isinstance(requirements, list):
            raise ParseError("invalid pyproject.toml: a dependency list is not a list")
        for line in requirements:
            if isinstance(line, str):  # dependency-groups may also hold {include-group = ...}
                try:
                    requirement = Requirement(line)
                except InvalidRequirement:
                    continue
                found[normalize_pypi_name(requirement.name)].append(
                    {
                        "version": str(requirement.specifier) or "*",
                        "markers": str(requirement.marker or ""),
                    }
                )

    poetry = table(table(pyproject.get("tool", {}), "[tool]").get("poetry", {}), "[tool.poetry]")
    tables = [poetry.get("dependencies", {}), poetry.get("dev-dependencies", {})]
    groups = table(poetry.get("group", {}), "[tool.poetry.group]").values()
    tables += [table(group, "a Poetry group").get("dependencies", {}) for group in groups]
    for dependency_table in tables:
        for name, spec in table(dependency_table, "Poetry dependencies").items():
            if name != "python":
                found[normalize_pypi_name(name)] += spec if isinstance(spec, list) else [spec]
    return dict(found)


def table(value: Any, where: str) -> dict[str, Any]:
    """The files come from other people's repos: a wrong shape is a ParseError, not a crash."""
    if not isinstance(value, dict):
        raise ParseError(f"invalid {where}: expected a table")
    return value
