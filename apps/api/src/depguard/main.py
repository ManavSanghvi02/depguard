from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from depguard.config import get_settings
from depguard.db.neo4j import make_driver
from depguard.routes import graph, ingest


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.neo4j = make_driver(get_settings())
    yield
    await app.state.neo4j.close()


app = FastAPI(title="DepGuard", lifespan=lifespan)
app.include_router(ingest.router)
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
