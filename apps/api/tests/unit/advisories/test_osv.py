import asyncio
import json

import httpx
import pytest
from fake_osv import FakeOsv, no_sleep

from depguard.advisories.osv import BatchResult, OsvError, PackageQuery, get_vuln, query_batch

LODASH = PackageQuery("npm", "lodash", "4.17.4")
MS = PackageQuery("npm", "ms", "2.1.3")


def batch(osv: FakeOsv, queries: list[PackageQuery]) -> BatchResult:
    async def go() -> BatchResult:
        async with osv.client() as client:
            return await query_batch(client, queries, sleep=no_sleep)

    return asyncio.run(go())


def test_recorded_matches_come_back_by_package() -> None:
    result = batch(FakeOsv(), [LODASH, MS])

    assert "GHSA-jf85-cpcp-j695" in result.matches[LODASH]
    assert len(result.matches[LODASH]) == 10
    assert MS not in result.matches  # no known advisories
    assert result.failed == []


def test_requests_hold_at_most_1000_queries() -> None:
    osv = FakeOsv()
    queries = [PackageQuery("npm", f"pkg-{i}", "1.0.0") for i in range(2_500)] + [LODASH]

    result = batch(osv, queries)

    sizes = [len(json.loads(r.content)["queries"]) for r in osv.requests]
    assert sizes == [1_000, 1_000, 501]
    assert LODASH in result.matches


def test_paged_results_are_followed_until_complete() -> None:
    pages = {
        None: (["GHSA-1"], "page-2"),
        "page-2": (["GHSA-2"], "page-3"),
        "page-3": (["GHSA-3"], None),
    }
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content)["queries"][0]
        seen.append(query.get("page_token"))
        ids, token = pages[query.get("page_token")]
        answer: dict[str, object] = {"vulns": [{"id": i, "modified": ""} for i in ids]}
        if token:
            answer["next_page_token"] = token
        return httpx.Response(200, json={"results": [answer]})

    async def go() -> BatchResult:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(base_url="https://x.test", transport=transport) as client:
            return await query_batch(client, [LODASH], sleep=no_sleep)

    result = asyncio.run(go())
    assert seen == [None, "page-2", "page-3"]
    assert sorted(result.matches[LODASH]) == ["GHSA-1", "GHSA-2", "GHSA-3"]


def test_a_failed_chunk_marks_only_its_packages_unchecked() -> None:
    # The second request (queries 1,000–1,499) keeps failing; retries don't help.
    calls = {"n": 0}

    def second_request_fails(request: httpx.Request) -> bool:
        if not request.url.path.endswith("/querybatch"):
            return False
        first = str(json.loads(request.content)["queries"][0]["package"]["name"])
        calls["n"] += 1
        return first == "pkg-1000"

    queries = [PackageQuery("npm", f"pkg-{i}", "1.0.0") for i in range(1_499)] + [LODASH]
    result = batch(FakeOsv(fail=second_request_fails), queries)

    assert len(result.failed) == 500
    assert LODASH in result.failed and LODASH not in result.matches
    assert calls["n"] == 1 + 4  # first chunk once, second chunk 1 try + 3 retries


def test_a_failed_later_page_drops_the_partial_matches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content)["queries"][0]
        if query.get("page_token"):
            return httpx.Response(500)
        answer = {"vulns": [{"id": "GHSA-1", "modified": ""}], "next_page_token": "p2"}
        return httpx.Response(200, json={"results": [answer]})

    async def go() -> BatchResult:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(base_url="https://x.test", transport=transport) as client:
            return await query_batch(client, [LODASH], sleep=no_sleep)

    result = asyncio.run(go())
    assert result.failed == [LODASH]
    assert LODASH not in result.matches


def test_get_vuln_returns_the_record_or_none() -> None:
    async def go() -> tuple[object, object]:
        async with FakeOsv().client() as client:
            return (
                await get_vuln(client, "GHSA-jf85-cpcp-j695", sleep=no_sleep),
                await get_vuln(client, "GHSA-none", sleep=no_sleep),
            )

    found, missing = asyncio.run(go())
    assert isinstance(found, dict) and found["aliases"][0] == "CVE-2019-10744"
    assert missing is None


def test_get_vuln_raises_after_retries() -> None:
    async def go() -> None:
        async with FakeOsv(fail=lambda request: True).client() as client:
            await get_vuln(client, "GHSA-jf85-cpcp-j695", sleep=no_sleep)

    with pytest.raises(OsvError):
        asyncio.run(go())
