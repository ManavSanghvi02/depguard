import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import with_driver
from neo4j import AsyncDriver

from depguard.graph.capacity import GraphSize, service_size
from depguard.graph.queries import (
    repo_services,
    service_tree,
    services_containing,
    shortest_paths,
)
from depguard.graph.schema import ensure_schema
from depguard.graph.writer import remove_stale_services, write_service
from depguard.parsers.models import Edge, Entry, ParsedService
from depguard.parsers.npm_lock import parse_package_lock
from depguard.parsers.poetry_lock import parse_poetry_lock
from depguard.parsers.requirements_txt import parse_requirements_txt
from depguard.parsers.uv_lock import parse_uv_lock

REAL = Path(__file__).parents[1] / "fixtures" / "real"
ROOMY = GraphSize(nodes=10_000_000, relationships=10_000_000)


@pytest.fixture
def repo() -> Iterator[str]:
    """A fresh repo ID per test; every service it wrote is deleted afterwards."""
    repo_id = str(uuid.uuid4())
    yield repo_id
    with_driver(lambda driver: remove_stale_services(driver, repo_id, []))


def new_id() -> str:
    return str(uuid.uuid4())


def real_services() -> list[ParsedService]:
    textual = REAL / "textual"
    return [
        parse_package_lock((REAL / "defectdojo" / "package-lock.json").read_bytes(), "a"),
        parse_requirements_txt((REAL / "defectdojo" / "requirements.txt").read_bytes(), "b"),
        parse_uv_lock((REAL / "full-stack-fastapi-template" / "uv.lock").read_bytes(), "c"),
        parse_poetry_lock(
            (textual / "poetry.lock").read_bytes(), "d", (textual / "pyproject.toml").read_bytes()
        ),
    ]


def npm_two_copies() -> ParsedService:
    """app -> a -> c@1 (nested copy) and app -> b -> c@2 (top-level copy), plus an orphan."""
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {"dependencies": {"a": "1", "b": "1"}},
            "node_modules/a": {"version": "1.0.0", "dependencies": {"c": "^1"}},
            "node_modules/a/node_modules/c": {"version": "1.0.0"},
            "node_modules/b": {"version": "1.0.0", "dependencies": {"c": "^2"}},
            "node_modules/c": {"version": "2.0.0"},
            "node_modules/orphan": {"version": "1.0.0", "extraneous": True},
        },
    }
    return parse_package_lock(json.dumps(lock).encode(), "package-lock.json")


def test_schema_is_idempotent() -> None:
    async def test(driver: AsyncDriver) -> set[str]:
        await ensure_schema(driver)
        await ensure_schema(driver)
        records, _, _ = await driver.execute_query("SHOW CONSTRAINTS YIELD name RETURN name")
        return {record["name"] for record in records}

    assert {"service_id", "dep_key"} <= with_driver(test)

    async def indexes(driver: AsyncDriver) -> set[str]:
        records, _, _ = await driver.execute_query("SHOW INDEXES YIELD name RETURN name")
        return {record["name"] for record in records}

    names = with_driver(indexes)
    assert "dep_package_norm" in names and "dep_package" not in names


def test_real_lockfiles_round_trip(repo: str) -> None:
    services = real_services()

    async def test(driver: AsyncDriver) -> None:
        for service in services:
            service_id = new_id()
            assert await write_service(driver, service_id, repo, service, ROOMY)
            tree = await service_tree(driver, service_id)
            assert tree is not None
            assert tree.lockfile_path == service.lockfile_path
            assert tree.entries == sorted(service.entries, key=lambda e: e.key)
            assert tree.edges == service.edges

    with_driver(test)


