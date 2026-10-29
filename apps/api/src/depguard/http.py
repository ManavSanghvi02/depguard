"""HTTP requests with timeouts and retries, shared by the GitHub, OSV and KEV/EPSS clients."""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

TIMEOUT_SECONDS = 10.0
RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
# Longest we wait for a rate limit to reset before giving up; a scan must finish in about 2 minutes.
MAX_WAIT_SECONDS = 60.0

Sleep = Callable[[float], Awaitable[None]]


class RateLimitError(Exception):
    """The API's rate limit resets too far in the future to wait for."""


def backoff_seconds(attempt: int) -> float:
    # 0.5 s, 1 s, 2 s, plus a little jitter so parallel clients don't retry in lockstep.
    return 0.5 * 2.0**attempt + random.uniform(0, 0.25)  # noqa: S311 (not used for security)


def _rate_limit_wait(response: httpx.Response, now: float) -> float | None:
    """Seconds until the primary rate limit resets, or None if this isn't a rate-limit response."""
    if (
        response.status_code not in (403, 429)
        or response.headers.get("x-ratelimit-remaining") != "0"
    ):
        return None
    reset = float(response.headers.get("x-ratelimit-reset", now))
    return max(reset - now, 0.0)


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    return float(value) if value is not None and value.isdigit() else None


async def request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    sleep: Sleep = asyncio.sleep,
    now: Callable[[], float] = time.time,
    timeout: float = TIMEOUT_SECONDS,
    **kwargs: Any,
) -> httpx.Response:
    """Send a request, retrying network errors, 5xx, 429 and short rate limits.

    The last response is returned even if it is still an error; the caller decides what it means.
    4xx errors other than rate limits (401, 404, 409, 422) are returned at once, never retried.
    """
    for attempt in range(RETRIES + 1):
        last_attempt = attempt == RETRIES
        try:
            response = await client.request(method, url, timeout=timeout, **kwargs)
        except httpx.TransportError:  # connection errors and timeouts
            if last_attempt:
                raise
            await sleep(backoff_seconds(attempt))
            continue

        wait = _rate_limit_wait(response, now())
        if wait is not None:
            if wait > MAX_WAIT_SECONDS:
                raise RateLimitError(f"rate limit resets in {int(wait)} s")
            if last_attempt:
                return response
            await sleep(wait)
            continue

        retry_after = _retry_after(response)
        # GitHub's secondary rate limit is a 403 with Retry-After.
        retryable = response.status_code in RETRY_STATUSES or (
            response.status_code == 403 and retry_after is not None
        )
        if not retryable or last_attempt:
            return response
        if retry_after is not None and retry_after > MAX_WAIT_SECONDS:
            raise RateLimitError(f"server asked to retry after {int(retry_after)} s")
        await sleep(retry_after if retry_after is not None else backoff_seconds(attempt))

    raise AssertionError("unreachable")  # pragma: no cover
