"""The LLM providers (ADR-0013): Groq first, Gemini as a fallback for public repos only, and
Langfuse tracing when its keys are set. Models are settings; switching doesn't change the graph."""

import asyncio
from dataclasses import dataclass
from functools import lru_cache

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langfuse import Langfuse, get_client
from langfuse.langchain import CallbackHandler
from pydantic import SecretStr

from depguard.agent.budget import TokenBudget
from depguard.config import Settings


@dataclass(frozen=True)
class Provider:
    name: str
    model_name: str
    model: BaseChatModel
    budget: TokenBudget | None = None  # tokens per minute, shared by every scan in this process


@dataclass(frozen=True)
class Llm:
    primary: Provider | None
    fallback: Provider | None  # only for public repos: Gemini's free tier trains on prompts
    langfuse_public_key: str | None = None

    def tracer(self) -> CallbackHandler | None:
        """A new handler per finding, so each explanation is its own trace."""
        if self.langfuse_public_key is None:
            return None
        return CallbackHandler(public_key=self.langfuse_public_key)

    async def flush(self) -> None:
        if self.langfuse_public_key is not None:
            # Blocking network call; traces are sent in the background otherwise.
            await asyncio.to_thread(get_client(public_key=self.langfuse_public_key).flush)


def make_llm(settings: Settings) -> Llm:
    # No automatic retries: a rate limit or outage moves on to the fallback (or "unavailable").
    primary = None
    if settings.groq_api_key:
        primary = Provider(
            "groq",
            settings.groq_model,
            ChatGroq(
                model=settings.groq_model,
                api_key=SecretStr(settings.groq_api_key),
                timeout=settings.llm_timeout_seconds,
                max_retries=0,
                temperature=0,
                reasoning_effort=settings.groq_reasoning_effort or None,
            ),
            shared_budget(settings.groq_model, settings.groq_tokens_per_minute),
        )
    fallback = None
    if settings.gemini_api_key:
        fallback = Provider(
            "gemini",
            settings.gemini_model,
            ChatGoogleGenerativeAI(
                model=settings.gemini_model,
                google_api_key=SecretStr(settings.gemini_api_key),
                timeout=settings.llm_timeout_seconds,
                max_retries=0,
                temperature=0,
            ),
        )
    public_key = None
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        langfuse_client(
            settings.langfuse_public_key, settings.langfuse_secret_key, settings.langfuse_host
        )
        public_key = settings.langfuse_public_key
    return Llm(primary, fallback, public_key)


@lru_cache
def shared_budget(model: str, per_minute: int) -> TokenBudget:
    return TokenBudget(per_minute)


@lru_cache
def langfuse_client(public_key: str, secret_key: str, host: str) -> Langfuse:
    """One client per process; handlers find it by its public key."""
    return Langfuse(public_key=public_key, secret_key=secret_key, host=host)
