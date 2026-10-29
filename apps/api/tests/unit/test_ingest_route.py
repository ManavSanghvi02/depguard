from collections.abc import AsyncIterator, Iterator

import pytest
from fake_github import FakeGitHub
from fastapi.testclient import TestClient

from depguard.config import Settings, get_settings
from depguard.github.client import GitHubReader
from depguard.main import app
from depguard.routes.ingest import get_reader

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def use_settings(enabled: bool, token: str = "test") -> None:
    settings = Settings.model_construct(enable_dev_endpoints=enabled, github_read_token=token)
    app.dependency_overrides[get_settings] = lambda: settings


def use_fake_github(github: FakeGitHub) -> None:
    async def reader() -> AsyncIterator[GitHubReader]:
        async with github.client() as http_client:
            yield github.reader(http_client)

    app.dependency_overrides[get_reader] = reader


def test_disabled_by_default() -> None:
    use_settings(enabled=False)

    response = client.post("/v1/ingest", json={"owner": "o", "repo": "r"})

    assert response.status_code == 404


def test_missing_token_is_a_clear_error() -> None:
    use_settings(enabled=True, token="")

    response = client.post("/v1/ingest", json={"owner": "o", "repo": "r"})

    assert response.status_code == 503
    assert "GITHUB_READ_TOKEN" in response.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"owner": "../etc", "repo": "r"},
        {"owner": "o", "repo": ".."},
        {"owner": "o", "repo": "a/b"},
        {"owner": "-o", "repo": "r"},
    ],
)
def test_invalid_names_are_rejected(body: dict[str, str]) -> None:
    use_settings(enabled=True)
    use_fake_github(FakeGitHub({}))

    response = client.post("/v1/ingest", json=body)

    assert response.status_code == 422


def test_returns_parsed_services() -> None:
    use_settings(enabled=True)
    use_fake_github(FakeGitHub({"requirements.txt": b"flask==3.0.0\n"}))

    response = client.post("/v1/ingest", json={"owner": "o", "repo": "r"})

    assert response.status_code == 200
    service = response.json()["services"][0]
    assert service["entries"][0]["key"] == "flask==3.0.0"


def test_private_or_missing_repo_is_404() -> None:
    use_settings(enabled=True)
    use_fake_github(FakeGitHub({}, private=True))

    response = client.post("/v1/ingest", json={"owner": "o", "repo": "r"})

    assert response.status_code == 404
    assert response.json()["detail"] == "repository not found or not public"
