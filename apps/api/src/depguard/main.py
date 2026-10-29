from fastapi import FastAPI

from depguard.routes import ingest

app = FastAPI(title="DepGuard")
app.include_router(ingest.router)


@app.get("/health")
def health() -> dict[str, str]:
    # Liveness only: it must not call the databases, or a sleeping free-tier
    # database would make Render restart a healthy API.
    return {"status": "ok"}
