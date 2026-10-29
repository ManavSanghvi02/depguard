"""A fake GitHub API for tests: serves one repo from a dict of {path: file content}."""

import hashlib
import json

import httpx

from depguard.github.cache import ByteCache
from depguard.github.client import GitHubReader

COMMIT = "c0ffee"


class FakeGitHub:
    def __init__(
        self,
        files: dict[str, bytes],
        *,
        private: bool = False,
        truncated: bool = False,
        sizes: dict[str, int] | None = None,
    ) -> None:
        self.files = files
        self.private = private
        self.truncated = truncated
        self.sizes = sizes or {}
        self.requests: list[str] = []
        self.blobs = {hashlib.sha1(content).hexdigest(): content for content in files.values()}  # noqa: S324

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        if path == "/repos/o/r":
            return httpx.Response(200, json={"private": self.private, "default_branch": "main"})
        if path == "/repos/o/r/commits/main":
            return httpx.Response(200, text=COMMIT)
        if path == f"/repos/o/r/git/trees/{COMMIT}":
            tree = [
                {
                    "path": p,
                    "type": "blob",
                    "sha": hashlib.sha1(c).hexdigest(),  # noqa: S324
                    "size": self.sizes.get(p, len(c)),
                }
                for p, c in self.files.items()
            ]
            return httpx.Response(200, text=json.dumps({"tree": tree, "truncated": self.truncated}))
        if path.startswith("/repos/o/r/git/blobs/"):
            return httpx.Response(200, content=self.blobs[path.rsplit("/", 1)[1]])
        return httpx.Response(404)

    def reader(self, client: httpx.AsyncClient) -> GitHubReader:
        return GitHubReader(client, ByteCache(max_bytes=10_000_000))

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="https://api.github.test", transport=httpx.MockTransport(self.handler)
        )
