"""Scan steps 4–6: match every entry against OSV, fetch advisory details (cached), merge aliases,
and work out each finding's fixed version. OSV failures make the scan partial, never silently
smaller (ADR-0004)."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from depguard.advisories import cache
from depguard.advisories.aliases import AdvisoryFacts, MergedAdvisory, merge
from depguard.advisories.osv import (
    DETAIL_CONCURRENCY,
    BatchResult,
    OsvError,
    PackageQuery,
    get_vuln,
    query_batch,
)
from depguard.db.models import Advisory
from depguard.http import Sleep
from depguard.parsers.models import Ecosystem, Entry, ParsedService
from depguard.versions import first_fixed, highest, is_major_bump, normalize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FindingDraft:
    service_id: uuid.UUID
    ecosystem: Ecosystem
    entry: Entry
    installed_version_norm: str
    advisory: MergedAdvisory
    fixed_version: str | None
    major_bump: bool


@dataclass
class MatchResult:
    findings: list[FindingDraft] = field(default_factory=list)
    unchecked: list[tuple[uuid.UUID, Entry]] = field(default_factory=list)  # OSV unavailable
    partial_reasons: list[str] = field(default_factory=list)


def facts(row: Advisory, ecosystem: Ecosystem, entry: Entry) -> AdvisoryFacts:
    record = row.raw or {}
    return AdvisoryFacts(
        id=row.id,
        aliases=tuple(row.aliases),
        summary=row.summary,
        cvss=row.cvss_score,
        fixed_version=first_fixed(record.get("affected", []), ecosystem, entry.name, entry.version),
    )


async def fetch_details(
    session: AsyncSession, client: httpx.AsyncClient, ids: list[str], sleep: Sleep
) -> list[str]:
    """Fetch and cache these advisories. Returns the IDs that couldn't be fetched."""
    limit = asyncio.Semaphore(DETAIL_CONCURRENCY)

    async def one(vuln_id: str) -> dict[str, object] | None:
        async with limit:
            try:
                return await get_vuln(client, vuln_id, sleep)
            except OsvError:
                logger.warning("could not fetch advisory %s", vuln_id, exc_info=True)
                return None

    records = await asyncio.gather(*(one(vuln_id) for vuln_id in ids))
    fetched = [record for record in records if record is not None]
    await cache.save(session, fetched)
    failed = sorted(set(ids) - {str(record["id"]) for record in fetched})
    await cache.save_placeholders(session, failed)
    return failed


QueryKey = tuple[str, str, str]  # (ecosystem, name, normalised version)


def unique_queries(services: list[tuple[uuid.UUID, ParsedService]]) -> dict[QueryKey, PackageQuery]:
    """One OSV query per distinct package version across all services (1.0 and 1.0.0 are one)."""
    queries: dict[QueryKey, PackageQuery] = {}
    for _, service in services:
        for entry in service.entries:
            key = (service.ecosystem, entry.name, normalize(service.ecosystem, entry.version))
            queries.setdefault(key, PackageQuery(service.ecosystem, entry.name, entry.version))
    return queries


async def match_services(
    session: AsyncSession,
    client: httpx.AsyncClient,
    services: list[tuple[uuid.UUID, ParsedService]],
    sleep: Sleep = asyncio.sleep,
) -> MatchResult:
    queries = unique_queries(services)
    batch = await query_batch(client, list(queries.values()), sleep)

    wanted: dict[str, str] = {}
    for matches in batch.matches.values():
        wanted.update(matches)
    unfetched = await fetch_details(
        session, client, await cache.ids_to_fetch(session, wanted), sleep
    )
    result = build_findings(services, queries, batch, await cache.load(session, list(wanted)))
    if unfetched:
        result.partial_reasons.append(
            f"details of {len(unfetched)} advisories could not be fetched from OSV;"
            " those findings show the advisory ID only, and their tier may be too low"
            " (no CVSS, and no CVE to look up KEV and EPSS)"
        )
    return result


def build_findings(
    services: list[tuple[uuid.UUID, ParsedService]],
    queries: dict[QueryKey, PackageQuery],
    batch: BatchResult,
    rows: dict[str, Advisory],
) -> MatchResult:
    """Turn OSV's answers into findings: per entry, merge its advisories and work out the fix.
    No I/O, so the OSV-Scanner comparison script uses it too."""
    result = MatchResult()
    failed_keys = {(q.ecosystem, q.name, normalize(q.ecosystem, q.version)) for q in batch.failed}
    if failed_keys:
        result.partial_reasons.append(
            f"{len(failed_keys)} packages could not be checked because OSV was unavailable;"
            " re-run to complete"
        )
    for service_id, service in services:
        ecosystem = service.ecosystem
        for entry in service.entries:
            norm = normalize(ecosystem, entry.version)
            key = (ecosystem, entry.name, norm)
            if key in failed_keys:
                result.unchecked.append((service_id, entry))
                continue
            ids = batch.matches.get(queries[key], {})
            members = [facts(rows[i], ecosystem, entry) for i in ids if not rows[i].withdrawn]
            for advisory in merge(members):
                # The fix that covers every merged advisory: the highest first fixed version.
                fixed = highest(ecosystem, advisory.fixed_versions)
                result.findings.append(
                    FindingDraft(
                        service_id=service_id,
                        ecosystem=ecosystem,
                        entry=entry,
                        installed_version_norm=norm,
                        advisory=advisory,
                        fixed_version=fixed,
                        major_bump=fixed is not None
                        and is_major_bump(ecosystem, entry.version, fixed),
                    )
                )
    return result
