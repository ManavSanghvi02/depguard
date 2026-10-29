"""Writes a service's graph: the old one is replaced in a single transaction, so a reader never
sees half a tree."""

from typing import Any

from neo4j import AsyncDriver, AsyncManagedTransaction

from depguard.graph.capacity import GraphSize, graph_size, has_room, service_size
from depguard.graph.schema import ensure_schema
from depguard.parsers.models import ParsedService
from depguard.versions import normalize

BATCH_SIZE = 1_000  # rows per UNWIND, so no single query carries a 5,000-entry list


def check_edges(service: ParsedService) -> None:
    """Every edge must join two entries of this service; anything else is a parser bug."""
    keys = {entry.key for entry in service.entries}
    for edge in service.edges:
        if edge.child_key not in keys or (
            edge.parent_key is not None and edge.parent_key not in keys
        ):
            raise ValueError(f"edge {edge.parent_key!r} -> {edge.child_key!r} has no entry")


def batches(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [rows[i : i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]


async def write_service(
    driver: AsyncDriver, service_id: str, repo_id: str, service: ParsedService, limits: GraphSize
) -> bool:
    """Replace the service's graph if there's room. False (and nothing written) if there isn't."""
    check_edges(service)
    await ensure_schema(driver)
    added = GraphSize(nodes=len(service.entries) + 1, relationships=len(service.edges))
    removed = await service_size(driver, service_id)
    if not has_room(await graph_size(driver), removed, added, limits):
        return False
    async with driver.session() as session:
        await session.execute_write(replace_service, service_id, repo_id, service)
    return True


async def replace_service(
    tx: AsyncManagedTransaction, service_id: str, repo_id: str, service: ParsedService
) -> None:
    await tx.run(
        """
        MERGE (s:Service {id: $id})
        SET s.repo_id = $repo_id, s.lockfile_path = $path, s.ecosystem = $ecosystem,
            s.lockfile_type = $type
        """,
        id=service_id,
        repo_id=repo_id,
        path=service.lockfile_path,
        ecosystem=service.ecosystem,
        type=service.lockfile_type,
    )
    await tx.run("MATCH (d:Dep {service_id: $id}) DETACH DELETE d", id=service_id)

    entries = [
        {**entry.model_dump(), "norm_version": normalize(service.ecosystem, entry.version)}
        for entry in service.entries
    ]
    for rows in batches(entries):
        await tx.run(
            """
            UNWIND $rows AS row
            CREATE (:Dep {service_id: $id, key: row.key, ecosystem: $ecosystem, name: row.name,
                          version: row.version, norm_version: row.norm_version, dev: row.dev,
                          direct: row.direct})
            """,
            rows=rows,
            id=service_id,
            ecosystem=service.ecosystem,
        )

    direct = [e.model_dump() for e in service.edges if e.parent_key is None]
    for rows in batches(direct):
        await tx.run(
            """
            MATCH (s:Service {id: $id})
            UNWIND $rows AS row
            MATCH (d:Dep {service_id: $id, key: row.child_key})
            CREATE (s)-[:DEPENDS_ON {ambiguous: row.ambiguous}]->(d)
            """,
            rows=rows,
            id=service_id,
        )

    transitive = [e.model_dump() for e in service.edges if e.parent_key is not None]
    for rows in batches(transitive):
        await tx.run(
            """
            UNWIND $rows AS row
            MATCH (p:Dep {service_id: $id, key: row.parent_key})
            MATCH (c:Dep {service_id: $id, key: row.child_key})
            CREATE (p)-[:DEPENDS_ON {ambiguous: row.ambiguous}]->(c)
            """,
            rows=rows,
            id=service_id,
        )


async def remove_stale_services(driver: AsyncDriver, repo_id: str, keep_ids: list[str]) -> None:
    """Delete the graphs of a repo's services that are gone or failed in this scan."""
    await driver.execute_query(
        """
        MATCH (s:Service {repo_id: $repo_id})
        WHERE NOT s.id IN $keep
        OPTIONAL MATCH (d:Dep {service_id: s.id})
        DETACH DELETE d, s
        """,
        repo_id=repo_id,
        keep=keep_ids,
    )
