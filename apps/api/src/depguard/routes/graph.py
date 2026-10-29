"""Dev-only graph endpoints, to try the graph before auth and Postgres exist.

Off unless ENABLE_DEV_ENDPOINTS=true, like POST /v1/ingest. The real endpoints (finding paths,
"which of my services are affected?") replace them once services and users are in Postgres.
Until then, IDs are derived from the repo and lockfile path, so a re-run replaces the same graph.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from neo4j import AsyncDriver
from pydantic import BaseModel

from depguard.config import Settings
from depguard.db.neo4j import get_driver
from depguard.github.client import GitHubReader
from depguard.graph.capacity import GraphSize
from depguard.graph.queries import (
    DependencyPath,
    ServiceTree,
    repo_services,
    service_tree,
    services_containing,
    shortest_paths,
)
from depguard.parsers.models import Ecosystem
from depguard.routes.ingest import (
    OWNER_PATTERN,
    REPO_PATTERN,
    IngestRequest,
    get_reader,
    ingest_or_http_error,
    require_dev_endpoints,
)
from depguard.scan.graph import ServiceGraph, store_graph
from depguard.scan.ingest import IngestResult

router = APIRouter(prefix="/v1/dev", dependencies=[Depends(require_dev_endpoints)])

Driver = Annotated[AsyncDriver, Depends(get_driver)]


def make_repo_id(owner: str, repo: str) -> str:
    # GitHub names are case-insensitive, so Octo/Repo and octo/repo are one repo.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://github.com/{owner}/{repo}".lower()))


def make_service_id(owner: str, repo: str, lockfile_path: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{make_repo_id(owner, repo)}/{lockfile_path}"))


class GraphIngestResult(BaseModel):
    ingest: IngestResult
    graph: list[ServiceGraph]
    partial_reasons: list[str]


class ServiceMatch(BaseModel):
    service_id: str
    lockfile_path: str


@router.post("/graph")
async def ingest_into_graph(
    body: IngestRequest,
    settings: Annotated[Settings, Depends(require_dev_endpoints)],
    reader: Annotated[GitHubReader, Depends(get_reader)],
    driver: Driver,
) -> GraphIngestResult:
    result = await ingest_or_http_error(reader, body.owner, body.repo, settings)
    services = [
        (make_service_id(body.owner, body.repo, s.lockfile_path), s) for s in result.services
    ]
    limits = GraphSize(settings.graph_max_nodes, settings.graph_max_relationships)
    repo_id = make_repo_id(body.owner, body.repo)
    graph = await store_graph(driver, repo_id, services, limits, result.all_lockfiles_seen)
    return GraphIngestResult(
        ingest=result,
        graph=graph.services,
        partial_reasons=result.partial_reasons + graph.partial_reasons,
    )


@router.get("/services/{service_id}/tree")
async def get_tree(service_id: str, driver: Driver) -> ServiceTree:
    tree = await service_tree(driver, service_id)
    if tree is None:
        raise HTTPException(status_code=404, detail="service not found")
    return tree


@router.get("/services/{service_id}/paths")
async def get_paths(
    service_id: str, key: Annotated[str, Query(min_length=1)], driver: Driver
) -> list[DependencyPath]:
    paths = await shortest_paths(driver, service_id, key)
    if paths is None:
        raise HTTPException(status_code=404, detail="service or entry not found")
    return paths


@router.get("/repos/{owner}/{repo}/services")
async def get_services_containing(
    owner: Annotated[str, Path(pattern=OWNER_PATTERN)],
    repo: Annotated[str, Path(pattern=REPO_PATTERN)],
    ecosystem: Ecosystem,
    # Query parameters, because npm names can contain "/" (@babel/core).
    name: Annotated[str, Query(min_length=1)],
    version: Annotated[str, Query(min_length=1)],
    driver: Driver,
) -> list[ServiceMatch]:
    # Stands in for "the signed-in user's service IDs from Postgres".
    paths = await repo_services(driver, make_repo_id(owner, repo))
    found = await services_containing(driver, ecosystem, name, version, list(paths))
    return [ServiceMatch(service_id=sid, lockfile_path=paths[sid]) for sid in found]
