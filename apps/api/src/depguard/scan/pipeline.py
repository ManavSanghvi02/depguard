"""A whole repo scan (architecture §3, steps 2–9), run as a background task (ADR-0008).

Status: queued -> running -> done | partial | failed. Anything that makes the results incomplete
is a partial reason; only an unrecoverable error fails the scan.
"""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from neo4j import AsyncDriver
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from depguard.config import Settings
from depguard.db.models import Finding, Repo, Scan, Service, SkippedPackage
from depguard.github.cache import ByteCache
from depguard.github.client import GitHubError, GitHubReader
from depguard.graph.capacity import GraphSize
from depguard.http import RateLimitError
from depguard.parsers.models import ParsedService
from depguard.scan.graph import store_graph
from depguard.scan.ingest import ingest_repo
from depguard.scan.match import MatchResult, match_services
from depguard.scoring.rescore import epss_date, rescore

logger = logging.getLogger(__name__)

ACTIVE = ("queued", "running")
NO_EXPLOIT_DATA = "KEV and EPSS data not loaded yet, so tiers ignore exploitation; run make refresh"


class ScanAlreadyRunning(Exception):
    pass


@dataclass(frozen=True)
class ScanDeps:
    """What a scan needs. The route builds the real ones; tests pass fakes."""

    sessions: async_sessionmaker[AsyncSession]
    driver: AsyncDriver
    settings: Settings
    github_client: Callable[[], httpx.AsyncClient]
    osv_client: Callable[[], httpx.AsyncClient]
    cache: ByteCache


async def start_scan(session: AsyncSession, user_id: uuid.UUID, owner: str, name: str) -> uuid.UUID:
    """Add the repo for this user if new, and queue a scan. One active scan per repo."""
    statement = insert(Repo).values(user_id=user_id, owner=owner.lower(), name=name.lower())
    # The upsert also locks the repo row until commit, so two requests can't both start a scan.
    repo_id = await session.scalar(
        statement.on_conflict_do_update(
            index_elements=[Repo.user_id, Repo.owner, Repo.name],
            set_={"owner": statement.excluded.owner},
        ).returning(Repo.id)
    )
    assert repo_id is not None  # noqa: S101 (RETURNING always gives the row)
    running = await session.scalar(
        select(func.count()).where(Scan.repo_id == repo_id, Scan.status.in_(ACTIVE))
    )
    if running:
        await session.rollback()
        raise ScanAlreadyRunning
    scan = Scan(repo_id=repo_id, status="queued")
    session.add(scan)
    await session.commit()
    return scan.id


async def save_services(
    session: AsyncSession, repo_id: uuid.UUID, services: list[ParsedService]
) -> list[tuple[uuid.UUID, ParsedService]]:
    """Upsert one row per lockfile; a lockfile keeps its ID (and graph) across scans."""
    saved = []
    for service in services:
        statement = insert(Service).values(
            repo_id=repo_id,
            lockfile_path=service.lockfile_path,
            ecosystem=service.ecosystem,
            lockfile_type=service.lockfile_type,
        )
        service_id = await session.scalar(
            statement.on_conflict_do_update(
                index_elements=[Service.repo_id, Service.lockfile_path],
                set_={"ecosystem": service.ecosystem, "lockfile_type": service.lockfile_type},
            ).returning(Service.id)
        )
        assert service_id is not None  # noqa: S101
        saved.append((service_id, service))
    return saved


