"""Merge advisories that describe the same problem (GHSA / PYSEC / CVE / MAL aliases), so one
problem is one finding. Two advisories are merged when their IDs or aliases overlap, also through a
third one (A~B and B~C puts A, B, C together)."""

from dataclasses import dataclass
from decimal import Decimal

# The ID shown for a merged group: GHSA first (best package data), then PYSEC, then MAL.
PREFIX_ORDER = ("GHSA-", "PYSEC-", "MAL-")


@dataclass(frozen=True)
class AdvisoryFacts:
    id: str
    aliases: tuple[str, ...]
    summary: str | None
    cvss: Decimal | None
    fixed_version: str | None  # for the entry being matched; computed by versions.first_fixed


@dataclass(frozen=True)
class MergedAdvisory:
    advisory_id: str  # the representative; always an OSV ID we have a row for
    ids: tuple[str, ...]  # every ID and alias in the group, sorted
    summary: str | None
    cvss: Decimal | None  # the highest in the group
    is_malicious: bool
    fixed_versions: tuple[str, ...]  # each member's first fixed version (the caller picks the max)

    @property
    def cve_ids(self) -> list[str]:
        return [i for i in self.ids if i.startswith("CVE-")]


def representative(ids: list[str]) -> str:
    def rank(advisory_id: str) -> tuple[int, str]:
        for position, prefix in enumerate(PREFIX_ORDER):
            if advisory_id.startswith(prefix):
                return position, advisory_id
        return len(PREFIX_ORDER), advisory_id

    return min(ids, key=rank)


def merge(advisories: list[AdvisoryFacts]) -> list[MergedAdvisory]:
    """Group by overlapping IDs. The result is sorted by advisory_id, so it's deterministic."""
    groups: list[tuple[set[str], list[AdvisoryFacts]]] = []
    for advisory in sorted(advisories, key=lambda a: a.id):
        names = {advisory.id, *advisory.aliases}
        overlapping = [group for group in groups if group[0] & names]
        merged_names, members = names, [advisory]
        for group in overlapping:
            merged_names |= group[0]
            members += group[1]
            groups.remove(group)
        groups.append((merged_names, members))

    result = []
    for names, members in groups:
        scores = [m.cvss for m in members if m.cvss is not None]
        main = representative([m.id for m in members])
        summary = next(m.summary for m in members if m.id == main)
        result.append(
            MergedAdvisory(
                advisory_id=main,
                ids=tuple(sorted(names)),
                summary=summary or next((m.summary for m in members if m.summary), None),
                cvss=max(scores) if scores else None,
                is_malicious=any(name.startswith("MAL-") for name in names),
                fixed_versions=tuple(m.fixed_version for m in members if m.fixed_version),
            )
        )
    return sorted(result, key=lambda m: m.advisory_id)
