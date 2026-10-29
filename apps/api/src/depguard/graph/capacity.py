"""Aura Free caps nodes and relationships, so a write must leave 10% headroom (spec §8.1)."""

from dataclasses import dataclass

from neo4j import AsyncDriver


@dataclass(frozen=True)
class GraphSize:
    nodes: int
    relationships: int


def has_room(current: GraphSize, removed: GraphSize, added: GraphSize, limits: GraphSize) -> bool:
    """Would the graph stay at or under 90% of both limits after replacing `removed` with `added`?

    Two writes running at the same moment could both pass; the 10% headroom absorbs that.
    """
    nodes = current.nodes - removed.nodes + added.nodes
    relationships = current.relationships - removed.relationships + added.relationships
    # Whole numbers only: x <= 0.9 * limit  <=>  10x <= 9 * limit
    return nodes * 10 <= limits.nodes * 9 and relationships * 10 <= limits.relationships * 9


async def graph_size(driver: AsyncDriver) -> GraphSize:
    # Two queries: counting both in one MATCH would multiply them. Both use Neo4j's count store.
    nodes, _, _ = await driver.execute_query("MATCH (n) RETURN count(n) AS n")
    relationships, _, _ = await driver.execute_query("MATCH ()-[r]->() RETURN count(r) AS n")
    return GraphSize(nodes=nodes[0]["n"], relationships=relationships[0]["n"])


async def service_size(driver: AsyncDriver, service_id: str) -> GraphSize:
    """What a service's current graph takes up (every edge ends at one of its Dep nodes)."""
    records, _, _ = await driver.execute_query(
        """
        OPTIONAL MATCH (s:Service {id: $id})
        OPTIONAL MATCH (d:Dep {service_id: $id})
        OPTIONAL MATCH ()-[r:DEPENDS_ON]->(d)
        RETURN count(DISTINCT s) + count(DISTINCT d) AS nodes, count(r) AS relationships
        """,
        id=service_id,
    )
    return GraphSize(nodes=records[0]["nodes"], relationships=records[0]["relationships"])
