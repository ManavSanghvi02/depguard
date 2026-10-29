"""A whole scan against real Postgres (as depguard_api) and Neo4j, with GitHub and OSV faked from
recorded real responses."""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import date

import pytest
from conftest import role_engine
from fake_github import FakeGitHub
from fake_osv import FakeOsv
from fastapi import HTTPException
from sqlalchemy import func, insert, select

from depguard.config import Settings
from depguard.db.models import EpssScore, FindingScore, KevEntry, Profile, Scan
from depguard.db.neo4j import make_driver
from depguard.db.postgres import make_sessions
from depguard.github.cache import ByteCache
from depguard.graph.writer import remove_stale_services
from depguard.routes.scans import FindingOut, ScanStatus, owned_scan, ranked_findings, scan_status
from depguard.scan.pipeline import (
    NO_EXPLOIT_DATA,
    ScanAlreadyRunning,
    ScanDeps,
    fail_interrupted_scans,
    run_scan,
    start_scan,
)
from depguard.scoring.rescore import latest_scores
from depguard.scoring.score import TIER_RANK

USER = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
OTHER_USER = uuid.UUID("00000000-0000-0000-0000-0000000000bb")

# Real versions from snyk-labs/nodejs-goof plus a known-malicious npm package and an old jinja2.
PACKAGE_LOCK = json.dumps(
    {
        "lockfileVersion": 3,
        "packages": {
            "": {
                "dependencies": {"lodash": "4.17.4", "ms": "2.1.3"},
                "devDependencies": {"dustjs-linkedin": "2.5.0", "flatmap-stream": "0.1.1"},
            },
            "node_modules/lodash": {"version": "4.17.4"},
            "node_modules/ms": {"version": "2.1.3"},
            "node_modules/dustjs-linkedin": {"version": "2.5.0", "dev": True},
            "node_modules/flatmap-stream": {"version": "0.1.1", "dev": True},
        },
    }
).encode()
REQUIREMENTS = b"jinja2==2.10\nrequests>=2\n"
FILES = {"web/package-lock.json": PACKAGE_LOCK, "requirements.txt": REQUIREMENTS}

# Real EPSS values of 2026-10-28, already rounded to 3 decimals as the refresh stores them.
EPSS = [
    ("CVE-2019-10744", "0.050", "0.922"),
    ("CVE-2020-8203", "0.052", "0.925"),
    ("CVE-2021-4264", "0.012", "0.668"),
]


def run[T](
    body: Callable[[ScanDeps], Awaitable[T]], osv: FakeOsv | None = None, **github: object
) -> T:
    """Run `body` with real databases and fake GitHub/OSV in one event loop."""
    fake_github = FakeGitHub(FILES, **github)  # type: ignore[arg-type]
    fake_osv = osv or FakeOsv()

    async def go() -> T:
        engine = role_engine("depguard_api")
        driver = make_driver(Settings())
        deps = ScanDeps(
            sessions=make_sessions(engine),
            driver=driver,
            settings=Settings(),
            github_client=fake_github.client,
            osv_client=fake_osv.client,
            cache=ByteCache(max_bytes=10_000_000),
        )
        try:
            return await body(deps)
        finally:
            await driver.close()
            await engine.dispose()

    return asyncio.run(go())


async def setup_user(deps: ScanDeps, user: uuid.UUID = USER) -> None:
    async with deps.sessions() as session:
        session.add(Profile(user_id=user, github_id=user.int % 2**62, github_login=str(user)))
        await session.commit()


@pytest.fixture
def exploit_data(db: None) -> None:
    seed_exploit_data()


