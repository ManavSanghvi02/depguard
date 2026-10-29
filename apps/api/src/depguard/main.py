import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from neo4j.exceptions import ServiceUnavailable, SessionExpired
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from depguard.config import get_settings
from depguard.db.neo4j import make_driver
from depguard.db.postgres import make_engine, make_sessions
from depguard.routes import graph, scans
from depguard.scan.pipeline import fail_interrupted_scans

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.neo4j = make_driver(settings)
    engine = make_engine(settings.database_url) if settings.database_url else None
    app.state.sessions = make_sessions(engine) if engine else None
    if app.state.sessions is not None:
        await mark_interrupted_scans(app.state.sessions)
    yield
    await app.state.neo4j.close()
    if engine is not None:
        await engine.dispose()


async def mark_interrupted_scans(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Scans that were running when the server stopped can't finish. A sleeping database must not
    stop the API from starting, so failure here is only logged."""
    try:
        async with sessions() as session:
            count = await fail_interrupted_scans(session)
        if count:
            logger.warning("marked %d interrupted scans as failed", count)
    except (OSError, SQLAlchemyError):
        logger.exception("could not check for interrupted scans")


app = FastAPI(title="DepGuard", lifespan=lifespan)
app.include_router(scans.router)
app.include_router(graph.router)


@app.exception_handler(ServiceUnavailable)
@app.exception_handler(SessionExpired)
async def graph_unreachable(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "graph database unreachable"})


@app.get("/health")
def health() -> dict[str, str]:
    # Liveness only: it must not call the databases, or a sleeping free-tier
    # database would make Render restart a healthy API.
    return {"status": "ok"}
