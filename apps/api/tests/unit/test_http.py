import asyncio

import httpx
import pytest

from depguard.http import RateLimitError, request_with_retries

NOW = 1_000_000.0


def run(responses: list[httpx.Response | Exception]) -> tuple[httpx.Response, int, list[float]]:
    """Send one request against a server that replies with `responses` in order."""
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        reply = responses[min(calls, len(responses) - 1)]
        calls += 1
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def go() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await request_with_retries(
                client, "GET", "https://x.test/", sleep=sleep, now=lambda: NOW
            )

    response = asyncio.run(go())
    return response, calls, sleeps


def ok() -> httpx.Response:
    return httpx.Response(200)


def test_retries_a_server_error_then_succeeds() -> None:
    response, calls, sleeps = run([httpx.Response(503), ok()])

    assert response.status_code == 200
    assert calls == 2
    assert 0.5 <= sleeps[0] <= 0.75


def test_gives_up_after_three_retries_and_returns_the_last_response() -> None:
    response, calls, sleeps = run([httpx.Response(503)])

    assert response.status_code == 503
    assert calls == 4
    assert len(sleeps) == 3


def test_client_errors_are_not_retried() -> None:
    response, calls, _ = run([httpx.Response(404)])

    assert response.status_code == 404
    assert calls == 1


def test_network_errors_are_retried() -> None:
    response, calls, _ = run([httpx.ConnectError("refused"), ok()])

    assert response.status_code == 200
    assert calls == 2


def test_network_error_on_every_attempt_is_raised() -> None:
    with pytest.raises(httpx.ConnectError):
        run([httpx.ConnectError("refused")])


def test_retry_after_header_is_honoured() -> None:
    _, _, sleeps = run([httpx.Response(429, headers={"retry-after": "7"}), ok()])

    assert sleeps == [7.0]


def test_secondary_rate_limit_403_is_retried() -> None:
    response, calls, _ = run([httpx.Response(403, headers={"retry-after": "2"}), ok()])

    assert response.status_code == 200
    assert calls == 2


def test_waits_for_a_rate_limit_that_resets_soon() -> None:
    limited = httpx.Response(
        403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(NOW) + 30)}
    )

    response, _, sleeps = run([limited, ok()])

    assert response.status_code == 200
    assert sleeps == [30.0]


def test_fails_fast_when_the_rate_limit_resets_much_later() -> None:
    limited = httpx.Response(
        403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(NOW) + 600)}
    )

    with pytest.raises(RateLimitError):
        run([limited])
