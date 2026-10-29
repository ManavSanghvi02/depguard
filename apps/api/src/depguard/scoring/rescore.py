"""Score the findings of every repo's latest scan, inserting a finding_scores row only when an
input changed (ADR-0003). Used after each scan (one user) and by the daily refresh (everyone).

Runs as depguard_api or depguard_refresh, so it only reads what the refresh role may read.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Text, func, select
from sqlalchemy.dialects.postgresql import UUID, distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Subquery

from depguard.db.models import EpssScore, Finding, FindingScore, KevEntry, Repo, Scan
from depguard.db.postgres import in_array
from depguard.scoring.score import ScoreInputs, risk_score, tier

FINISHED = ("done", "partial")


@dataclass(frozen=True)
class LatestFinding:
    finding: Finding
    user_id: uuid.UUID


def latest_scans(user_id: uuid.UUID | None, fully_checked: bool = False) -> Subquery:
    """Each repo's most recent finished scan, or most recent fully checked one (scan ID, repo ID,
    user ID)."""
    query = (
        select(Scan.id, Scan.repo_id, Repo.user_id)
        .join(Repo, Repo.id == Scan.repo_id)
        .where(Scan.status.in_(FINISHED))
        .ext(distinct_on(Scan.repo_id))
        .order_by(Scan.repo_id, Scan.finished_at.desc(), Scan.id)
    )
    if fully_checked:
        query = query.where(Scan.osv_complete.is_(True))
    if user_id is not None:
        query = query.where(Repo.user_id == user_id)
    return query.subquery()


async def latest_findings(session: AsyncSession, user_id: uuid.UUID | None) -> list[LatestFinding]:
    """The findings to score: each repo's latest finished scan, complete or not."""
    latest = latest_scans(user_id)
    rows = await session.execute(
        select(Finding, latest.c.user_id).join(latest, latest.c.id == Finding.scan_id)
    )
    return [LatestFinding(finding, user) for finding, user in rows]


@dataclass
class Reach:
    services: dict[tuple[object, ...], set[uuid.UUID]]
    incomplete_users: set[uuid.UUID]  # some repo had no fully checked scan to count from

    def count(self, item: LatestFinding) -> int:
        # The finding's own service always counts, even if its scan isn't the one counted from.
        return len(self.services.get(reach_key(item), set()) | {item.finding.service_id})

    def complete(self, item: LatestFinding) -> bool:
        return item.user_id not in self.incomplete_users


async def reach_sources(session: AsyncSession, user_id: uuid.UUID | None) -> Reach:
    """Reach counts each repo's latest *fully checked* scan, so one OSV outage can't make other
    repos' reach drop. A repo with no fully checked scan yet counts its latest partial scan, and
    that user's reach is marked incomplete."""
    latest = latest_scans(user_id)
    checked = latest_scans(user_id, fully_checked=True)
    repos = await session.execute(
        select(latest.c.repo_id, latest.c.user_id, latest.c.id, checked.c.id).outerjoin(
            checked, checked.c.repo_id == latest.c.repo_id
        )
    )
    scan_ids, incomplete = [], set()
    for _, owner, latest_id, checked_id in repos:
        scan_ids.append(checked_id or latest_id)
        if checked_id is None:
            incomplete.add(owner)

    rows = await session.execute(
        select(
            Repo.user_id,
            Finding.ecosystem,
            Finding.package,
            Finding.installed_version_norm,
            Finding.advisory_id,
            Finding.service_id,
        )
        .join(Scan, Scan.id == Finding.scan_id)
        .join(Repo, Repo.id == Scan.repo_id)
        .where(in_array(Finding.scan_id, scan_ids, UUID()))
    )
    services: dict[tuple[object, ...], set[uuid.UUID]] = defaultdict(set)
    for owner, ecosystem, package, version, advisory, service_id in rows:
        services[(owner, ecosystem, package, version, advisory)].add(service_id)
    return Reach(services, incomplete)


