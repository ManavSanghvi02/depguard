import asyncio
from typing import Any

import pytest
from neo4j.exceptions import AuthError, ServiceUnavailable, TransientError

from depguard.graph.capacity import GraphSize
from depguard.parsers.models import ParsedService
from depguard.scan import graph
from depguard.scan.graph import FAILED, FULL, UNREACHABLE, GraphResult, store_graph

LIMITS = GraphSize(nodes=10, relationships=10)


def parsed(path: str) -> ParsedService:
    return ParsedService(
        lockfile_path=path,
        lockfile_type="requirements",
        ecosystem="PyPI",
        entries=[],
        edges=[],
        skipped=[],
    )


SERVICES = [("s1", parsed("a.txt")), ("s2", parsed("b.txt")), ("s3", parsed("c.txt"))]


def run(remove_stale: bool = True) -> GraphResult:
    return asyncio.run(store_graph(None, "repo", SERVICES, LIMITS, remove_stale))  # type: ignore[arg-type]


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records the order of graph calls: "remove" and the IDs written."""
    order: list[str] = []

    async def remove(driver: Any, repo_id: str, keep_ids: list[str]) -> None:
        assert keep_ids == ["s1", "s2", "s3"]  # refused or failed services keep their old graph
        order.append("remove")

    monkeypatch.setattr(graph, "remove_stale_services", remove)
    return order


def fake_write(monkeypatch: pytest.MonkeyPatch, calls: list[str], outcomes: dict[str, Any]) -> None:
    async def write(driver: Any, service_id: str, *args: Any) -> bool:
        calls.append(service_id)
        outcome = outcomes.get(service_id, True)
        if isinstance(outcome, Exception):
            raise outcome
        return bool(outcome)

    monkeypatch.setattr(graph, "write_service", write)


def test_stale_services_are_removed_before_writing(
    monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    fake_write(monkeypatch, calls, {})

    result = run()

    assert calls == ["remove", "s1", "s2", "s3"]
    assert all(s.written for s in result.services) and result.partial_reasons == []


def test_incomplete_file_list_keeps_unlisted_graphs(
    monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    fake_write(monkeypatch, calls, {})

    run(remove_stale=False)

    assert "remove" not in calls


def test_full_storage_is_a_partial_reason(
    monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    fake_write(monkeypatch, calls, {"s2": False})

    result = run()

    assert [s.written for s in result.services] == [True, False, True]
    assert result.partial_reasons == [f"b.txt: {FULL}"]


@pytest.mark.parametrize(
    "error", [TransientError("memory limit"), AuthError("bad password"), ValueError("bad edge")]
)
def test_a_failed_write_affects_only_that_service(
    monkeypatch: pytest.MonkeyPatch, calls: list[str], error: Exception
) -> None:
    fake_write(monkeypatch, calls, {"s2": error})

    result = run()

    assert [s.written for s in result.services] == [True, False, True]
    assert result.partial_reasons == [f"b.txt: {FAILED}"]


def test_unreachable_graph_stops_the_step(
    monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    fake_write(monkeypatch, calls, {"s2": ServiceUnavailable("down")})

    result = run()

    assert calls == ["remove", "s1", "s2"]
    assert [s.written for s in result.services] == [True, False, False]
    assert result.partial_reasons == [UNREACHABLE]


def test_failed_cleanup_is_a_partial_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    async def remove(*args: Any) -> None:
        raise AuthError("bad password")

    monkeypatch.setattr(graph, "remove_stale_services", remove)

    result = run()

    assert not any(s.written for s in result.services)
    assert result.partial_reasons == [FAILED]