def save_results(
    session: AsyncSession,
    scan_id: uuid.UUID,
    services: list[tuple[uuid.UUID, ParsedService]],
    match: MatchResult,
) -> None:
    for service_id, service in services:
        for skipped in service.skipped:
            session.add(
                SkippedPackage(
                    scan_id=scan_id,
                    service_id=service_id,
                    name=skipped.name,
                    spec=skipped.spec,
                    reason=skipped.reason,
                )
            )
    for service_id, entry in match.unchecked:
        session.add(
            SkippedPackage(
                scan_id=scan_id,
                service_id=service_id,
                name=entry.name,
                spec=entry.version,
                reason="osv_unavailable",
            )
        )
    for draft in match.findings:
        session.add(
            Finding(
                scan_id=scan_id,
                service_id=draft.service_id,
                dep_key=draft.entry.key,
                ecosystem=draft.ecosystem,
                package=draft.entry.name,
                installed_version=draft.entry.version,
                installed_version_norm=draft.installed_version_norm,
                advisory_id=draft.advisory.advisory_id,
                aliases=list(draft.advisory.ids),
                summary=draft.advisory.summary,
                cvss=draft.advisory.cvss,
                is_malicious=draft.advisory.is_malicious,
                fixed_version=draft.fixed_version,
                major_bump=draft.major_bump,
                is_dev=draft.entry.dev,
                is_direct=draft.entry.direct,
            )
        )


async def scan_steps(session: AsyncSession, scan: Scan, repo: Repo, deps: ScanDeps) -> list[str]:
    """Steps 2–8. Returns the partial reasons."""
    async with deps.github_client() as github:
        ingest = await ingest_repo(
            GitHubReader(github, deps.cache), repo.owner, repo.name, deps.settings
        )
    scan.commit_sha = ingest.commit_sha
    reasons = list(ingest.partial_reasons)
    reasons += [f"{f.lockfile_path}: not scanned: {f.error}" for f in ingest.failed_services]

    services = await save_services(session, repo.id, ingest.services)
    async with deps.osv_client() as osv:
        match = await match_services(session, osv, services)
    reasons += match.partial_reasons
    scan.osv_complete = not match.unchecked
    save_results(session, scan.id, services, match)

    limits = GraphSize(deps.settings.graph_max_nodes, deps.settings.graph_max_relationships)
    graph = await store_graph(
        deps.driver,
        str(repo.id),
        [(str(service_id), service) for service_id, service in services],
        limits,
        ingest.all_lockfiles_seen,
    )
    reasons += graph.partial_reasons

    scan.data_date = await epss_date(session)
    if scan.data_date is None:
        reasons.append(NO_EXPLOIT_DATA)
    return reasons


async def run_scan(scan_id: uuid.UUID, deps: ScanDeps) -> None:
    started = time.monotonic()
    async with deps.sessions() as session:
        scan = await session.get_one(Scan, scan_id)
        repo = await session.get_one(Repo, scan.repo_id)
        scan.status, scan.started_at = "running", datetime.now(UTC)
        await session.commit()
        try:
            reasons = await scan_steps(session, scan, repo, deps)
            scan.status = "partial" if reasons else "done"
            scan.partial_reasons = reasons
            finish(scan, started)
            await session.flush()
            # The scan counts as this repo's latest now, so scoring (and reach) includes it.
            await rescore(session, repo.user_id)
            await session.commit()
        except (GitHubError, RateLimitError) as error:
            await fail(session, scan_id, started, str(error))
        except Exception:
            logger.exception("scan %s failed", scan_id)
            await fail(session, scan_id, started, "internal error; see the server log")


def finish(scan: Scan, started: float) -> None:
    scan.finished_at = datetime.now(UTC)
    scan.duration_ms = int((time.monotonic() - started) * 1000)


async def fail(session: AsyncSession, scan_id: uuid.UUID, started: float, message: str) -> None:
    await session.rollback()
    scan = await session.get_one(Scan, scan_id)
    scan.status, scan.error = "failed", message
    finish(scan, started)
    await session.commit()


async def fail_interrupted_scans(session: AsyncSession) -> int:
    """At startup: scans left queued or running by a restart can't finish (ADR-0008)."""
    result = await session.execute(
        update(Scan)
        .where(Scan.status.in_(ACTIVE))
        .values(status="failed", error="server restarted", finished_at=func.now())
    )
    await session.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]
