import asyncio

import pytest
from fake_github import COMMIT, FakeGitHub

from depguard.github.cache import ByteCache
from depguard.github.client import RepoNotFoundError


def test_reads_commit_tree_and_blob() -> None:
    github = FakeGitHub({"package-lock.json": b"{}", "src/app.py": b"print()"})

    async def go() -> tuple[str, list[str], bytes]:
        async with github.client() as client:
            reader = github.reader(client)
            head = await reader.latest_commit("o", "r")
            assert head.private is False
            sha = head.commit_sha
            tree = await reader.tree("o", "r", sha)
            lock = next(f for f in tree.files if f.path == "package-lock.json")
            return sha, [f.path for f in tree.files], await reader.blob("o", "r", lock.sha)

    sha, paths, content = asyncio.run(go())

    assert sha == COMMIT
    assert paths == ["package-lock.json", "src/app.py"]
    assert content == b"{}"


def test_private_repo_is_treated_as_not_found() -> None:
    github = FakeGitHub({}, private=True)

    async def go() -> None:
        async with github.client() as client:
            await github.reader(client).latest_commit("o", "r")

    with pytest.raises(RepoNotFoundError):
        asyncio.run(go())


def test_missing_repo_is_not_found() -> None:
    github = FakeGitHub({})

    async def go() -> None:
        async with github.client() as client:
            await github.reader(client).latest_commit("o", "missing")

    with pytest.raises(RepoNotFoundError):
        asyncio.run(go())


def test_truncated_tree_is_reported() -> None:
    github = FakeGitHub({"a.txt": b"a"}, truncated=True)

    async def go() -> bool:
        async with github.client() as client:
            return (await github.reader(client).tree("o", "r", COMMIT)).truncated

    assert asyncio.run(go()) is True


def test_cached_blob_is_not_downloaded_twice() -> None:
    github = FakeGitHub({"uv.lock": b"version = 1"})

    async def go() -> None:
        async with github.client() as client:
            reader = github.reader(client)
            tree = await reader.tree("o", "r", COMMIT)
            await reader.blob("o", "r", tree.files[0].sha)
            await reader.blob("o", "r", tree.files[0].sha)

    asyncio.run(go())

    assert sum("/git/blobs/" in path for path in github.requests) == 1


def test_cache_drops_least_recently_used_items_over_the_size_limit() -> None:
    cache = ByteCache(max_bytes=10)
    cache.put("a", b"12345")
    cache.put("b", b"12345")
    cache.get("a")  # a is now the most recently used
    cache.put("c", b"12345")

    assert cache.get("a") == b"12345"
    assert cache.get("b") is None
    assert cache.get("c") == b"12345"
