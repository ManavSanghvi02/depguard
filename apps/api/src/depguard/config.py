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
    max_entries_per_service: int = 5_000

    # One URL per role (architecture §5.3). DATABASE_URL is the API's depguard_api role.
    database_url: str = ""
    refresh_database_url: str = ""  # the daily refresh (depguard_refresh)
    migration_database_url: str = ""  # the table owner; only for migrations and role setup

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    # AuraDB Free limits (spec §8.1). Aura doesn't report them through Cypher, so they are settings.
    graph_max_nodes: int = 200_000
    graph_max_relationships: int = 400_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
