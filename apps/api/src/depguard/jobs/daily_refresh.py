"""Daily refresh (architecture §3.1): download KEV and EPSS, replace both tables, rescore every
repo's latest scan, record the run. Runs as depguard_refresh (REFRESH_DATABASE_URL).

Locally: `make refresh`. On GitHub Actions (daily-refresh.yml) from the deploy phase, which also
adds the Neo4j keep-alive write.
"""

import asyncio
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from depguard.advisories.feeds import (
    EPSS_URL,
    KEV_URL,
    EpssRow,
    FeedError,
    KevRow,
    parse_epss,
    parse_kev,
)
from depguard.config import get_settings
from depguard.db.models import RefreshRun
from depguard.db.postgres import make_engine, make_sessions
from depguard.http import RateLimitError, request_with_retries
from depguard.scoring.rescore import rescore

logger = logging.getLogger(__name__)
DOWNLOAD_TIMEOUT_SECONDS = 60.0  # the EPSS file is ~3 MB; slower than the API default allows


@dataclass(frozen=True)
class RefreshResult:
    kev_count: int
    epss_count: int
    rescored: int


async def download(client: httpx.AsyncClient, url: str) -> bytes:
    try:
        response = await request_with_retries(client, "GET", url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    except (httpx.TransportError, RateLimitError) as error:
        raise FeedError(f"download failed: {url}: {error}") from error
    if response.status_code != 200:
        raise FeedError(f"download failed: {url} answered {response.status_code}")
    return response.content


async def replace_tables(session: AsyncSession, kev: list[KevRow], epss: list[EpssRow]) -> None:
    """Swap in the new snapshot inside the caller's transaction (readers see old or new, never
    half). Postgres refuses COPY under row-level security, so each table gets one INSERT that
    unpacks whole columns from arrays: still one statement for ~300,000 EPSS rows."""
    await session.execute(text("TRUNCATE kev_entries, epss_scores"))
    connection = await (await session.connection()).get_raw_connection()
    raw = connection.driver_connection
    assert raw is not None  # noqa: S101 (always set for an open asyncpg connection)
    await raw.execute(
        "INSERT INTO kev_entries (cve_id, date_added, due_date, known_ransomware)"
        " SELECT * FROM unnest($1::text[], $2::date[], $3::date[], $4::boolean[])",
        *columns(kev),
    )
    await raw.execute(
        "INSERT INTO epss_scores (cve_id, score, percentile, data_date)"
        " SELECT * FROM unnest($1::text[], $2::numeric[], $3::numeric[], $4::date[])",
        *columns(epss),
    )


def columns(rows: Sequence[tuple[object, ...]]) -> list[list[object]]:
    """Rows -> one list per column."""
    return [list(column) for column in zip(*rows, strict=True)]


async def record_failure(sessions: async_sessionmaker[AsyncSession], message: str) -> None:
    """A failed run is recorded too, unless the database itself is what failed."""
    try:
        async with sessions() as session:
            session.add(RefreshRun(status="failed", error=message))
            await session.commit()
    except (OSError, SQLAlchemyError):
        logger.exception("could not record the failed refresh run")


async def refresh(
    sessions: async_sessionmaker[AsyncSession], client: httpx.AsyncClient
) -> RefreshResult:
    try:
        kev = parse_kev(await download(client, KEV_URL))
        epss = parse_epss(await download(client, EPSS_URL))
    except FeedError as error:
        await record_failure(sessions, str(error))
        raise

    try:
        async with sessions() as session:
            await replace_tables(session, kev, epss)
            rescored = await rescore(session)
            session.add(
                RefreshRun(
                    status="ok",
                    kev_count=len(kev),
                    epss_count=len(epss),
                    epss_date=epss[0][3],
                    rescored=rescored,
                )
            )
            await session.commit()
    except SQLAlchemyError as error:
        # The transaction rolled back, so the old snapshot and scores are still in place.
        await record_failure(sessions, f"database step failed: {type(error).__name__}")
        raise
    return RefreshResult(kev_count=len(kev), epss_count=len(epss), rescored=rescored)


async def main() -> int:
    settings = get_settings()
    if not settings.refresh_database_url:
        print("REFRESH_DATABASE_URL is not set (see .env.example)", file=sys.stderr)
        return 1
    engine = make_engine(settings.refresh_database_url)
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": "depguard"},
            follow_redirects=True,  # EPSS's "current" redirects
        ) as client:
            result = await refresh(make_sessions(engine), client)
    except (FeedError, SQLAlchemyError) as error:
        print(f"refresh failed, tables unchanged: {error}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    print(
        f"KEV {result.kev_count} entries, EPSS {result.epss_count} scores,"
        f" {result.rescored} new score rows"
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(asyncio.run(main()))