def seed_exploit_data(kev: list[str] | None = None) -> None:
    """Load EPSS (and optionally KEV) rows as the refresh role, the only role allowed to."""

    async def go() -> None:
        engine = role_engine("depguard_refresh")
        try:
            async with make_sessions(engine)() as session:
                await session.execute(
                    insert(EpssScore),
                    [
                        {"cve_id": c, "score": s, "percentile": p, "data_date": date(2026, 10, 28)}
                        for c, s, p in EPSS
                    ],
                )
                for cve in kev or []:
                    session.add(
                        KevEntry(cve_id=cve, date_added=date(2026, 1, 1), known_ransomware=False)
                    )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(go())


async def scan(
    deps: ScanDeps, owner: str = "o", repo: str = "r", user: uuid.UUID = USER
) -> uuid.UUID:
    async with deps.sessions() as session:
        scan_id = await start_scan(session, user, owner, repo)
    await run_scan(scan_id, deps)
    return scan_id


async def results(deps: ScanDeps, scan_id: uuid.UUID) -> tuple[ScanStatus, list[FindingOut]]:
    async with deps.sessions() as session:
        return (
            await scan_status(session, USER, scan_id),
            await ranked_findings(session, USER, scan_id),
        )


async def cleanup_graph(deps: ScanDeps) -> None:
    async with deps.sessions() as session:
        repo_ids = await session.scalars(select(Scan.repo_id).distinct())
        for repo_id in repo_ids:
            await remove_stale_services(deps.driver, str(repo_id), [])


def by_advisory(findings: list[FindingOut]) -> dict[str, FindingOut]:
    return {f.advisory_id: f for f in findings}


def test_scan_finds_merges_scores_and_ranks(exploit_data: None) -> None:
    async def body(deps: ScanDeps) -> tuple[ScanStatus, list[FindingOut]]:
        await setup_user(deps)
        scan_id = await scan(deps)
        try:
            return await results(deps, scan_id)
        finally:
            await cleanup_graph(deps)

    status, findings = run(body)

    assert status.status == "done", status.partial_reasons
    assert status.skipped == {"version_unknown": 1}  # requests>=2
    found = by_advisory(findings)

    lodash = found["GHSA-jf85-cpcp-j695"]
    assert (lodash.tier, lodash.risk_score, lodash.fixed_version) == ("fix_soon", 0.754, "4.17.12")
    assert lodash.breakdown.model_dump() == {
        "in_kev": False,
        "epss": 0.05,
        "epss_percentile": 0.922,
        "cvss": 9.1,
        "reach": 1,
        "reach_complete": True,
        "data_date": date(2026, 10, 28),
    }

    # GHSA-462w-v97r-4m45 and PYSEC-2019-217 describe one jinja2 problem: one finding.
    jinja = found["GHSA-462w-v97r-4m45"]
    assert "PYSEC-2019-217" in jinja.aliases and "PYSEC-2019-217" not in found
    assert jinja.lockfile_path == "requirements.txt"

    # A known-malicious package ranks first, even as a dev dependency.
    assert findings[0].is_malicious and findings[0].package == "flatmap-stream"
    assert (findings[0].tier, findings[0].subgroup) == ("fix_now", "malicious")
    # dustjs is dev-only with CVSS 8.8: high CVSS only counts in production.
    assert found["GHSA-c6rp-wrp9-qr4q"].tier == "monitor"
    ranks = [TIER_RANK[f.tier] for f in findings]
    assert ranks == sorted(ranks)
    assert not any(f.package == "ms" for f in findings)


def test_tier_filter(exploit_data: None) -> None:
    async def body(deps: ScanDeps) -> list[FindingOut]:
        await setup_user(deps)
        scan_id = await scan(deps)
        try:
            async with deps.sessions() as session:
                return await ranked_findings(session, USER, scan_id, "fix_now")
        finally:
            await cleanup_graph(deps)

    assert {f.tier for f in run(body)} == {"fix_now"}


