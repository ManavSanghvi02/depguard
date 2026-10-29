"""Read queries: a service's tree, shortest paths to an entry, and which services hold a package.

Callers pass service IDs they are allowed to see; these functions never decide that themselves.
"""

from neo4j import AsyncDriver
from pydantic import BaseModel

from depguard.parsers.common import sorted_edges
from depguard.parsers.models import Ecosystem, Edge, Entry
from depguard.parsers.names import normalize_pypi_name
from depguard.versions import normalize


class ServiceTree(BaseModel):
    service_id: str
    lockfile_path: str
    ecosystem: Ecosystem
    entries: list[Entry]
    edges: list[Edge]


class PathStep(BaseModel):
    key: str
    name: str
    version: str
    ambiguous: bool  # the edge into this step is a Poetry guess (see Edge.ambiguous)


class DependencyPath(BaseModel):
    steps: list[PathStep]  # from a direct dependency down to the target
    ambiguous: bool  # any step's edge is ambiguous


async def service_tree(driver: AsyncDriver, service_id: str) -> ServiceTree | None:
    services, _, _ = await driver.execute_query(
        "MATCH (s:Service {id: $id}) RETURN s.lockfile_path AS path, s.ecosystem AS ecosystem",
        id=service_id,
    )
    if not services:
        return None
    entries, _, _ = await driver.execute_query(
        """
        MATCH (d:Dep {service_id: $id})
        RETURN d.key AS key, d.name AS name, d.version AS version, d.dev AS dev,
               d.direct AS direct
        ORDER BY key
        """,
        id=service_id,
    )
    edges, _, _ = await driver.execute_query(
        """
        MATCH (p)-[r:DEPENDS_ON]->(c:Dep {service_id: $id})
        RETURN CASE WHEN p:Service THEN null ELSE p.key END AS parent, c.key AS child,
               r.ambiguous AS ambiguous
        """,
        id=service_id,
    )
    return ServiceTree(
        service_id=service_id,
        lockfile_path=services[0]["path"],
        ecosystem=services[0]["ecosystem"],
        entries=[Entry(**record.data()) for record in entries],
        edges=sorted_edges(
            {(r["parent"], r["child"]) for r in edges},
            {(r["parent"], r["child"]) for r in edges if r["ambiguous"]},
        ),
    )


async def shortest_paths(
    driver: AsyncDriver, service_id: str, key: str, limit: int = 3
) -> list[DependencyPath] | None:
    """Up to `limit` shortest paths from the service to the entry. None if either doesn't exist;
    an empty list if the entry exists but nothing leads to it (e.g. an extraneous npm entry)."""
    records, _, _ = await driver.execute_query(
        """
        MATCH (s:Service {id: $id}), (d:Dep {service_id: $id, key: $key})
        OPTIONAL MATCH p = allShortestPaths((s)-[:DEPENDS_ON*]->(d))
        // Neo4j returns equally short paths in no fixed order; sorting by the keys along each
        // path before the LIMIT gives the same paths every time.
        WITH p ORDER BY [n IN nodes(p) | n.key] LIMIT $limit
        RETURN [n IN tail(nodes(p)) | n {.key, .name, .version}] AS nodes,
               [r IN relationships(p) | r.ambiguous] AS ambiguous
        """,
        id=service_id,
        key=key,
        limit=limit,
    )
    if not records:
        return None
    return [
        DependencyPath(
            steps=[
                PathStep(**node, ambiguous=ambiguous)
                for node, ambiguous in zip(record["nodes"], record["ambiguous"], strict=True)
            ],
            ambiguous=any(record["ambiguous"]),
        )
        for record in records
        if record["nodes"] is not None
    ]


async def services_containing(
    driver: AsyncDriver, ecosystem: Ecosystem, name: str, version: str, service_ids: list[str]
) -> list[str]:
    """Which of these services hold this package version (uses the dep_package_norm index).
    Versions are compared normalised, so 1.0 and 1.0.0 are the same PyPI version."""
    if ecosystem == "PyPI":
        name = normalize_pypi_name(name)  # stored names are PEP 503; npm names are exact
    records, _, _ = await driver.execute_query(
        """
        MATCH (d:Dep {ecosystem: $ecosystem, name: $name, norm_version: $version})
        WHERE d.service_id IN $ids
        RETURN DISTINCT d.service_id AS id
        ORDER BY id
        """,
        ecosystem=ecosystem,
        name=name,
        version=normalize(ecosystem, version),
        ids=service_ids,
    )
    return [record["id"] for record in records]


async def repo_services(driver: AsyncDriver, repo_id: str) -> dict[str, str]:
    """A repo's services in the graph: service ID -> lockfile path."""
    records, _, _ = await driver.execute_query(
        "MATCH (s:Service {repo_id: $repo_id}) RETURN s.id AS id, s.lockfile_path AS path",
        repo_id=repo_id,
    )
    return {record["id"]: record["path"] for record in records}
