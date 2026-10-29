"""POST /v1/ingest: a dev-only endpoint to try ingestion before auth and the database exist.

It is off unless ENABLE_DEV_ENDPOINTS=true, because it has no auth and would spend our GitHub quota.
It goes away when POST /v1/repos/{id}/scans is built.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from depguard.config import Settings, get_settings
from depguard.github.cache import ByteCache
from depguard.github.client import GitHubError, GitHubReader, RepoNotFoundError, make_client
from depguard.http import RateLimitError
from depguard.scan.ingest import IngestResult, ingest_repo

router = APIRouter(prefix="/v1")

# Shared by all requests in this process; about 32 MB at most (Render's free instance has 512 MB).
_cache = ByteCache(max_bytes=32_000_000)


# GitHub's naming rules. Both values go into API URLs, so nothing else is allowed.
OWNER_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$"
REPO_PATTERN = r"^[A-Za-z0-9._-]{1,100}$"


class IngestRequest(BaseModel):
    owner: str = Field(pattern=OWNER_PATTERN)
    repo: str = Field(pattern=REPO_PATTERN)

    @field_validator("repo")
    @classmethod
    def not_dot_path(cls, value: str) -> str:
        if value in (".", ".."):
            raise ValueError("invalid repository name")
        return value


def require_dev_endpoints(settings: Annotated[Settings, Depends(get_settings)]) -> Settings:
    if not settings.enable_dev_endpoints:
        raise HTTPException(status_code=404, detail="Not Found")
    return settings


async def get_reader(
    settings: Annotated[Settings, Depends(require_dev_endpoints)],
) -> AsyncIterator[GitHubReader]:
    if not settings.github_read_token:
        raise HTTPException(status_code=503, detail="GITHUB_READ_TOKEN is not set")
    async with make_client(settings.github_read_token) as client:
        yield GitHubReader(client, _cache)


@router.post("/ingest")
async def ingest(
    body: IngestRequest,
    settings: Annotated[Settings, Depends(require_dev_endpoints)],
    reader: Annotated[GitHubReader, Depends(get_reader)],
) -> IngestResult:
    return await ingest_or_http_error(reader, body.owner, body.repo, settings)


async def ingest_or_http_error(
    reader: GitHubReader, owner: str, repo: str, settings: Settings
) -> IngestResult:
    try:
        return await ingest_repo(reader, owner, repo, settings)
    except RepoNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RateLimitError as error:
        raise HTTPException(status_code=503, detail=f"GitHub {error}") from error
    except GitHubError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
