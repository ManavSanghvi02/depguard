"""OSV.dev: which advisories affect each package version (querybatch), and their details (ADR-0004).

https://google.github.io/osv.dev/post-v1-querybatch/
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from depguard.http import RateLimitError, Sleep, request_with_retries
from depguard.parsers.models import Ecosystem

OSV_API = "https://api.osv.dev/v1"
BATCH_SIZE = 1_000  # OSV's limit per querybatch request
DETAIL_CONCURRENCY = 10  # parallel GET /vulns/{id} calls


class OsvError(Exception):
    """OSV still failed after the retries in request_with_retries."""


@dataclass(frozen=True)
class PackageQuery:
    ecosystem: Ecosystem
    name: str
    version: str


@dataclass
class BatchResult:
    # Advisory ID -> OSV's `modified` timestamp, per package version that has any.
    matches: dict[PackageQuery, dict[str, str]] = field(default_factory=dict)
    # Packages OSV couldn't answer for: reported as osv_unavailable, never as "no findings".
    failed: list[PackageQuery] = field(default_factory=list)


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=OSV_API, headers={"User-Agent": "depguard"})


def chunks[T](items: list[T]) -> list[list[T]]:
    return [items[i : i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]


async def _post_batch(
    client: httpx.AsyncClient, queries: list[dict[str, Any]], sleep: Sleep
) -> list[dict[str, Any]]:
    try:
        response = await request_with_retries(
            client, "POST", "/querybatch", json={"queries": queries}, sleep=sleep
        )
    except (httpx.TransportError, RateLimitError) as error:
        raise OsvError(f"querybatch failed: {error}") from error
    if response.status_code != 200:
        raise OsvError(f"querybatch answered {response.status_code}")
    results: list[dict[str, Any]] = response.json().get("results", [])
    if len(results) != len(queries):
        raise OsvError("querybatch returned the wrong number of results")
    return results


def _body(query: PackageQuery, page_token: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "package": {"ecosystem": query.ecosystem, "name": query.name},
        "version": query.version,
    }
    if page_token:
        body["page_token"] = page_token
    return body


async def query_batch(
    client: httpx.AsyncClient, queries: list[PackageQuery], sleep: Sleep = asyncio.sleep
) -> BatchResult:
    """Match every package version, 1,000 per request. A query whose results come in pages is
    asked again with its page token until it has no more."""
    result = BatchResult()
    pending: list[tuple[PackageQuery, str | None]] = [(query, None) for query in queries]
    while pending:
        next_pages: list[tuple[PackageQuery, str | None]] = []
        for chunk in chunks(pending):
            try:
                answers = await _post_batch(client, [_body(q, token) for q, token in chunk], sleep)
            except OsvError:
                result.failed += [query for query, _ in chunk]
                continue
            for (query, _), answer in zip(chunk, answers, strict=True):
                for vuln in answer.get("vulns", []):
                    result.matches.setdefault(query, {})[vuln["id"]] = vuln.get("modified", "")
                if answer.get("next_page_token"):
                    next_pages.append((query, answer["next_page_token"]))
        pending = next_pages

    # A query whose later page failed is incomplete, so it counts as failed, not half-matched.
    for query in result.failed:
        result.matches.pop(query, None)
    return result


async def get_vuln(
    client: httpx.AsyncClient, vuln_id: str, sleep: Sleep = asyncio.sleep
) -> dict[str, Any] | None:
    """An advisory's full record, or None if OSV no longer has it."""
    try:
        response = await request_with_retries(
            client, "GET", f"/vulns/{quote(vuln_id, safe='')}", sleep=sleep
        )
    except (httpx.TransportError, RateLimitError) as error:
        raise OsvError(f"{vuln_id}: {error}") from error
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise OsvError(f"{vuln_id}: OSV answered {response.status_code}")
    record: dict[str, Any] = response.json()
    return record