def test_osv_outage_makes_the_scan_partial_never_smaller(exploit_data: None) -> None:
    osv = FakeOsv(fail=lambda request: request.url.path.endswith("/querybatch"))

    async def body(deps: ScanDeps) -> tuple[ScanStatus, list[FindingOut]]:
        await setup_user(deps)
        scan_id = await scan(deps)
        try:
            return await results(deps, scan_id)
        finally:
            await cleanup_graph(deps)

    status, findings = run(body, osv=osv)

    assert status.status == "partial"
    assert "OSV was unavailable" in status.partial_reasons[0]
    assert status.skipped == {"version_unknown": 1, "osv_unavailable": 5}
    assert findings == []


def test_failed_advisory_details_keep_the_finding_by_id(exploit_data: None) -> None:
    osv = FakeOsv(fail=lambda request: request.url.path.endswith("/GHSA-jf85-cpcp-j695"))

    async def body(deps: ScanDeps) -> tuple[ScanStatus, list[FindingOut]]:
        await setup_user(deps)
        scan_id = await scan(deps)
        try:
            return await results(deps, scan_id)
        finally:
            await cleanup_graph(deps)

    status, findings = run(body, osv=osv)

    assert status.status == "partial"
    assert any("could not be fetched" in reason for reason in status.partial_reasons)
    lodash = by_advisory(findings)["GHSA-jf85-cpcp-j695"]
    assert lodash.summary is None and lodash.fixed_version is None


def test_missing_exploit_data_is_a_partial_reason(db: None) -> None:
    async def body(deps: ScanDeps) -> ScanStatus:
        await setup_user(deps)
        scan_id = await scan(deps)
        try:
            return (await results(deps, scan_id))[0]
        finally:
            await cleanup_graph(deps)

    status = run(body)
    assert status.status == "partial" and status.partial_reasons == [NO_EXPLOIT_DATA]


def test_reach_counts_services_across_repos_and_rescoring_adds_rows_only_on_change(
    exploit_data: None,
) -> None:
    async def body(deps: ScanDeps) -> tuple[list[FindingOut], list[FindingOut], int, int]:
        await setup_user(deps)
        first = await scan(deps)
        rows_before = await count_scores(deps)
        again = await scan(deps)  # same repo, same data: a new scan, so new findings
        rows_after = await count_scores(deps)
        try:
            return (
                (await results(deps, first))[1],
                (await results(deps, again))[1],
                rows_before,
                rows_after,
            )
        finally:
            await cleanup_graph(deps)

    first, again, rows_before, rows_after = run(body)
    # Reach counts each repo's latest scan only, so rescanning doesn't double it.
    assert by_advisory(again)["GHSA-jf85-cpcp-j695"].breakdown.reach == 1
    assert rows_after == 2 * rows_before  # the new scan's findings, nothing for unchanged ones
    assert len(first) == len(again)


def test_a_second_repo_with_the_same_package_raises_reach(exploit_data: None) -> None:
    async def body(deps: ScanDeps) -> tuple[int, int]:
        await setup_user(deps)
        first = await scan(deps)
        await run_other_repo(deps)
        try:
            findings = (await results(deps, first))[1]
            return by_advisory(findings)["GHSA-jf85-cpcp-j695"].breakdown.reach, await count_scores(
                deps
            )
        finally:
            await cleanup_graph(deps)

    reach, _ = run(body)
    assert reach == 2  # repo A's finding was rescored when repo B was scanned


async def run_other_repo(deps: ScanDeps, osv_down: bool = False) -> None:
    other = FakeGitHub({"package-lock.json": PACKAGE_LOCK}, repo="o/second")
    changes: dict[str, object] = {"github_client": other.client}
    if osv_down:
        changes["osv_client"] = FakeOsv(fail=lambda request: True).client
    await scan(ScanDeps(**{**deps.__dict__, **changes}), repo="second")


def lodash_reach(findings: list[FindingOut]) -> tuple[int, bool]:
    breakdown = by_advisory(findings)["GHSA-jf85-cpcp-j695"].breakdown
    return breakdown.reach, breakdown.reach_complete


