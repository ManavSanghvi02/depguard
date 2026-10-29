"""A scan's findings in rank order (ADR-0003), each with its current score and explanation.

Callers check that the scan belongs to the user first; this module never decides that itself.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from depguard.db.models import Explanation, Finding, FindingScore, Service
from depguard.scoring.score import Tier, sort_key


@dataclass(frozen=True)
class RankedFinding:
    finding: Finding
    score: FindingScore
    lockfile_path: str
    explanation: Explanation | None


async def ranked_findings(
    session: AsyncSession, scan_id: uuid.UUID, tier: Tier | None = None
) -> list[RankedFinding]:
    """Tier, subgroup, risk score, then advisory ID and package."""
    in_scan = select(Finding.id).where(Finding.scan_id == scan_id)
    # A finding's current score and explanation are its newest rows.
    newest_score = (
        select(FindingScore)
        .where(FindingScore.finding_id.in_(in_scan))
        .ext(distinct_on(FindingScore.finding_id))
        .order_by(FindingScore.finding_id, FindingScore.created_at.desc())
        .subquery()
    )
    newest_explanation = (
        select(Explanation)
        .where(Explanation.finding_id.in_(in_scan))
        .ext(distinct_on(Explanation.finding_id))
        .order_by(Explanation.finding_id, Explanation.created_at.desc())
        .subquery()
    )
    score = aliased(FindingScore, newest_score)
    explanation = aliased(Explanation, newest_explanation)
    query = (
        select(Finding, score, Service.lockfile_path, explanation)
        .join(score, score.finding_id == Finding.id)
        .join(Service, Service.id == Finding.service_id)
        .outerjoin(explanation, explanation.finding_id == Finding.id)
        .where(Finding.scan_id == scan_id)
    )
    if tier is not None:
        query = query.where(score.tier == tier)
    rows = [RankedFinding(*row) for row in (await session.execute(query)).all()]
    return sorted(
        rows,
        key=lambda r: sort_key(
            r.score.tier,
            r.score.subgroup,
            r.score.risk_score,
            r.finding.advisory_id,
            r.finding.package,
        ),
    )
