"""Scan step 7: store each parsed service's graph. Never fails the scan; problems become partial
reasons, because findings don't depend on the graph."""

import logging

from neo4j import AsyncDriver
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel

from depguard.graph.capacity import GraphSize
from depguard.graph.writer import remove_stale_services, write_service
from depguard.parsers.models import ParsedService

logger = logging.getLogger(__name__)

UNREACHABLE = "dependency paths unavailable: graph database unreachable"
FULL = (
    "dependency paths unavailable: graph storage full"
    " (paths shown are from the last scan that fitted, if any)"
)
FAILED = "dependency paths unavailable: graph write failed"


class ServiceGraph(BaseModel):
    service_id: str
    lockfile_path: str
    written: bool


class GraphResult(BaseModel):
    services: list[ServiceGraph]
    partial_reasons: list[str]


async def store_graph(
    driver: AsyncDriver,
    repo_id: str,
    services: list[tuple[str, ParsedService]],  # (service ID, parsed lockfile)
    limits: GraphSize,
    remove_stale: bool,  # False when the repo's file list was incomplete (truncated, over the cap)
) -> GraphResult:
    written_ids: set[str] = set()
    reasons: list[str] = []
    try:
        # First, so a moved lockfile's old copy doesn't count against the capacity check.
        # Services refused for space below are in this list, so they keep their old graph.
        if remove_stale:
            await remove_stale_services(driver, repo_id, [service_id for service_id, _ in services])
        for service_id, service in services:
            try:
                if await write_service(driver, service_id, repo_id, service, limits):
                    written_ids.add(service_id)
                else:
                    reasons.append(f"{service.lockfile_path}: {FULL}")
            except (Neo4jError, ValueError):
                # This service only: e.g. a transaction memory limit, or an edge with no entry.
                logger.exception("graph write failed for %s", service.lockfile_path)
                reasons.append(f"{service.lockfile_path}: {FAILED}")
    except DriverError:  # can't reach Neo4j at all: no point trying the other services
        logger.exception("graph database unreachable")
        reasons.append(UNREACHABLE)
    except Neo4jError:  # e.g. wrong password, or the stale-service cleanup failed
        logger.exception("graph step failed")
        reasons.append(FAILED)
    results = [
        ServiceGraph(
            service_id=service_id,
            lockfile_path=service.lockfile_path,
            written=service_id in written_ids,
        )
        for service_id, service in services
    ]
    return GraphResult(services=results, partial_reasons=reasons)
