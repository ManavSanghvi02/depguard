from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fake_github import FakeGitHub
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from depguard.config import Settings, get_settings
from depguard.db.neo4j import get_driver
from depguard.github.client import GitHubReader
from depguard.graph.queries import DependencyPath, PathStep, ServiceTree
from depguard.main import app
from depguard.routes import graph
from depguard.routes.ingest import get_reader
from depguard.scan.graph import GraphResult, ServiceGraph

# No `with`: the lifespan (which builds a real driver) doesn't run; the graph layer is faked.
client = TestClient(app)


@pytest.fixture(autouse=True)
def dev_endpoints_on() -> Iterator[None]:
    settings = Settings.model_construct(enable_dev_endpoints=True, github_read_token="test")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_driver] = lambda: None
    yield
    app.dependency_overrides.clear()


def use_fake_github(github: FakeGitHub) -> None:
    async def reader() -> AsyncIterator[GitHubReader]:
        async with github.client() as http_client:
            yield github.reader(http_client)

    app.dependency_overrides[get_reader] = reader


def fake(monkeypatch: pytest.MonkeyPatch, name: str, result: Any) -> None:
    async def function(*args: Any) -> Any:
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(graph, name, function)


def test_disabled_by_default() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings.model_construct()

    assert client.get("/v1/dev/services/x/tree").status_code == 404


def test_ids_are_stable_and_case_insensitive() -> None:
    assert graph.make_repo_id("Octo", "Repo") == graph.make_repo_id("octo", "repo")
    a = graph.make_service_id("o", "r", "a/uv.lock")
    assert a != graph.make_service_id("o", "r", "b/uv.lock")


def test_ingest_into_graph_merges_partial_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fake_github(FakeGitHub({"requirements.txt": b"flask==3.0.0\n"}, truncated=True))
    service_id = graph.make_service_id("o", "r", "requirements.txt")
    fake(
        monkeypatch,
        "store_graph",
        GraphResult(
            services=[
                ServiceGraph(service_id=service_id, lockfile_path="requirements.txt", written=True)
            ],
            partial_reasons=["graph reason"],
        ),
    )

    response = client.post("/v1/dev/graph", json={"owner": "o", "repo": "r"})

    assert response.status_code == 200
    body = response.json()
    assert body["graph"][0]["service_id"] == service_id
    assert len(body["partial_reasons"]) == 2
    assert body["partial_reasons"][1] == "graph reason"


def test_unknown_service_or_entry_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, "service_tree", None)
    fake(monkeypatch, "shortest_paths", None)

    assert client.get("/v1/dev/services/x/tree").status_code == 404
    assert client.get("/v1/dev/services/x/paths?key=k").status_code == 404


def test_unreachable_graph_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, "service_tree", ServiceUnavailable("down"))

    response = client.get("/v1/dev/services/x/tree")

    assert response.status_code == 503
    assert response.json()["detail"] == "graph database unreachable"


def test_services_containing_a_package(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, "repo_services", {"s1": "web/package-lock.json", "s2": "package-lock.json"})
    fake(monkeypatch, "services_containing", ["s1"])

    response = client.get(
        "/v1/dev/repos/o/r/services",
        params={"ecosystem": "npm", "name": "@babel/core", "version": "7.0.0"},
    )

    assert response.status_code == 200
    assert response.json() == [{"service_id": "s1", "lockfile_path": "web/package-lock.json"}]


def test_unknown_ecosystem_is_rejected() -> None:
    response = client.get(
        "/v1/dev/repos/o/r/services", params={"ecosystem": "maven", "name": "x", "version": "1"}
    )

    assert response.status_code == 422


def test_tree_and_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    step = PathStep(key="node_modules/a", name="a", version="1.0.0", ambiguous=False)
    fake(monkeypatch, "shortest_paths", [DependencyPath(steps=[step], ambiguous=False)])
    fake(
        monkeypatch,
        "service_tree",
        ServiceTree(
            service_id="x", lockfile_path="package-lock.json", ecosystem="npm", entries=[], edges=[]
        ),
    )

    tree = client.get("/v1/dev/services/x/tree")
    paths = client.get("/v1/dev/services/x/paths", params={"key": "node_modules/a"})

    assert tree.status_code == 200 and tree.json()["lockfile_path"] == "package-lock.json"
    assert paths.status_code == 200
    assert paths.json() == [{"steps": [step.model_dump()], "ambiguous": False}]