def reach_key(item: LatestFinding) -> tuple[object, ...]:
    f = item.finding
    return item.user_id, f.ecosystem, f.package, f.installed_version_norm, f.advisory_id


async def exploit_data(
    session: AsyncSession, cve_ids: set[str]
) -> tuple[set[str], dict[str, EpssScore]]:
    kev = set(
        await session.scalars(
            select(KevEntry.cve_id).where(in_array(KevEntry.cve_id, cve_ids, Text()))
        )
    )
    epss = await session.scalars(
        select(EpssScore).where(in_array(EpssScore.cve_id, cve_ids, Text()))
    )
    return kev, {row.cve_id: row for row in epss}


async def latest_scores(
    session: AsyncSession, finding_ids: list[uuid.UUID]
) -> dict[uuid.UUID, FindingScore]:
    rows = await session.scalars(
        select(FindingScore)
        .where(in_array(FindingScore.finding_id, finding_ids, UUID()))
        .ext(distinct_on(FindingScore.finding_id))
        .order_by(FindingScore.finding_id, FindingScore.created_at.desc())
    )
    return {row.finding_id: row for row in rows}


async def epss_date(session: AsyncSession) -> date | None:
    data_date: date | None = await session.scalar(select(func.max(EpssScore.data_date)))
    return data_date


def inputs_for(
    finding: Finding, reach: int, kev: set[str], epss: dict[str, EpssScore]
) -> ScoreInputs:
    # A merged advisory can carry several CVEs: in KEV if any is; the highest EPSS.
    cves = [alias for alias in finding.aliases if alias.startswith("CVE-")]
    scores = [epss[cve] for cve in cves if cve in epss]
    best = max(scores, key=lambda row: (row.score, row.percentile), default=None)
    return ScoreInputs(
        is_malicious=finding.is_malicious,
        in_kev=any(cve in kev for cve in cves),
        epss=best.score if best else None,
        epss_percentile=best.percentile if best else None,
        cvss=finding.cvss,
        reach=reach,
        is_dev=finding.is_dev,
    )


def unchanged(previous: FindingScore | None, inputs: ScoreInputs, reach_complete: bool) -> bool:
    if previous is None:
        return False
    before: tuple[bool, Decimal | None, Decimal | None, Decimal | None, int, bool] = (
        previous.in_kev,
        previous.epss,
        previous.epss_percentile,
        previous.cvss,
        previous.reach,
        previous.reach_complete,
    )
    return before == (
        inputs.in_kev,
        inputs.epss,
        inputs.epss_percentile,
        inputs.cvss,
        inputs.reach,
        reach_complete,
    )


async def rescore(session: AsyncSession, user_id: uuid.UUID | None = None) -> int:
    """Score the latest findings of one user (or everyone). Returns how many rows were added.
    The caller commits."""
    findings = await latest_findings(session, user_id)
    if not findings:
        return 0
    reach = await reach_sources(session, user_id)
    cves = {a for item in findings for a in item.finding.aliases if a.startswith("CVE-")}
    kev, epss = await exploit_data(session, cves)
    previous = await latest_scores(session, [item.finding.id for item in findings])
    data_date = await epss_date(session)

    added = 0
    for item in findings:
        inputs = inputs_for(item.finding, reach.count(item), kev, epss)
        reach_complete = reach.complete(item)
        if unchanged(previous.get(item.finding.id), inputs, reach_complete):
            continue
        tier_name, subgroup = tier(inputs)
        session.add(
            FindingScore(
                finding_id=item.finding.id,
                data_date=data_date,
                in_kev=inputs.in_kev,
                epss=inputs.epss,
                epss_percentile=inputs.epss_percentile,
                cvss=inputs.cvss,
                reach=inputs.reach,
                reach_complete=reach_complete,
                tier=tier_name,
                subgroup=subgroup,
                risk_score=risk_score(inputs),
            )
        )
        added += 1
    await session.flush()
    return added