def test_rewriting_replaces_the_graph(repo: str) -> None:
    big = npm_two_copies()
    small = big.model_copy(
        update={
            "entries": big.entries[:1],
            "edges": [Edge(parent_key=None, child_key=big.entries[0].key)],
        }
    )
    service_id = new_id()

    async def test(driver: AsyncDriver) -> list[GraphSize]:
        sizes = []
        for service in (big, big, small):
            await write_service(driver, service_id, repo, service, ROOMY)
            sizes.append(await service_size(driver, service_id))
        return sizes

    first, again, after_small = with_driver(test)
    assert first == again == GraphSize(nodes=len(big.entries) + 1, relationships=len(big.edges))
    assert after_small == GraphSize(nodes=2, relationships=1)


def test_stale_services_are_removed(repo: str) -> None:
    keep, stale = new_id(), new_id()

    async def test(driver: AsyncDriver) -> tuple[dict[str, str], GraphSize]:
        await write_service(driver, keep, repo, npm_two_copies(), ROOMY)
        await write_service(driver, stale, repo, npm_two_copies(), ROOMY)
        await remove_stale_services(driver, repo, [keep])
        return await repo_services(driver, repo), await service_size(driver, stale)

    services, stale_size = with_driver(test)
    assert list(services) == [keep]
    assert stale_size == GraphSize(nodes=0, relationships=0)


def test_paths_never_cross_between_copies_of_a_package(repo: str) -> None:
    service_id = new_id()

    async def test(driver: AsyncDriver) -> None:
        await write_service(driver, service_id, repo, npm_two_copies(), ROOMY)

        nested = await shortest_paths(driver, service_id, "node_modules/a/node_modules/c")
        top = await shortest_paths(driver, service_id, "node_modules/c")
        direct = await shortest_paths(driver, service_id, "node_modules/a")
        assert nested is not None and top is not None and direct is not None
        assert [[s.key for s in p.steps] for p in nested] == [
            ["node_modules/a", "node_modules/a/node_modules/c"]
        ]
        assert [[s.key for s in p.steps] for p in top] == [["node_modules/b", "node_modules/c"]]
        assert [[s.key for s in p.steps] for p in direct] == [["node_modules/a"]]
        assert not nested[0].ambiguous

        assert await shortest_paths(driver, service_id, "node_modules/orphan") == []
        assert await shortest_paths(driver, service_id, "node_modules/missing") is None
        assert await shortest_paths(driver, new_id(), "node_modules/a") is None

    with_driver(test)


def test_ambiguous_poetry_edges_show_in_paths(repo: str) -> None:
    lock = b"""
[[package]]
name = "app-lib"
version = "1.0"
[package.dependencies]
anything = "*"

[[package]]
name = "anything"
version = "1.0"

[[package]]
name = "anything"
version = "2.0"
"""
    service = parse_poetry_lock(lock, "poetry.lock", b'[project]\ndependencies = ["app-lib"]\n')
    service_id = new_id()

    async def test(driver: AsyncDriver) -> None:
        await write_service(driver, service_id, repo, service, ROOMY)
        paths = await shortest_paths(driver, service_id, "anything==2.0")
        assert paths is not None and len(paths) == 1
        assert paths[0].ambiguous
        assert [step.ambiguous for step in paths[0].steps] == [False, True]

    with_driver(test)


def test_services_containing_only_searches_the_given_services(repo: str) -> None:
    mine, other = new_id(), new_id()
    service = parse_requirements_txt(b"Django_Filter==24.3\n", "requirements.txt")

    async def test(driver: AsyncDriver) -> None:
        await write_service(driver, mine, repo, service, ROOMY)
        await write_service(driver, other, repo, service, ROOMY)

        found = await services_containing(driver, "PyPI", "django-filter", "24.3", [mine])
        assert found == [mine]
        both = await services_containing(driver, "PyPI", "Django.Filter", "24.3", [mine, other])
        assert both == sorted([mine, other])
        assert await services_containing(driver, "PyPI", "django-filter", "1.0", [mine]) == []

    with_driver(test)


