from fastapi import FastAPI

app = FastAPI(title="DepGuard")


@app.get("/health")
def health() -> dict[str, str]:
    # Liveness only: it must not call the databases, or a sleeping free-tier
    # database would make Render restart a healthy API.
    return {"status": "ok"}
