"""uv.lock.

The project itself (and each workspace member) is a package with an `editable` or `virtual` source.
Its `dependencies` and `optional-dependencies` are direct production dependencies; its
`dev-dependencies` and the workspace's `[manifest.dependency-groups]` are direct dev dependencies.
uv.lock has no per-package dev flag, so a package is dev when no production dependency
leads to it.
"""

from collections import defaultdict
from typing import Any

from depguard.parsers.common import load_toml, sorted_edges
from depguard.parsers.models import Entry, ParsedService, ParseError, SkippedPackage
from depguard.parsers.names import normalize_pypi_name, pypi_key

LOCAL_PROJECT_SOURCES = {"editable", "virtual"}


def parse_uv_lock(content: bytes, lockfile_path: str) -> ParsedService:
    data = load_toml(content)
    packages = data.get("package", [])
    if not isinstance(packages, list):
        raise ParseError("invalid uv.lock: 'package' is not a list")

    entries: dict[str, Entry] = {}
    keys_by_name: dict[str, list[str]] = defaultdict(list)
    local_projects: list[dict[str, Any]] = []
    registry_packages: list[tuple[str, dict[str, Any]]] = []
    skipped: list[SkippedPackage] = []

    for package in packages:
        if not isinstance(package, dict) or not package.get("name"):
            raise ParseError("invalid uv.lock: package without a name")
        name = normalize_pypi_name(str(package["name"]))
        source = package.get("source") or {}
        if LOCAL_PROJECT_SOURCES & source.keys():
            local_projects.append(package)
            continue
        if "registry" not in source:  # git, url, path or directory
            spec = str(next(iter(source.values()), ""))
            skipped.append(SkippedPackage(name=name, spec=spec, reason="not_from_registry"))
            continue
        if not package.get("version"):
            skipped.append(SkippedPackage(name=name, spec="", reason="version_unknown"))
            continue
        key = pypi_key(name, str(package["version"]))
        entries[key] = Entry(
            key=key, name=name, version=str(package["version"]), dev=False, direct=False
        )
        keys_by_name[name].append(key)
        registry_packages.append((key, package))

    def targets(ref: Any) -> list[str]:
        """Keys a dependency reference points to (`version` is set if a name has several)."""
        if not isinstance(ref, dict) or "name" not in ref:
            return []
        name = normalize_pypi_name(str(ref["name"]))
        if "version" in ref:
            key = pypi_key(name, str(ref["version"]))
            return [key] if key in entries else []
        return keys_by_name.get(name, [])

    extras: dict[str, dict[str, list[Any]]] = {
        key: package.get("optional-dependencies", {}) for key, package in registry_packages
    }
    edges: set[tuple[str | None, str]] = set()
    expanded_extras: set[tuple[str, str]] = set()  # extras can refer to each other in a loop

    def add_edges(parent: str | None, refs: list[Any]) -> list[str]:
        children: list[str] = []
        for ref in refs:
            for child in targets(ref):
                edges.add((parent, child))
                children.append(child)
                # `fastapi[standard]` also pulls in fastapi's "standard" extra.
                for extra in ref.get("extra", []):
                    if (child, extra) not in expanded_extras:
                        expanded_extras.add((child, extra))
                        add_edges(child, extras.get(child, {}).get(extra, []))
        return children

    for key, package in registry_packages:
        add_edges(key, package.get("dependencies", []))

    prod_roots: list[str] = []
    for project in local_projects:
        prod_roots += add_edges(None, project.get("dependencies", []))
        for refs in project.get("optional-dependencies", {}).values():
            prod_roots += add_edges(None, refs)
        for refs in project.get("dev-dependencies", {}).values():
            add_edges(None, refs)
    for requirements in data.get("manifest", {}).get("dependency-groups", {}).values():
        add_edges(None, requirements)

    prod = reachable(prod_roots, edges)
    direct = {child for parent, child in edges if parent is None}
    return ParsedService(
        lockfile_path=lockfile_path,
        lockfile_type="uv-lock",
        ecosystem="PyPI",
        entries=[
            e.model_copy(update={"direct": e.key in direct, "dev": e.key not in prod})
            for e in entries.values()
        ],
        edges=sorted_edges(edges),
        skipped=skipped,
    )


def reachable(starts: list[str], edges: set[tuple[str | None, str]]) -> set[str]:
    children: dict[str, list[str]] = defaultdict(list)
    for parent, child in edges:
        if parent is not None:
            children[parent].append(child)
    seen: set[str] = set()
    stack = list(starts)
    while stack:
        key = stack.pop()
        if key not in seen:
            seen.add(key)
            stack.extend(children[key])
    return seen
