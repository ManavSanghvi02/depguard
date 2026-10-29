"""Postgres connections. Each job connects as its own role (architecture §5.3): the API as
depguard_api, the daily refresh as depguard_refresh, migrations as the table owner."""

from collections.abc import AsyncIterator, Iterable
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import ColumnElement, any_, bindparam
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.types import TypeEngine


def sqlalchemy_url(url: str) -> str:
    """postgresql://… (the usual form, also Supabase's) -> the asyncpg driver SQLAlchemy needs.

    asyncpg rather than psycopg: psycopg's async mode can't run on Windows' default event loop."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url.removeprefix(prefix)
    return url


def in_array(
    column: QueryableAttribute[Any], values: Iterable[Any], item_type: TypeEngine[Any]
) -> ColumnElement[bool]:
    """`column = ANY($1)` with the values as one array parameter. `IN (...)` sends one parameter
    per value, and asyncpg refuses more than 32,767 in a query; the daily refresh would hit that.
    """
    return column == any_(bindparam(None, list(values), type_=ARRAY(item_type)))


def make_engine(url: str) -> AsyncEngine:
    if not url:
        raise ValueError("database URL is not set")
    # pool_pre_ping: a free-tier database may have dropped idle connections.
    return create_async_engine(sqlalchemy_url(url), pool_pre_ping=True)


def make_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, from the engine made at startup."""
    sessions: async_sessionmaker[AsyncSession] | None = request.app.state.sessions
    if sessions is None:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not set")
    async with sessions() as session:
        yield session