def test_services_containing_matches_equal_versions(repo: str) -> None:
    service_id = new_id()
    service = parse_requirements_txt(b"requests==2.0.0\n", "requirements.txt")

    async def test(driver: AsyncDriver) -> None:
        await write_service(driver, service_id, repo, service, ROOMY)
        assert await services_containing(driver, "PyPI", "requests", "2.0", [service_id]) == [
            service_id
        ]
        tree = await service_tree(driver, service_id)
        assert tree is not None and tree.entries[0].version == "2.0.0"  # shown as the lock says

    with_driver(test)


def test_full_graph_refuses_the_write(repo: str) -> None:
    service_id = new_id()

    async def test(driver: AsyncDriver) -> None:
        full = GraphSize(nodes=0, relationships=0)
        assert not await write_service(driver, service_id, repo, npm_two_copies(), full)
        assert await service_tree(driver, service_id) is None

    with_driver(test)


def test_a_5000_entry_service_writes_in_one_go(repo: str) -> None:
    entries = [
        Entry(key=f"p{i}==1", name=f"p{i}", version="1", dev=False, direct=i == 0)
        for i in range(5_000)
    ]
    edges = [Edge(parent_key=None, child_key="p0==1")] + [
        Edge(parent_key=f"p{i}==1", child_key=f"p{i + 1}==1") for i in range(4_999)
    ]
    service = ParsedService(
        lockfile_path="big.txt",
        lockfile_type="requirements",
        ecosystem="PyPI",
        entries=entries,
        edges=edges,
        skipped=[],
    )
    service_id = new_id()

    async def test(driver: AsyncDriver) -> GraphSize:
        assert await write_service(driver, service_id, repo, service, ROOMY)
        return await service_size(driver, service_id)

    assert with_driver(test) == GraphSize(nodes=5_001, relationships=5_000)


def operators(plan: dict[str, Any]) -> list[str]:
    children = plan.get("children", [])
    return [plan["operatorType"]] + [op for child in children for op in operators(child)]


def test_a_services_nodes_are_found_through_an_index() -> None:
    async def test(driver: AsyncDriver) -> list[str]:
        await ensure_schema(driver)
        _, summary, _ = await driver.execute_query(
            "EXPLAIN MATCH (d:Dep {service_id: $id}) RETURN d", id="x"
        )
        assert summary.plan is not None
        return operators(summary.plan)

    used = with_driver(test)
    assert not any("LabelScan" in op for op in used), used


def test_equally_short_paths_come_back_in_a_fixed_order(repo: str) -> None:
    parents = [f"p{i}" for i in (3, 1, 4, 2)]
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {"dependencies": {p: "1" for p in parents}},
            **{
                f"node_modules/{p}": {"version": "1.0.0", "dependencies": {"c": "1"}}
                for p in parents
            },
            "node_modules/c": {"version": "1.0.0"},
        },
    }
    service = parse_package_lock(json.dumps(lock).encode(), "package-lock.json")
    service_id = new_id()

    async def test(driver: AsyncDriver) -> list[list[str]]:
        await write_service(driver, service_id, repo, service, ROOMY)
        paths = await shortest_paths(driver, service_id, "node_modules/c", limit=2)
        assert paths is not None
        return [[step.key for step in path.steps] for path in paths]

    assert with_driver(test) == [
        ["node_modules/p1", "node_modules/c"],
        ["node_modules/p2", "node_modules/c"],
    ]


def test_a_refused_write_keeps_the_old_graph(repo: str) -> None:
    service_id = new_id()

    async def test(driver: AsyncDriver) -> None:
        assert await write_service(driver, service_id, repo, npm_two_copies(), ROOMY)
        smaller = parse_requirements_txt(b"flask==3.0.0\n", "requirements.txt")
        assert not await write_service(driver, service_id, repo, smaller, GraphSize(0, 0))
        tree = await service_tree(driver, service_id)
        assert tree is not None and tree.lockfile_path == "package-lock.json"

    with_driver(test)
