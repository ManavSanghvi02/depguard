"""Everything the agent may see about one finding, loaded from stored data before it runs.

The tools only read from this object, and the fact checker only accepts what is in it, so the LLM
can't reach other data and can't introduce facts of its own (ADR-0013).
"""

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from neo4j import AsyncDriver
from sqlalchemy.ext.asyncio import AsyncSession

from depguard.db.models import Advisory, Repo
from depguard.graph.queries import shortest_paths
from depguard.scoring.ranking import RankedFinding

MAX_DETAILS_CHARS = 600  # advisory text is long and untrusted; the summary plus this is enough
MAX_PATHS = 3


@dataclass(frozen=True)
class FindingContext:
    finding_id: uuid.UUID
    repo_id: uuid.UUID
    repo_private: bool | None  # None (unknown) counts as private: no Gemini fallback
    ecosystem: str
    package: str
    installed_version: str
    lockfile_path: str
    fixed_version: str | None
    major_bump: bool
    is_bundled: bool
    is_dev: bool
    is_direct: bool
    is_malicious: bool
    advisory_id: str
    aliases: tuple[str, ...]
    summary: str | None
    details: str | None
    cvss: Decimal | None
    cvss_version: str | None
    in_kev: bool
    epss: Decimal | None
    epss_percentile: Decimal | None
    reach: int
    reach_complete: bool
    tier: str
    subgroup: str | None
    data_date: date | None
    # Each path from a direct dependency down to the package, as (name, version) steps.
    paths: tuple[tuple[tuple[str, str], ...], ...]


async def load_context(
    session: AsyncSession, driver: AsyncDriver, row: RankedFinding, repo: Repo
) -> FindingContext:
    finding, score = row.finding, row.score
    advisory = await session.get(Advisory, finding.advisory_id)
    raw = (advisory.raw if advisory else None) or {}
    details = raw.get("details")
    found = await shortest_paths(driver, str(finding.service_id), finding.dep_key, MAX_PATHS)
    return FindingContext(
        finding_id=finding.id,
        repo_id=repo.id,
        repo_private=repo.is_private,
        ecosystem=finding.ecosystem,
        package=finding.package,
        installed_version=finding.installed_version,
        lockfile_path=row.lockfile_path,
        fixed_version=finding.fixed_version,
        major_bump=finding.major_bump,
        is_bundled=finding.is_bundled,
        is_dev=finding.is_dev,
        is_direct=finding.is_direct,
        is_malicious=finding.is_malicious,
        advisory_id=finding.advisory_id,
        aliases=tuple(finding.aliases),
        summary=finding.summary,
        details=details[:MAX_DETAILS_CHARS] if isinstance(details, str) else None,
        cvss=score.cvss,
        cvss_version=advisory.cvss_version if advisory else None,
        in_kev=score.in_kev,
        epss=score.epss,
        epss_percentile=score.epss_percentile,
        reach=score.reach,
        reach_complete=score.reach_complete,
        tier=score.tier,
        subgroup=score.subgroup,
        data_date=score.data_date,
        paths=tuple(tuple((s.name, s.version) for s in path.steps) for path in found or []),
    )


def cache_key(context: FindingContext, prompt_version: str) -> str:
    """Same facts and prompt give the same key, so a rescan reuses the stored explanation."""
    facts = asdict(context)
    del facts["finding_id"], facts["repo_id"], facts["repo_private"]
    facts["prompt_version"] = prompt_version
    encoded = json.dumps(facts, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
