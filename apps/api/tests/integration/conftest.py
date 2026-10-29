"""Integration tests run against the real Neo4j and Postgres from `make db-up` (service containers
in CI).

Locally they are skipped if a database isn't running; in CI (CI=true) that is a failure instead.
Postgres tests use their own `depguard_test` database, so they never touch dev data. They connect
as the owner and then `SET ROLE` to depguard_api or depguard_refresh, so the role's grants and
policies apply without needing the roles' passwords.
"""

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from neo4j import AsyncDriver
from neo4j.exceptions import AuthError, ServiceUnavailable
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from depguard.config import Settings
from depguard.db.neo4j import make_driver
from depguard.db.postgres import make_engine, make_sessions

TEST_DATABASE = "depguard_test"
API_DIR = Path(__file__).parents[2]


def with_driver[T](test: Callable[[AsyncDriver], Awaitable[T]]) -> T:
    """Run an async test body with a fresh driver (a driver belongs to one event loop)."""

    async def go() -> T:
        driver = make_driver(Settings())
        try:
            return await test(driver)
        finally:
            await driver.close()

    return asyncio.run(go())


def owner_url(database: str = TEST_DATABASE) -> str:
    parts = urlsplit(Settings().migration_database_url)
    return urlunsplit(parts._replace(path=f"/{database}"))


def role_engine(role: str) -> AsyncEngine:
    """An engine whose every connection acts as `role` (RLS and grants apply)."""
    engine = make_engine(owner_url())

    @event.listens_for(engine.sync_engine, "connect")
    def set_role(connection: object, _: object) -> None:
        cursor = connection.cursor()  # type: ignore[attr-defined]
        cursor.execute(f"SET ROLE {role}")
        cursor.close()

    return engine


def with_session[T](role: str, test: Callable[[AsyncSession], Awaitable[T]]) -> T:
    async def go() -> T:
        engine = role_engine(role)
        try:
            async with make_sessions(engine)() as session:
                return await test(session)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("url", owner_url())
    return config


def owner_query[T](database: str, query: Callable[[asyncpg.Connection], Awaitable[T]]) -> T:
    """Run something as the owner on a plain asyncpg connection (setup and catalog checks)."""

    async def go() -> T:
        connection = await asyncpg.connect(owner_url(database), timeout=5)
        try:
            return await query(connection)
        finally:
            await connection.close()

    return asyncio.run(go())


def clear_tables() -> None:
    async def clear(connection: asyncpg.Connection) -> None:
        tables = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename <> 'alembic_version'"
        )
        if tables:
            await connection.execute(f"TRUNCATE {', '.join(t[0] for t in tables)} CASCADE")

    owner_query(TEST_DATABASE, clear)


def fail_or_skip(message: str) -> None:
    if os.environ.get("CI"):
        raise RuntimeError(message)
    pytest.skip(message)


@pytest.fixture(scope="session", autouse=True)
def neo4j_running() -> None:
    try:
        with_driver(lambda driver: driver.verify_connectivity())
    except (ServiceUnavailable, AuthError, OSError) as error:
        fail_or_skip(f"Neo4j isn't reachable ({error}); run `make db-up`")


@pytest.fixture(scope="session")
def postgres() -> None:
    """Create the test database if needed and migrate it to the latest schema."""
    if not Settings().migration_database_url:
        fail_or_skip("MIGRATION_DATABASE_URL isn't set; see .env.example")

    async def create(connection: asyncpg.Connection) -> None:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DATABASE
        )
        if not exists:
            await connection.execute(f"CREATE DATABASE {TEST_DATABASE}")

    try:
        owner_query("postgres", create)
    except (OSError, asyncpg.PostgresError) as error:
        fail_or_skip(f"Postgres isn't reachable ({error}); run `make db-up`")
    command.upgrade(alembic_config(), "head")


@pytest.fixture
def db(postgres: None) -> None:
    """Empty tables for each test."""
    clear_tables()
