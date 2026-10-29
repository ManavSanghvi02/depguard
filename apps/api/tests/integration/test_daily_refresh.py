"""The daily refresh against real Postgres as depguard_refresh, with the downloads faked from
small real samples of the KEV and EPSS files (tests/fixtures/feeds)."""

import asyncio
import gzip
from pathlib import Path

import httpx
import pytest
from conftest import role_engine
from sqlalchemy import func, select

from depguard.advisories import feeds
from depguard.advisories.feeds import EPSS_URL, KEV_URL, FeedError
from depguard.db.models import EpssScore, KevEntry, RefreshRun
from depguard.db.postgres import make_sessions
from depguard.jobs.daily_refresh import RefreshResult, refresh

FEEDS = Path(__file__).parents[1] / "fixtures" / "feeds"
FILES = {
    KEV_URL: (FEEDS / "kev-sample.json").read_bytes(),
    EPSS_URL: gzip.compress((FEEDS / "epss-sample.csv").read_bytes()),
}


@pytest.fixture(autouse=True)
def small_samples_are_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feeds, "MIN_KEV_ENTRIES", 1)
    monkeypatch.setattr(feeds, "MIN_EPSS_ROWS", 1)


def client(files: dict[str, bytes]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        content = files.get(str(request.url))
        return httpx.Response(200, content=content) if content else httpx.Response(503)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run_refresh(
    files: dict[str, bytes],
) -> tuple[RefreshResult | Exception, dict[str, int], list[str]]:
    async def go() -> tuple[RefreshResult | Exception, dict[str, int], list[str]]:
        engine = role_engine("depguard_refresh")
        sessions = make_sessions(engine)
        try:
            async with client(files) as http:
                try:
                    result: RefreshResult | Exception = await refresh(sessions, http)
                except FeedError as error:
                    result = error
            async with sessions() as session:
                counts = {
                    "kev": await session.scalar(select(func.count()).select_from(KevEntry)) or 0,
                    "epss": await session.scalar(select(func.count()).select_from(EpssScore)) or 0,
                }
                runs = list(
                    await session.scalars(select(RefreshRun.status).order_by(RefreshRun.ran_at))
                )
            return result, counts, runs
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_refresh_loads_both_feeds_and_records_the_run(db: None) -> None:
    result, counts, runs = run_refresh(FILES)

    assert result == RefreshResult(kev_count=4, epss_count=7, rescored=0)
    assert counts == {"kev": 4, "epss": 7}
    assert runs == ["ok"]


def test_refresh_replaces_rather_than_adds(db: None) -> None:
    run_refresh(FILES)
    _, counts, runs = run_refresh(FILES)

    assert counts == {"kev": 4, "epss": 7}
    assert runs == ["ok", "ok"]


def test_a_failed_download_leaves_the_tables_unchanged(db: None) -> None:
    run_refresh(FILES)
    result, counts, runs = run_refresh({KEV_URL: FILES[KEV_URL]})  # EPSS download fails

    assert isinstance(result, FeedError)
    assert counts == {"kev": 4, "epss": 7}
    assert runs == ["ok", "failed"]
