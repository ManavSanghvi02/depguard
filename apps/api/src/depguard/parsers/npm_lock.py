"""package-lock.json (lockfileVersion 2 and 3).

Only the "packages" map is read. Its keys are install paths ("" = the project itself,
"node_modules/a/node_modules/b" = a copy of b nested under a). Keys without "node_modules/"
are workspace folders: local code, not registry packages.
"""

import json
from typing import Any

from depguard.parsers.common import sorted_edges
from depguard.parsers.models import Entry, ParsedService, ParseError, SkippedPackage

DEPENDENCY_FIELDS = ("dependencies", "optionalDependencies", "peerDependencies")
# Only the project and its workspaces install their devDependencies; for packages they're ignored.
TOP_LEVEL_FIELDS = (*DEPENDENCY_FIELDS, "devDependencies")
NOT_REGISTRY_PREFIXES = ("git+", "git:", "github:", "file:", "link:")


def name_from_path(path: str) -> str:
    # "node_modules/a/node_modules/@scope/b" -> "@scope/b"
    return path.rsplit("node_modules/", 1)[-1]


def parent_folder(path: str) -> str:
    # "node_modules/a/node_modules/b" -> "node_modules/a"
    # "node_modules/a" or "packages/x" -> "" (the root)
    index = path.rfind("/node_modules/")
    return path[:index] if index != -1 else ""


def resolve(packages: dict[str, Any], from_path: str, dep_name: str) -> str | None:
    """Where npm finds dep_name for from_path: its own node_modules, then each parent's."""
    folder = from_path
    while True:
        candidate = f"{folder}/node_modules/{dep_name}" if folder else f"node_modules/{dep_name}"
        if candidate in packages:
            return candidate
        if not folder:
            return None
        folder = parent_folder(folder)


def is_from_registry(resolved: str | None) -> bool:
    # Bundled packages and some older locks have no "resolved"; those came from the registry.
    if not resolved:
        return True
    return not resolved.startswith(NOT_REGISTRY_PREFIXES) and "://" in resolved


def parse_package_lock(content: bytes, lockfile_path: str) -> ParsedService:
    try:
        data = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ParseError(f"invalid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ParseError("invalid package-lock.json: not a JSON object")

    version = data.get("lockfileVersion")
    if version not in (2, 3):
        raise ParseError(
            f"unsupported lockfileVersion {version}; regenerate the lockfile with npm 7 or newer"
        )
    packages = data.get("packages")
    if not isinstance(packages, dict):
        raise ParseError("invalid package-lock.json: missing 'packages'")

    entries: dict[str, Entry] = {}
    skipped: list[SkippedPackage] = []
    top_level = [""]  # the project and its workspace folders

    for path, info in packages.items():
        if path == "" or not isinstance(info, dict) or info.get("link"):
            continue  # links point at workspace folders, which are listed separately
        if "node_modules/" not in path:
            top_level.append(path)
            continue
        name = info.get("name") or name_from_path(path)  # "name" is set for aliases (npm:real@1)
        resolved = info.get("resolved")
        if not is_from_registry(resolved):
            skipped.append(
                SkippedPackage(name=name, spec=str(resolved), reason="not_from_registry")
            )
            continue
        if not info.get("version"):
            skipped.append(SkippedPackage(name=name, spec="", reason="version_unknown"))
            continue
        entries[path] = Entry(
            key=path,
            name=name,
            version=str(info["version"]),
            # devOptional = also needed in production (as an optional dependency).
            dev=bool(info.get("dev")),
            direct=False,
        )

    edges: set[tuple[str | None, str]] = set()
    for path in top_level:
        for dep in _dependency_names(packages.get(path, {}), TOP_LEVEL_FIELDS):
            target = resolve(packages, path, dep)
            if target in entries:
                edges.add((None, target))
    for path in entries:
        for dep in _dependency_names(packages[path], DEPENDENCY_FIELDS):
            target = resolve(packages, path, dep)
            # A missing optional or peer dependency simply has no edge.
            if target in entries:
                edges.add((path, target))

    direct = {child for parent, child in edges if parent is None}
    return ParsedService(
        lockfile_path=lockfile_path,
        lockfile_type="package-lock",
        ecosystem="npm",
        entries=[e.model_copy(update={"direct": e.key in direct}) for e in entries.values()],
        edges=sorted_edges(edges),
        skipped=skipped,
    )


def _dependency_names(info: Any, fields: tuple[str, ...]) -> set[str]:
    names: set[str] = set()
    if isinstance(info, dict):
        for field in fields:
            deps = info.get(field)
            if isinstance(deps, dict):
                names.update(deps)
    return names
