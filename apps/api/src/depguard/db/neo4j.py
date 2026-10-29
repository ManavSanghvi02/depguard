"""The Neo4j driver. One per process, created at startup; creating it doesn't connect, so the API
starts (and /health answers) even when Neo4j is asleep or down."""

from fastapi import Request
from neo4j import AsyncDriver, AsyncGraphDatabase

from depguard.config import Settings


def make_driver(settings: Settings) -> AsyncDriver:
    return AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )


def get_driver(request: Request) -> AsyncDriver:
    driver: AsyncDriver = request.app.state.neo4j
    return driver
