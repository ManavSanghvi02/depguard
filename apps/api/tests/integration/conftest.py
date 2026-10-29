"""Integration tests run against the real Neo4j from `make db-up` (a service container in CI).

Locally they are skipped if Neo4j isn't running; in CI (CI=true) that is a failure instead.
"""

import asyncio
import os
from collections.abc import Awaitable, Callable

import pytest
from neo4j import AsyncDriver
from neo4j.exceptions import AuthError, ServiceUnavailable

from depguard.config import Settings
from depguard.db.neo4j import make_driver


def with_driver[T](test: Callable[[AsyncDriver], Awaitable[T]]) -> T:
    """Run an async test body with a fresh driver (a driver belongs to one event loop)."""

    async def go() -> T:
        driver = make_driver(Settings())
        try:
            return await test(driver)
        finally:
            await driver.close()

    return asyncio.run(go())


@pytest.fixture(scope="session", autouse=True)
def neo4j_running() -> None:
    try:
        with_driver(lambda driver: driver.verify_connectivity())
    except (ServiceUnavailable, AuthError, OSError) as error:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"Neo4j isn't reachable ({error}); run `make db-up`")
