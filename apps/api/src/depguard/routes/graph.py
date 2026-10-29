"""Dev-only graph endpoints: a service's tree, paths to an entry, and which of a repo's services
hold a package version. Off unless ENABLE_DEV_ENDPOINTS=true.

Service IDs come from Postgres and are the same in Neo4j. Lookups only search services that belong
to the (dev) user, as the real endpoints will (security.md §7).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from neo4j import AsyncDriver
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from depguard.db.models import Repo, Service
from depguard.db.neo4j import get_driver
from depguard.db.postgres import get_session
from depguard.graph.queries import (
    DependencyPath,
    ServiceTree,
    service_tree,
    services_containing,
    shortest_paths,
)
from depguard.parsers.models import Ecosystem
from depguard.routes.dev import DEV_USER_ID, OWNER_PATTERN, REPO_PATTERN, require_dev_endpoints

router = APIRouter(prefix="/v1/dev", dependencies=[Depends(require_dev_endpoints)])

Driver = Annotated[AsyncDriver, Depends(get_driver)]
Session = Annotated[AsyncSession, Depends(get_session)]


class ServiceMatch(BaseModel):
    service_id: str
    lockfile_path: str


async def owned_service(session: AsyncSession, service_id: uuid.UUID) -> None:
    found = await session.scalar(
        select(Service.id)
        .join(Repo, Repo.id == Service.repo_id)
        .where(Service.id == service_id, Repo.user_id == DEV_USER_ID)
    )
    if found is None:
        raise HTTPException(status_code=404, detail="service not found")


@router.get("/services/{service_id}/tree")
async def get_tree(service_id: uuid.UUID, session: Session, driver: Driver) -> ServiceTree:
    await owned_service(session, service_id)
    tree = await service_tree(driver, str(service_id))
    if tree is None:
        raise HTTPException(status_code=404, detail="no graph stored for this service")
    return tree


@router.get("/services/{service_id}/paths")
async def get_paths(
    service_id: uuid.UUID,
    key: Annotated[str, Query(min_length=1)],
    session: Session,
    driver: Driver,
) -> list[DependencyPath]:
    await owned_service(session, service_id)
    paths = await shortest_paths(driver, str(service_id), key)
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
    session: Session,
    driver: Driver,
) -> list[ServiceMatch]:
    rows = await session.execute(
        select(Service.id, Service.lockfile_path)
        .join(Repo, Repo.id == Service.repo_id)
        .where(Repo.user_id == DEV_USER_ID, Repo.owner == owner.lower(), Repo.name == repo.lower())
    )
    paths = {str(service_id): path for service_id, path in rows}
    found = await services_containing(driver, ecosystem, name, version, list(paths))
    return [ServiceMatch(service_id=sid, lockfile_path=paths[sid]) for sid in found]
