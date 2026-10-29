"""A fake OSV server that answers from real recorded responses (tests/fixtures/osv).

Recorded on 2026-10-28 from api.osv.dev; see tests/fixtures/README.md.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).parent / "fixtures" / "osv"
RECORDED = json.loads((FIXTURES / "querybatch.json").read_text(encoding="utf-8"))


def recorded_vuln(vuln_id: str) -> dict[str, Any] | None:
    path = FIXTURES / "vulns" / f"{vuln_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def recorded_matches() -> dict[tuple[str, str, str], list[dict[str, str]]]:
    """(ecosystem, name, version) -> [{id, modified}] from the recorded querybatch."""
    return {
        (q["package"]["ecosystem"], q["package"]["name"], q["version"]): result.get("vulns", [])
        for q, result in zip(RECORDED["queries"], RECORDED["response"]["results"], strict=True)
    }


class FakeOsv:
    """Answers querybatch from the recordings (unknown packages have no vulns) and /vulns/{id}
    from the recorded advisories. `fail` decides which requests get a 503 instead."""

    def __init__(self, fail: Callable[[httpx.Request], bool] = lambda request: False) -> None:
        self.fail = fail
        self.requests: list[httpx.Request] = []
        self.matches = recorded_matches()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail(request):
            return httpx.Response(503)
        if request.url.path.endswith("/querybatch"):
            queries = json.loads(request.content)["queries"]
            results = []
            for query in queries:
                key = (query["package"]["ecosystem"], query["package"]["name"], query["version"])
                vulns = self.matches.get(key, [])
                results.append({"vulns": vulns} if vulns else {})
            return httpx.Response(200, json={"results": results})
        vuln_id = request.url.path.rsplit("/", 1)[-1]
        record = recorded_vuln(vuln_id)
        return httpx.Response(200, json=record) if record else httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="https://api.osv.dev/v1", transport=httpx.MockTransport(self.handler)
        )


async def no_sleep(seconds: float) -> None:
    pass
