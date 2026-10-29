import asyncio
import json

from fake_github import FakeGitHub

from depguard.config import Settings
from depguard.github.client import TreeFile
from depguard.scan.ingest import IngestResult, ingest_repo, select_lockfiles

NPM_LOCK = json.dumps(
    {
        "lockfileVersion": 3,
        "packages": {"": {"dependencies": {"a": "1"}}, "node_modules/a": {"version": "1.0.0"}},
    }
).encode()
POETRY_LOCK = b'[[package]]\nname = "rich"\nversion = "14.0.0"\n'
PYPROJECT = b'[project]\ndependencies = ["rich"]\n'


def ingest(github: FakeGitHub, **limits: int) -> IngestResult:
    # model_construct skips reading the developer's local .env.
    settings = Settings.model_construct(github_read_token="test").model_copy(update=limits)

    async def go() -> IngestResult:
        async with github.client() as client:
            return await ingest_repo(github.reader(client), "o", "r", settings)

    return asyncio.run(go())


def test_selects_supported_lockfiles_outside_dependency_and_test_folders() -> None:
    paths = [
        "package-lock.json",
        "web/package-lock.json",
        "node_modules/x/package-lock.json",
        "tests/fixtures/poetry.lock",
        "api/uv.lock",
        "requirements-dev.txt",
        "requirements/base.txt",  # folder form is not supported
        "package.json",
    ]

    selected = select_lockfiles([TreeFile(path=p, sha="s", size=1) for p in paths])

    assert [(f.path, kind) for f, kind in selected] == [
        ("api/uv.lock", "uv-lock"),
        ("package-lock.json", "package-lock"),
        ("requirements-dev.txt", "requirements"),
        ("web/package-lock.json", "package-lock"),
    ]


def test_ingests_every_lockfile_as_a_service() -> None:
    github = FakeGitHub(
        {
            "package-lock.json": NPM_LOCK,
            "py/poetry.lock": POETRY_LOCK,
            "py/pyproject.toml": PYPROJECT,
            "requirements.txt": b"flask==3.0.0\nrequests>=2\n",
            "README.md": b"hello",
        }
    )

    result = ingest(github)

    assert result.commit_sha == "c0ffee"
    assert [s.lockfile_path for s in result.services] == [
        "package-lock.json",
        "py/poetry.lock",
        "requirements.txt",
    ]
    poetry = result.services[1]
    assert poetry.entries[0].direct is True  # from py/pyproject.toml
    assert result.services[2].skipped[0].name == "requests"
    assert result.failed_services == [] and result.partial_reasons == []


def test_one_bad_lockfile_does_not_fail_the_others() -> None:
    github = FakeGitHub({"a/package-lock.json": b"{broken", "b/package-lock.json": NPM_LOCK})

    result = ingest(github)

    assert [s.lockfile_path for s in result.services] == ["b/package-lock.json"]
    assert result.failed_services[0].lockfile_path == "a/package-lock.json"
    assert "invalid JSON" in result.failed_services[0].error


def test_lockfile_count_limit_is_a_partial_reason() -> None:
    github = FakeGitHub({f"s{i}/package-lock.json": NPM_LOCK for i in range(3)})

    result = ingest(github, max_lockfiles_per_repo=2)

    assert len(result.services) == 2
    assert result.partial_reasons == ["3 lockfiles found; only the first 2 were scanned"]


def test_oversized_lockfile_is_not_downloaded() -> None:
    github = FakeGitHub({"package-lock.json": NPM_LOCK}, sizes={"package-lock.json": 20_000_000})

    result = ingest(github)

    assert result.services == []
    assert "larger than 10 MB" in result.failed_services[0].error
    assert not any("/git/blobs/" in path for path in github.requests)


def test_too_many_dependencies_fails_that_service() -> None:
    result = ingest(FakeGitHub({"package-lock.json": NPM_LOCK}), max_entries_per_service=0)

    assert result.services == []
    assert "the limit is 0" in result.failed_services[0].error


def test_truncated_tree_and_parser_warnings_are_partial_reasons() -> None:
    github = FakeGitHub({"poetry.lock": POETRY_LOCK}, truncated=True)

    result = ingest(github)

    assert len(result.partial_reasons) == 2
    assert "truncated" in result.partial_reasons[0]
    assert result.partial_reasons[1].startswith("poetry.lock: pyproject.toml not found")
