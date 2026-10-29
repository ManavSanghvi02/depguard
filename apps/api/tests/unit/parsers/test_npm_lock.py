import json
from pathlib import Path
from typing import Any

import pytest

from depguard.parsers.models import ParsedService, ParseError
from depguard.parsers.npm_lock import parse_package_lock

REAL = Path(__file__).parents[2] / "fixtures" / "real"


def parse(packages: dict[str, Any], version: int = 3) -> ParsedService:
    lock = {"name": "app", "lockfileVersion": version, "packages": packages}
    return parse_package_lock(json.dumps(lock).encode(), "package-lock.json")


def by_key(service: ParsedService) -> dict[str, Any]:
    return {entry.key: entry for entry in service.entries}


def edge_pairs(service: ParsedService) -> set[tuple[str | None, str]]:
    return {(edge.parent_key, edge.child_key) for edge in service.edges}


def test_real_defectdojo_lockfile() -> None:
    content = (REAL / "defectdojo" / "package-lock.json").read_bytes()
    service = parse_package_lock(content, "docs/package-lock.json")
    entries = by_key(service)

    assert len(service.entries) == 318
    assert sum(e.dev for e in service.entries) == 39
    assert sum(e.direct for e in service.entries) == 10  # 8 dependencies + 2 devDependencies
    assert service.skipped == []
    assert entries["node_modules/vite"].dev is True
    assert entries["node_modules/thulite"].direct is True
    # Two copies of picomatch stay apart, and anymatch uses its own nested copy.
    assert entries["node_modules/picomatch"].version == "4.0.7"
    assert entries["node_modules/anymatch/node_modules/picomatch"].version == "2.3.2"
    assert ("node_modules/anymatch", "node_modules/anymatch/node_modules/picomatch") in edge_pairs(
        service
    )
    assert ("node_modules/anymatch", "node_modules/picomatch") not in edge_pairs(service)


def test_lockfile_version_1_is_refused() -> None:
    lock = {"lockfileVersion": 1, "dependencies": {"a": {"version": "1.0.0"}}}

    with pytest.raises(ParseError, match="lockfileVersion 1"):
        parse_package_lock(json.dumps(lock).encode(), "package-lock.json")


def test_invalid_json_is_a_parse_error() -> None:
    with pytest.raises(ParseError, match="invalid JSON"):
        parse_package_lock(b"{not json", "package-lock.json")


def test_v2_legacy_dependencies_section_is_ignored() -> None:
    lock = {
        "lockfileVersion": 2,
        "packages": {"": {"dependencies": {"a": "^1"}}, "node_modules/a": {"version": "1.0.0"}},
        "dependencies": {"ghost": {"version": "9.9.9"}},
    }

    service = parse_package_lock(json.dumps(lock).encode(), "package-lock.json")

    assert [e.name for e in service.entries] == ["a"]


def test_dev_and_dev_optional_flags() -> None:
    service = parse(
        {
            "": {"devDependencies": {"d": "1"}, "optionalDependencies": {"o": "1"}},
            "node_modules/d": {"version": "1.0.0", "dev": True},
            "node_modules/o": {"version": "1.0.0", "optional": True},
            "node_modules/both": {"version": "1.0.0", "devOptional": True},
        }
    )
    entries = by_key(service)

    assert entries["node_modules/d"].dev is True
    assert entries["node_modules/o"].dev is False
    # devOptional = also needed in production as an optional dependency -> production.
    assert entries["node_modules/both"].dev is False


def test_scoped_and_aliased_names() -> None:
    service = parse(
        {
            "": {"dependencies": {"@scope/pkg": "1", "alias": "npm:real@2"}},
            "node_modules/@scope/pkg": {"version": "1.0.0"},
            "node_modules/alias": {"name": "real", "version": "2.0.0"},
        }
    )
    entries = by_key(service)

    assert entries["node_modules/@scope/pkg"].name == "@scope/pkg"
    assert entries["node_modules/alias"].name == "real"


def test_dependency_lookup_walks_up_to_the_root() -> None:
    service = parse(
        {
            "": {"dependencies": {"a": "1"}},
            "node_modules/a": {"version": "1.0.0", "dependencies": {"b": "1", "c": "1"}},
            "node_modules/a/node_modules/b": {"version": "1.0.0", "dependencies": {"c": "1"}},
            "node_modules/c": {"version": "1.0.0"},
        }
    )

    assert edge_pairs(service) == {
        (None, "node_modules/a"),
        ("node_modules/a", "node_modules/a/node_modules/b"),
        ("node_modules/a", "node_modules/c"),
        ("node_modules/a/node_modules/b", "node_modules/c"),
    }
    assert [e.key for e in service.entries if e.direct] == ["node_modules/a"]


def test_missing_optional_or_peer_dependency_has_no_edge() -> None:
    service = parse(
        {
            "": {"dependencies": {"a": "1"}},
            "node_modules/a": {
                "version": "1.0.0",
                "optionalDependencies": {"fsevents": "2"},
                "peerDependencies": {"react": "18"},
            },
        }
    )

    assert edge_pairs(service) == {(None, "node_modules/a")}


def test_workspace_dependencies_are_direct_and_links_are_not_entries() -> None:
    service = parse(
        {
            "": {"workspaces": ["packages/*"], "dependencies": {"lib": "*"}},
            "node_modules/lib": {"resolved": "packages/lib", "link": True},
            "packages/lib": {"version": "0.1.0", "dependencies": {"left-pad": "1"}},
            "node_modules/left-pad": {"version": "1.3.0"},
        }
    )

    assert [e.key for e in service.entries] == ["node_modules/left-pad"]
    assert edge_pairs(service) == {(None, "node_modules/left-pad")}


def test_git_and_file_dependencies_are_skipped() -> None:
    service = parse(
        {
            "": {"dependencies": {"g": "github:o/g", "f": "file:../f"}},
            "node_modules/g": {
                "version": "1.0.0",
                "resolved": "git+ssh://git@github.com/o/g.git#abc",
            },
            "node_modules/f": {"version": "1.0.0", "resolved": "file:../f"},
        }
    )

    assert service.entries == []
    assert {(s.name, s.reason) for s in service.skipped} == {
        ("g", "not_from_registry"),
        ("f", "not_from_registry"),
    }
