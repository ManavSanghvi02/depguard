"""Dev-only scan endpoints: start a scan, read its status, read its ranked findings.

The real `POST /v1/repos/{id}/scans` and `GET /v1/scans/{id}[/findings]` replace these when auth
exists (phase 6); the pipeline and queries stay the same.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from depguard.advisories.osv import make_client as make_osv_client
from depguard.agent.explain import retry_explanation
from depguard.agent.llm import make_llm
from depguard.config import Settings
from depguard.db.models import Finding, Repo, Scan, SkippedPackage
from depguard.db.postgres import get_session
from depguard.github.cache import ByteCache
from depguard.github.client import make_client as make_github_client
from depguard.routes.dev import DEV_USER_ID, RepoRequest, ensure_dev_profile, require_dev_endpoints
from depguard.scan.pipeline import ScanAlreadyRunning, ScanDeps, run_scan, start_scan
from depguard.scoring import ranking
from depguard.scoring.score import Subgroup, Tier

router = APIRouter(prefix="/v1/dev", dependencies=[Depends(require_dev_endpoints)])

Session = Annotated[AsyncSession, Depends(get_session)]

# Shared by all scans in this process; about 32 MB at most (Render's free instance has 512 MB).
_cache = ByteCache(max_bytes=32_000_000)


class ScanStarted(BaseModel):
    scan_id: uuid.UUID


class ScanStatus(BaseModel):
    id: uuid.UUID
    owner: str
    repo: str
    status: str
    partial_reasons: list[str]
    error: str | None
    commit_sha: str | None
    data_date: date | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    findings: int
    skipped: dict[str, int]  # reason -> count


class ScoreBreakdown(BaseModel):
    in_kev: bool
    epss: float | None
    epss_percentile: float | None
    cvss: float | None
    reach: int
    reach_complete: bool  # False: a repo had no fully checked scan, reach may be low
    data_date: date | None


class ExplanationOut(BaseModel):
    # "unavailable": no LLM allowed or reachable, or the fact check failed twice; show the summary.
    status: Literal["ok", "unavailable"]
    text: str | None
    fact_check_passed: bool
    model: str | None
    cache_hit: bool
    created_at: datetime


class FindingOut(BaseModel):
    id: uuid.UUID
    lockfile_path: str
    ecosystem: str
    package: str
    installed_version: str
    fixed_version: str | None
    major_bump: bool
    is_dev: bool
    is_direct: bool
    is_bundled: bool
    advisory_id: str
    aliases: list[str]
    summary: str | None
    is_malicious: bool
    tier: Tier
    subgroup: Subgroup | None
    risk_score: float
    breakdown: ScoreBreakdown
    explanation: ExplanationOut | None  # None: not explained (not in the top 5, or still running)


def get_scan_deps(
    request: Request, settings: Annotated[Settings, Depends(require_dev_endpoints)]
) -> ScanDeps:
    if not settings.github_read_token:
        raise HTTPException(status_code=503, detail="GITHUB_READ_TOKEN is not set")
    # Clients are made inside the background task: request-scoped ones are closed by then.
    return ScanDeps(
        sessions=request.app.state.sessions,
        driver=request.app.state.neo4j,
        settings=settings,
        github_client=lambda: make_github_client(settings.github_read_token),
        osv_client=make_osv_client,
        cache=_cache,
        llm=make_llm(settings),
    )


async def owned_scan(
    session: AsyncSession, user_id: uuid.UUID, scan_id: uuid.UUID
) -> tuple[Scan, Repo]:
    """The scan if it belongs to this user; 404 otherwise, so nothing is revealed."""
    row = (
        await session.execute(
            select(Scan, Repo)
            .join(Repo, Repo.id == Scan.repo_id)
            .where(Scan.id == scan_id, Repo.user_id == user_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return row[0], row[1]


@router.post("/scans", status_code=202)
async def create_scan(
    body: RepoRequest,
    background: BackgroundTasks,
    session: Session,
    deps: Annotated[ScanDeps, Depends(get_scan_deps)],
) -> ScanStarted:
    await ensure_dev_profile(session)
    try:
        scan_id = await start_scan(session, DEV_USER_ID, body.owner, body.repo)
    except ScanAlreadyRunning as error:
        raise HTTPException(
            status_code=409, detail="a scan of this repo is already running"
        ) from error
    background.add_task(run_scan, scan_id, deps)
    return ScanStarted(scan_id=scan_id)


@router.get("/scans/{scan_id}")
async def get_scan(scan_id: uuid.UUID, session: Session) -> ScanStatus:
    return await scan_status(session, DEV_USER_ID, scan_id)


@router.get("/scans/{scan_id}/findings")
async def get_findings(
    scan_id: uuid.UUID, session: Session, tier: Tier | None = None
) -> list[FindingOut]:
    return await ranked_findings(session, DEV_USER_ID, scan_id, tier)


@router.post("/findings/{finding_id}/explanation", status_code=202)
async def retry_finding_explanation(
    finding_id: uuid.UUID,
    background: BackgroundTasks,
    session: Session,
    deps: Annotated[ScanDeps, Depends(get_scan_deps)],
) -> None:
    """A new attempt that skips the cache; the result shows up in the findings list."""
    owned = await session.scalar(
        select(Finding.id)
        .join(Scan, Scan.id == Finding.scan_id)
        .join(Repo, Repo.id == Scan.repo_id)
        .where(Finding.id == finding_id, Repo.user_id == DEV_USER_ID)
    )
    if owned is None:
        raise HTTPException(status_code=404, detail="finding not found")
    seconds = deps.settings.explanation_deadline_seconds
    background.add_task(
        retry_explanation, deps.sessions, deps.driver, deps.llm, seconds, finding_id
    )


async def scan_status(session: AsyncSession, user_id: uuid.UUID, scan_id: uuid.UUID) -> ScanStatus:
    scan, repo = await owned_scan(session, user_id, scan_id)
    findings = await session.scalar(select(func.count()).where(Finding.scan_id == scan_id))
    skipped = await session.execute(
        select(SkippedPackage.reason, func.count())
        .where(SkippedPackage.scan_id == scan_id)
        .group_by(SkippedPackage.reason)
    )
    return ScanStatus(
        id=scan.id,
        owner=repo.owner,
        repo=repo.name,
        status=scan.status,
        partial_reasons=scan.partial_reasons,
        error=scan.error,
        commit_sha=scan.commit_sha,
        data_date=scan.data_date,
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        duration_ms=scan.duration_ms,
        findings=findings or 0,
        skipped={reason: count for reason, count in skipped},
    )


async def ranked_findings(
    session: AsyncSession, user_id: uuid.UUID, scan_id: uuid.UUID, tier: Tier | None = None
) -> list[FindingOut]:
    await owned_scan(session, user_id, scan_id)
    return [to_out(row) for row in await ranking.ranked_findings(session, scan_id, tier)]


def number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def to_out(row: ranking.RankedFinding) -> FindingOut:
    finding, score, explanation = row.finding, row.score, row.explanation
    return FindingOut(
        id=finding.id,
        lockfile_path=row.lockfile_path,
        ecosystem=finding.ecosystem,
        package=finding.package,
        installed_version=finding.installed_version,
        fixed_version=finding.fixed_version,
        major_bump=finding.major_bump,
        is_dev=finding.is_dev,
        is_direct=finding.is_direct,
        is_bundled=finding.is_bundled,
        advisory_id=finding.advisory_id,
        aliases=finding.aliases,
        summary=finding.summary,
        is_malicious=finding.is_malicious,
        # Stored as text; only score.tier() ever writes them.
        tier=cast(Tier, score.tier),
        subgroup=cast(Subgroup | None, score.subgroup),
        risk_score=float(score.risk_score),
        breakdown=ScoreBreakdown(
            in_kev=score.in_kev,
            epss=number(score.epss),
            epss_percentile=number(score.epss_percentile),
            cvss=number(score.cvss),
            reach=score.reach,
            reach_complete=score.reach_complete,
            data_date=score.data_date,
        ),
        explanation=ExplanationOut(
            status=cast(Literal["ok", "unavailable"], explanation.status),
            text=explanation.text,
            fact_check_passed=explanation.fact_check_passed,
            model=explanation.model,
            cache_hit=explanation.cache_hit,
            created_at=explanation.created_at,
        )
        if explanation is not None
        else None,
    )
