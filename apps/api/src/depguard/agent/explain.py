"""Scan step 10 (architecture §3): explain the top findings and store one row per attempt.

It never changes the scan's status: with no LLM, or when it fails, explanations are just
"unavailable" and everything else still works (ADR-0013).
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Literal

from neo4j import AsyncDriver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from depguard.agent.context import FindingContext, cache_key, load_context
from depguard.agent.graph import run_agent
from depguard.agent.llm import Llm, Provider
from depguard.agent.prompt import PROMPT_VERSION
from depguard.db.models import Explanation, Finding, Repo, Scan
from depguard.scoring.ranking import RankedFinding, ranked_findings

logger = logging.getLogger(__name__)

TOP_N = 5


@dataclass(frozen=True)
class Outcome:
    status: Literal["ok", "unavailable"]
    text: str | None = None
    model: str | None = None
    trace_id: str | None = None
    error: str | None = None


def allowed_providers(llm: Llm, context: FindingContext) -> list[Provider]:
    """Groq, then Gemini only for a repo known to be public (ADR-0013, security.md §11)."""
    providers = [llm.primary] if llm.primary else []
    if llm.fallback and context.repo_private is False:
        providers.append(llm.fallback)
    return providers


async def explain(context: FindingContext, llm: Llm, deadline_seconds: float) -> Outcome:
    providers = allowed_providers(llm, context)
    if not providers:
        return Outcome("unavailable", error="no LLM allowed for this repo")
    errors = []
    for provider in providers:
        tracer = llm.tracer()
        try:
            deadline = asyncio.get_running_loop().time() + deadline_seconds
            async with asyncio.timeout_at(deadline):
                result = await run_agent(
                    provider.model, context, [tracer] if tracer else [], provider.budget, deadline
                )
        except Exception as error:  # outage, timeout or rate limit: try the next allowed provider
            logger.warning("explanation with %s failed: %r", provider.name, error)
            errors.append(f"{provider.name}: {type(error).__name__}")
            continue
        trace_id = tracer.last_trace_id if tracer else None
        if result.draft is None:
            # A failed fact check isn't an outage, so the fallback isn't tried.
            problems = "; ".join(result.problems)[:1_000]
            return Outcome("unavailable", None, provider.model_name, trace_id, problems)
        return Outcome("ok", result.draft.text(), provider.model_name, trace_id)
    if llm.fallback and context.repo_private is not False:
        errors.append("fallback not allowed: repo is not known to be public")
    return Outcome("unavailable", error="; ".join(errors))


async def cached(session: AsyncSession, repo_id: uuid.UUID, key: str) -> Explanation | None:
    """A passing explanation of the same facts in this repo (usually from the previous scan)."""
    return await session.scalar(
        select(Explanation)
        .join(Finding, Finding.id == Explanation.finding_id)
        .join(Scan, Scan.id == Finding.scan_id)
        .where(Scan.repo_id == repo_id, Explanation.cache_key == key, Explanation.status == "ok")
        .order_by(Explanation.created_at.desc())
        .limit(1)
    )


async def explain_finding(
    session: AsyncSession,
    driver: AsyncDriver,
    llm: Llm,
    deadline_seconds: float,
    row: RankedFinding,
    repo: Repo,
    use_cache: bool = True,
) -> Explanation:
    context = await load_context(session, driver, row, repo)
    key = cache_key(context, PROMPT_VERSION)
    hit = await cached(session, repo.id, key) if use_cache else None
    if hit is not None:
        explanation = Explanation(
            finding_id=context.finding_id,
            cache_key=key,
            data_date=context.data_date,
            status="ok",
            text=hit.text,
            model=hit.model,
            trace_id=hit.trace_id,
            fact_check_passed=True,
            cache_hit=True,
        )
    else:
        outcome = await explain(context, llm, deadline_seconds)
        explanation = Explanation(
            finding_id=context.finding_id,
            cache_key=key,
            data_date=context.data_date,
            status=outcome.status,
            text=outcome.text,
            model=outcome.model,
            trace_id=outcome.trace_id,
            fact_check_passed=outcome.status == "ok",
            cache_hit=False,
            error=outcome.error,
        )
    session.add(explanation)
    await session.commit()
    return explanation


async def explain_scan(
    sessions: async_sessionmaker[AsyncSession],
    driver: AsyncDriver,
    llm: Llm,
    deadline_seconds: float,
    scan_id: uuid.UUID,
) -> None:
    """One finding at a time: Groq's free tier allows 8,000 tokens a minute."""
    async with sessions() as session:
        scan = await session.get_one(Scan, scan_id)
        repo = await session.get_one(Repo, scan.repo_id)
        for row in (await ranked_findings(session, scan_id))[:TOP_N]:
            await explain_finding(session, driver, llm, deadline_seconds, row, repo)
    await llm.flush()


async def retry_explanation(
    sessions: async_sessionmaker[AsyncSession],
    driver: AsyncDriver,
    llm: Llm,
    deadline_seconds: float,
    finding_id: uuid.UUID,
) -> None:
    """A fresh attempt that skips the cache (the caller checked that the user owns the finding)."""
    async with sessions() as session:
        finding = await session.get_one(Finding, finding_id)
        scan = await session.get_one(Scan, finding.scan_id)
        repo = await session.get_one(Repo, scan.repo_id)
        rows = await ranked_findings(session, scan.id)
        row = next(r for r in rows if r.finding.id == finding_id)
        await explain_finding(session, driver, llm, deadline_seconds, row, repo, use_cache=False)
    await llm.flush()