def test_an_osv_outage_does_not_lower_other_repos_reach(exploit_data: None) -> None:
    async def body(deps: ScanDeps) -> tuple[tuple[int, bool], tuple[int, bool]]:
        await setup_user(deps)
        first = await scan(deps)
        await run_other_repo(deps)
        before = lodash_reach((await results(deps, first))[1])
        await run_other_repo(deps, osv_down=True)  # the second repo's latest scan is now partial
        try:
            return before, lodash_reach((await results(deps, first))[1])
        finally:
            await cleanup_graph(deps)

    before, after = run(body)
    # The second repo still counts through its last fully checked scan.
    assert before == after == (2, True)


def test_a_repo_with_only_a_partial_scan_marks_reach_incomplete(exploit_data: None) -> None:
    async def body(deps: ScanDeps) -> tuple[int, bool]:
        await setup_user(deps)
        first = await scan(deps)
        await run_other_repo(deps, osv_down=True)  # never fully checked
        try:
            return lodash_reach((await results(deps, first))[1])
        finally:
            await cleanup_graph(deps)

    assert run(body) == (1, False)


async def count_scores(deps: ScanDeps) -> int:
    async with deps.sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(FindingScore)) or 0)


def test_one_active_scan_per_repo(db: None) -> None:
    async def body(deps: ScanDeps) -> None:
        await setup_user(deps)
        async with deps.sessions() as session:
            await start_scan(session, USER, "o", "r")
        async with deps.sessions() as session:
            await start_scan(session, USER, "O", "R")  # same repo: names are case-insensitive

    with pytest.raises(ScanAlreadyRunning):
        run(body)


def test_another_users_scan_is_not_found(db: None) -> None:
    async def body(deps: ScanDeps) -> None:
        await setup_user(deps, OTHER_USER)
        async with deps.sessions() as session:
            scan_id = await start_scan(session, OTHER_USER, "o", "r")
            await owned_scan(session, USER, scan_id)

    with pytest.raises(HTTPException) as error:
        run(body)
    assert error.value.status_code == 404


def test_missing_repo_fails_the_scan_with_a_message(db: None) -> None:
    async def body(deps: ScanDeps) -> ScanStatus:
        await setup_user(deps)
        scan_id = await scan(deps)
        return (await results(deps, scan_id))[0]

    status = run(body, private=True)
    assert status.status == "failed"
    assert status.error == "repository not found or not public"


def test_interrupted_scans_are_failed_at_startup(db: None) -> None:
    async def body(deps: ScanDeps) -> tuple[int, str | None]:
        await setup_user(deps)
        async with deps.sessions() as session:
            scan_id = await start_scan(session, USER, "o", "r")
        async with deps.sessions() as session:
            count = await fail_interrupted_scans(session)
        async with deps.sessions() as session:
            return count, (await session.get_one(Scan, scan_id)).error

    assert run(body) == (1, "server restarted")


def test_kev_puts_a_production_finding_in_fix_now(db: None) -> None:
    seed_exploit_data(kev=["CVE-2019-10744"])

    async def body(deps: ScanDeps) -> FindingOut:
        await setup_user(deps)
        scan_id = await scan(deps)
        try:
            return by_advisory((await results(deps, scan_id))[1])["GHSA-jf85-cpcp-j695"]
        finally:
            await cleanup_graph(deps)

    lodash = run(body)
    assert (lodash.tier, lodash.subgroup, lodash.breakdown.in_kev) == ("fix_now", "kev", True)


def test_rescoring_lookups_take_more_ids_than_a_query_has_parameters(db: None) -> None:
    """asyncpg allows 32,767 parameters per query; the ID lists go in as one array instead."""

    async def body(deps: ScanDeps) -> int:
        async with deps.sessions() as session:
            found = await latest_scores(session, [uuid.uuid4() for _ in range(40_000)])
            return len(found)

    assert run(body) == 0
