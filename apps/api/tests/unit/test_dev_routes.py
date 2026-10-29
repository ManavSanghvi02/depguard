"""Dev route behaviour without databases: Postgres and Neo4j calls are faked. The real queries are
covered by tests/integration."""

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from depguard.config import Settings, get_settings
from depguard.db.neo4j import get_driver
from depguard.db.postgres import get_session
from depguard.graph.queries import DependencyPath, PathStep, ServiceTree
from depguard.main import app
from depguard.routes import graph, scans
from depguard.scan.pipeline import ScanAlreadyRunning

# No `with`: the lifespan (which builds real database clients) doesn't run.
client = TestClient(app)
SERVICE = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def dev_endpoints_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    settings = Settings.model_construct(enable_dev_endpoints=True, github_read_token="test")

    async def no_session() -> AsyncIterator[None]:
        yield None

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_driver] = lambda: None
    # What the lifespan would set; the scan deps read them.
    app.state.sessions = None
    app.state.neo4j = None
    app.dependency_overrides[get_session] = no_session
    fake(monkeypatch, graph, "owned_service", None)
    yield
    app.dependency_overrides.clear()


def fake(monkeypatch: pytest.MonkeyPatch, module: Any, name: str, result: Any) -> None:
    async def function(*args: Any) -> Any:
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(module, name, function)


def test_disabled_by_default() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings.model_construct()

    assert client.get(f"/v1/dev/services/{SERVICE}/tree").status_code == 404
    assert client.post("/v1/dev/scans", json={"owner": "o", "repo": "r"}).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"owner": "../etc", "repo": "r"},
        {"owner": "o", "repo": ".."},
        {"owner": "o", "repo": "a/b"},
        {"owner": "-o", "repo": "r"},
    ],
)
def test_invalid_repo_names_are_rejected(body: dict[str, str]) -> None:
    assert client.post("/v1/dev/scans", json=body).status_code == 422


def test_missing_token_is_a_clear_error() -> None:
    settings = Settings.model_construct(enable_dev_endpoints=True, github_read_token="")
    app.dependency_overrides[get_settings] = lambda: settings

    response = client.post("/v1/dev/scans", json={"owner": "o", "repo": "r"})

    assert response.status_code == 503
    assert "GITHUB_READ_TOKEN" in response.json()["detail"]


def test_a_running_scan_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, scans, "ensure_dev_profile", None)
    fake(monkeypatch, scans, "start_scan", ScanAlreadyRunning())

    response = client.post("/v1/dev/scans", json={"owner": "o", "repo": "r"})

    assert response.status_code == 409


def test_unknown_scan_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, scans, "owned_scan", HTTPException(404, "scan not found"))

    assert client.get(f"/v1/dev/scans/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/v1/dev/scans/{uuid.uuid4()}/findings").status_code == 404
    assert client.get("/v1/dev/scans/not-a-uuid").status_code == 422


def test_unknown_tier_is_rejected() -> None:
    assert client.get(f"/v1/dev/scans/{uuid.uuid4()}/findings?tier=urgent").status_code == 422


def test_another_users_service_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, graph, "owned_service", HTTPException(404, "service not found"))

    assert client.get(f"/v1/dev/services/{SERVICE}/tree").status_code == 404


def test_unknown_entry_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, graph, "service_tree", None)
    fake(monkeypatch, graph, "shortest_paths", None)

    assert client.get(f"/v1/dev/services/{SERVICE}/tree").status_code == 404
    assert client.get(f"/v1/dev/services/{SERVICE}/paths?key=k").status_code == 404


def test_unreachable_graph_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, graph, "service_tree", ServiceUnavailable("down"))

    response = client.get(f"/v1/dev/services/{SERVICE}/tree")

    assert response.status_code == 503
    assert response.json()["detail"] == "graph database unreachable"


def test_unknown_ecosystem_is_rejected() -> None:
    response = client.get(
        "/v1/dev/repos/o/r/services", params={"ecosystem": "maven", "name": "x", "version": "1"}
    )

    assert response.status_code == 422


def test_tree_and_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    step = PathStep(key="node_modules/a", name="a", version="1.0.0", ambiguous=False)
    fake(monkeypatch, graph, "shortest_paths", [DependencyPath(steps=[step], ambiguous=False)])
    fake(
        monkeypatch,
        graph,
        "service_tree",
        ServiceTree(
            service_id=SERVICE,
            lockfile_path="package-lock.json",
            ecosystem="npm",
            entries=[],
            edges=[],
        ),
    )

    tree = client.get(f"/v1/dev/services/{SERVICE}/tree")
    paths = client.get(f"/v1/dev/services/{SERVICE}/paths", params={"key": "node_modules/a"})

    assert tree.status_code == 200 and tree.json()["lockfile_path"] == "package-lock.json"
    assert paths.status_code == 200
    assert paths.json() == [{"steps": [step.model_dump()], "ambiguous": False}]
