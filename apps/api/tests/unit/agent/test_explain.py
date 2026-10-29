"""Provider choice (ADR-0013): Groq first; Gemini only when Groq fails and the repo is public."""

import asyncio

import httpx
import pytest
from fake_llm import GOOD, FakeChat, llm, lodash, submit

from depguard.agent.context import FindingContext
from depguard.agent.explain import Outcome, explain
from depguard.agent.llm import Llm


def rate_limited() -> Exception:
    return httpx.HTTPStatusError(
        "429", request=httpx.Request("POST", "https://groq"), response=httpx.Response(429)
    )


def run(models: Llm, context: FindingContext, deadline: float = 5) -> Outcome:
    return asyncio.run(explain(context, models, deadline))


def test_groq_is_used_first() -> None:
    gemini = FakeChat()
    outcome = run(llm(FakeChat(replies=[submit(GOOD)]), gemini), lodash())

    assert outcome.status == "ok" and outcome.model == "fake-groq"
    assert outcome.attempts == 1 and outcome.rejected == () and outcome.tokens > 0
    assert gemini.calls == []


def test_gemini_is_tried_when_groq_fails_on_a_public_repo() -> None:
    gemini = FakeChat(replies=[submit(GOOD)])
    outcome = run(llm(FakeChat(replies=[rate_limited()]), gemini), lodash(repo_private=False))

    assert outcome.status == "ok" and outcome.model == "fake-gemini"


@pytest.mark.parametrize("private", [True, None])
def test_gemini_is_never_called_for_a_private_or_unknown_repo(private: bool | None) -> None:
    gemini = FakeChat(replies=[submit(GOOD)])
    outcome = run(llm(FakeChat(replies=[rate_limited()]), gemini), lodash(repo_private=private))

    assert gemini.calls == []
    assert outcome == Outcome(
        "unavailable",
        error="fake-groq: HTTPStatusError; fallback not allowed: repo is not known to be public",
    )


def test_the_gemini_models_are_tried_in_order() -> None:
    overloaded = FakeChat(replies=[rate_limited()])
    second = FakeChat(replies=[submit(GOOD)])
    outcome = run(llm(FakeChat(replies=[rate_limited()]), overloaded, second), lodash())

    assert outcome.status == "ok" and outcome.model == "fake-gemini-2"
    assert len(overloaded.calls) == 1


def test_when_every_model_fails_the_explanation_is_skipped() -> None:
    models = llm(FakeChat(replies=[rate_limited()]), FakeChat(replies=[rate_limited()]),
                 FakeChat(replies=[rate_limited()]))  # fmt: skip
    outcome = run(models, lodash())

    assert outcome == Outcome(
        "unavailable",
        error="fake-groq: HTTPStatusError; fake-gemini: HTTPStatusError;"
        " fake-gemini-2: HTTPStatusError",
    )


def test_a_slow_gemini_model_is_cut_off_by_its_deadline_then_the_next_is_tried() -> None:
    slow = FakeChat(replies=[submit(GOOD)], delay=1)
    fast = FakeChat(replies=[submit(GOOD)])
    outcome = run(llm(FakeChat(replies=[rate_limited()]), slow, fast), lodash(), deadline=0.05)

    assert outcome.status == "ok" and outcome.model == "fake-gemini-2"


def test_a_failed_fact_check_does_not_use_the_fallback() -> None:
    bad = {**GOOD, "summary": "See CVE-2099-0001."}
    gemini = FakeChat(replies=[submit(GOOD)])
    outcome = run(llm(FakeChat(replies=[submit(bad), submit(bad)]), gemini), lodash())

    assert outcome.status == "unavailable" and outcome.error == "unknown advisory ID CVE-2099-0001"
    assert gemini.calls == []


def test_a_slow_provider_hits_the_deadline() -> None:
    outcome = run(llm(FakeChat(replies=[submit(GOOD)], delay=1)), lodash(), deadline=0.05)
    assert outcome == Outcome("unavailable", error="fake-groq: TimeoutError")


def test_without_keys_explanations_are_unavailable() -> None:
    assert run(llm(), lodash()) == Outcome("unavailable", error="no LLM allowed for this repo")


def test_gemini_alone_still_respects_the_privacy_rule() -> None:
    gemini = FakeChat(replies=[submit(GOOD)])
    assert run(llm(None, gemini), lodash(repo_private=True)).status == "unavailable"
    assert gemini.calls == []
