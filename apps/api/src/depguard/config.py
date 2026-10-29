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

    # Explanations (ADR-0013). Without a Groq key every explanation is "unavailable".
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    # gpt-oss thinks before answering, and those tokens count against the limit; "" = model default.
    groq_reasoning_effort: str = "low"
    groq_tokens_per_minute: int = 7_500  # the free limit is 8,000; kept below it on purpose
    # Fallback for public repos only: Gemini's free tier uses prompts to improve Google's products.
    gemini_api_key: str = ""
    # Tried in order, comma-separated: the first that answers in time explains the finding.
    # gemini-3.5-flash is deprecated and routed to 3.6 by Google, so 3.6 is named directly.
    gemini_models: str = "gemini-3.6-flash,gemini-3.8-flash"
    # Short, so an overloaded model fails fast and the next one (or "unavailable") follows.
    # 10 s was too short in the Phase 4b run: tool calls took 10-15 s under load.
    gemini_timeout_seconds: float = 20  # one Gemini call
    llm_timeout_seconds: float = 20  # one Groq call
    # Per provider for one finding (all its calls and the retry); each fallback gets its own.
    explanation_deadline_seconds: float = 90
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
