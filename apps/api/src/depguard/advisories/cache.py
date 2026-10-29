"""The `advisories` table caches OSV records. A record is fetched again only when it's missing,
was never fetched successfully, or OSV reports it modified since (ADR-0004)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Text, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from depguard.advisories.cvss import best_cvss
from depguard.db.models import Advisory
from depguard.db.postgres import in_array


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def advisory_row(record: dict[str, Any]) -> dict[str, Any]:
    cvss = best_cvss(record)
    return {
        "id": record["id"],
        "aliases": sorted(set(record.get("aliases", []))),
        "summary": record.get("summary") or None,
        "cvss_score": cvss.score if cvss else None,
        "cvss_vector": cvss.vector if cvss else None,
        "cvss_version": cvss.version if cvss else None,
        "is_malicious": record["id"].startswith("MAL-"),
        "withdrawn": bool(record.get("withdrawn")),
        "modified": parse_time(record.get("modified")),
        "raw": record,
        "fetched_at": datetime.now(UTC),
    }


async def ids_to_fetch(session: AsyncSession, wanted: dict[str, str]) -> list[str]:
    """Of these IDs (ID -> `modified` from querybatch), the ones the cache can't answer."""
    rows = await session.execute(
        select(Advisory.id, Advisory.modified, Advisory.raw.is_(None)).where(
            in_array(Advisory.id, wanted, Text())
        )
    )
    cached = {advisory_id: (modified, empty) for advisory_id, modified, empty in rows}
    stale = []
    for advisory_id, modified_text in sorted(wanted.items()):
        if advisory_id not in cached:
            stale.append(advisory_id)
            continue
        cached_modified, empty = cached[advisory_id]
        reported = parse_time(modified_text)
        if empty or (reported and (cached_modified is None or reported > cached_modified)):
            stale.append(advisory_id)
    return stale


async def save(session: AsyncSession, records: list[dict[str, Any]]) -> None:
    for record in records:
        row = advisory_row(record)
        statement = insert(Advisory).values(row)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[Advisory.id],
                set_={key: statement.excluded[key] for key in row if key != "id"},
            )
        )


async def save_placeholders(session: AsyncSession, ids: list[str]) -> None:
    """IDs whose details couldn't be fetched: a row with no record (raw is null), so findings can
    point at it and the next scan tries again. An older cached record is kept as it is."""
    for advisory_id in ids:
        await session.execute(
            insert(Advisory).values(id=advisory_id).on_conflict_do_nothing(index_elements=["id"])
        )


async def load(session: AsyncSession, ids: list[str]) -> dict[str, Advisory]:
    rows = await session.scalars(select(Advisory).where(in_array(Advisory.id, ids, Text())))
    return {row.id: row for row in rows}
