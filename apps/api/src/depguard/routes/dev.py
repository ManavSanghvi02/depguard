"""Shared pieces of the dev-only endpoints, which exist until auth arrives (phase 6).

They are off unless ENABLE_DEV_ENDPOINTS=true, because they have no auth and spend our GitHub and
OSV quota. Everything they create belongs to one fixed "dev" profile, so queries are already
scoped to a user the way the real endpoints will be.
"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from depguard.config import Settings, get_settings
from depguard.db.models import Profile

# Stands in for the signed-in user until Supabase Auth exists. github_id 0 is never a real account.
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# GitHub's naming rules. Both values go into API URLs, so nothing else is allowed.
OWNER_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$"
REPO_PATTERN = r"^[A-Za-z0-9._-]{1,100}$"


class RepoRequest(BaseModel):
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


async def ensure_dev_profile(session: AsyncSession) -> None:
    await session.execute(
        insert(Profile)
        .values(user_id=DEV_USER_ID, github_id=0, github_login="dev")
        .on_conflict_do_nothing(index_elements=[Profile.user_id])
    )
