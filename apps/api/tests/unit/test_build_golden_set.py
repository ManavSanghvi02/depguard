"""The golden-set builder's own logic (scripts/build_golden_set.py): paths, downloads, case lookup
and reach. The rest is the scan's code, tested elsewhere."""

import hashlib
import uuid
from pathlib import Path

import pytest
from build_golden_set import download, pick, reach, shortest_paths

from depguard.advisories.aliases import MergedAdvisory
from depguard.parsers.models import Edge, Entry, ParsedService
from depguard.scan.match import FindingDraft


def service(edges: list[tuple[str | None, str]], extra: tuple[str, ...] = ()) -> ParsedService:
    keys = sorted({k for edge in edges for k in edge if k} | set(extra))
    return ParsedService(
        lockfile_path="package-lock.json",
        lockfile_type="package-lock",
        ecosystem="npm",
        entries=[Entry(key=k, name=k, version="1.0.0", dev=False, direct=False) for k in keys],
        edges=[Edge(parent_key=p, child_key=c) for p, c in edges],
        skipped=[],
    )


def names(paths: list[list[Entry]]) -> list[list[str]]:
    return [[e.name for e in path] for path in paths]


def test_a_direct_dependency_is_its_own_path() -> None:
    assert names(shortest_paths(service([(None, "t")]), "t")) == [["t"]]


def test_only_the_shortest_paths_in_name_order() -> None:
    graph = service([(None, "b"), (None, "a"), (None, "x"), ("a", "c"), ("b", "c"), ("c", "t"),
                     ("x", "y"), ("y", "z"), ("z", "t")])  # fmt: skip
    assert names(shortest_paths(graph, "t")) == [["a", "c", "t"], ["b", "c", "t"]]


def test_at_most_three_paths() -> None:
    graph = service([*((None, f"p{i}") for i in range(5)), *((f"p{i}", "t") for i in range(5))])
    assert names(shortest_paths(graph, "t")) == [["p0", "t"], ["p1", "t"], ["p2", "t"]]


def test_a_cycle_does_not_loop() -> None:
    graph = service([(None, "a"), ("a", "b"), ("b", "a"), ("b", "t")])
    assert names(shortest_paths(graph, "t")) == [["a", "b", "t"]]


def test_an_unreachable_package_has_no_path() -> None:
    assert shortest_paths(service([(None, "a")], extra=("u",)), "u") == []


def test_download_writes_a_file_only_when_its_hash_matches(tmp_path: Path) -> None:
    content = b'{"lockfileVersion": 3}'
    good = {"a/lock.json": {"url": "u", "sha256": hashlib.sha256(content).hexdigest()}}
    download(good, tmp_path, lambda url: content)
    assert (tmp_path / "a/lock.json").read_bytes() == content

    bad = {"b/lock.json": {"url": "u", "sha256": "0" * 64}}
    with pytest.raises(SystemExit, match="differs"):
        download(bad, tmp_path, lambda url: content)
    assert not (tmp_path / "b/lock.json").exists()


def test_a_changed_file_already_on_disk_is_refused(tmp_path: Path) -> None:
    (tmp_path / "lock.json").write_bytes(b"changed")
    with pytest.raises(SystemExit, match="differs"):
        download({"lock.json": {"url": "u", "sha256": "0" * 64}}, tmp_path, lambda url: b"")


def draft(key: str, service_id: uuid.UUID | None = None) -> FindingDraft:
    advisory = MergedAdvisory("GHSA-x", ("GHSA-x",), None, None, False, ())
    entry = Entry(key=key, name="lodash", version="4.17.4", dev=False, direct=False)
    return FindingDraft(service_id or uuid.uuid4(), "npm", entry, "4.17.4", advisory, None, False)


CASE = {"id": "c", "package": "lodash", "version": "4.17.4", "advisory": "GHSA-x"}


def test_pick_needs_a_key_when_the_package_is_installed_twice() -> None:
    drafts = [draft("node_modules/lodash"), draft("node_modules/a/node_modules/lodash")]
    with pytest.raises(SystemExit, match="set `key` to one of: node_modules/lodash"):
        pick(drafts, CASE)
    assert pick(drafts, {**CASE, "key": "node_modules/lodash"}) is drafts[0]


def test_reach_counts_the_lockfiles_with_the_same_package_version_and_advisory() -> None:
    by_path = {"one": [draft("k")], "two": [draft("k")], "three": []}
    assert reach(by_path, by_path["one"][0]) == 2
