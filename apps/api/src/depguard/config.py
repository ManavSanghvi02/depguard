from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo-root .env, so `make dev` (which runs inside apps/api) finds it.
# Missing in Docker, where only environment variables are used.
ROOT_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")

    github_read_token: str = ""
    # Dev-only endpoints (POST /v1/ingest) have no auth yet, so they are off unless
    # switched on locally.
    enable_dev_endpoints: bool = False

    max_lockfiles_per_repo: int = 25
    max_lockfile_bytes: int = 10_000_000
    max_entries_per_service: int = 2_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
