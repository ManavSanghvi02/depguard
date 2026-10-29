"""Read-only GitHub access: commit SHA, file tree, and file contents (ADR-0012)."""

import asyncio
import json
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from depguard.github.cache import ByteCache
from depguard.http import Sleep, request_with_retries

GITHUB_API = "https://api.github.com"


class GitHubError(Exception):
    """GitHub answered with an error we can't recover from."""


class RepoNotFoundError(GitHubError):
    """The repo doesn't exist or isn't public (GitHub answers 404 for both)."""


@dataclass(frozen=True)
class Head:
    commit_sha: str
    private: bool


@dataclass(frozen=True)
class TreeFile:
    path: str
    sha: str
    size: int


@dataclass(frozen=True)
class Tree:
    files: list[TreeFile]
    truncated: bool  # GitHub cuts off very large trees


def make_client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=GITHUB_API,
        headers={
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "depguard",
        },
    )


class GitHubReader:
    def __init__(
        self, client: httpx.AsyncClient, cache: ByteCache, sleep: Sleep = asyncio.sleep
    ) -> None:
        self._client = client
        self._cache = cache
        self._sleep = sleep

    async def _get(self, path: str, accept: str = "application/vnd.github+json") -> bytes:
        response = await request_with_retries(
            self._client, "GET", path, headers={"Accept": accept}, sleep=self._sleep
        )
        if response.status_code == 404:
            raise RepoNotFoundError("repository not found or not public")
        if response.status_code == 409:
            raise GitHubError("repository is empty")
        if response.status_code != 200:
            raise GitHubError(f"GitHub returned {response.status_code} for {path}")
        return response.content

    async def latest_commit(self, owner: str, repo: str) -> Head:
        """The newest commit on the default branch. Only public repos are allowed."""
        info = json.loads(await self._get(f"/repos/{owner}/{repo}"))
        if info.get("private"):
            raise RepoNotFoundError("repository not found or not public")
        branch = quote(info["default_branch"], safe="")
        sha = await self._get(
            f"/repos/{owner}/{repo}/commits/{branch}", accept="application/vnd.github.sha"
        )
        # Stored so the LLM fallback can check it (ADR-0013); a missing field counts as private.
        return Head(commit_sha=sha.decode().strip(), private=info.get("private") is not False)

    async def tree(self, owner: str, repo: str, commit_sha: str) -> Tree:
        key = f"tree:{commit_sha}"
        content = self._cache.get(key)
        if content is None:
            content = await self._get(f"/repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1")
            self._cache.put(key, content)
        data = json.loads(content)
        files = [
            TreeFile(path=item["path"], sha=item["sha"], size=item.get("size", 0))
            for item in data["tree"]
            if item["type"] == "blob"
        ]
        return Tree(files=files, truncated=bool(data.get("truncated")))

    async def blob(self, owner: str, repo: str, blob_sha: str) -> bytes:
        """Raw file bytes. The blob API, unlike the contents API, also works for files over 1 MB."""
        key = f"blob:{blob_sha}"
        content = self._cache.get(key)
        if content is None:
            content = await self._get(
                f"/repos/{owner}/{repo}/git/blobs/{blob_sha}",
                accept="application/vnd.github.raw+json",
            )
            self._cache.put(key, content)
        return content
