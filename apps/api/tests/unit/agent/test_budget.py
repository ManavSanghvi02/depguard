"""Rate limits (ADR-0013): wait before the token budget runs out, and retry a 429 as asked."""

import asyncio

import httpx
import pytest
from fake_llm import GOOD, FakeChat, call, lodash, submit
from langchain_core.messages import AIMessage, ToolMessage

from depguard.agent.budget import TokenBudget, retry_after
from depguard.agent.graph import AgentResult, run_agent


class Clock:
    """Fake time: sleeping moves the clock instead of waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def budget(per_minute: int = 1_000) -> tuple[TokenBudget, Clock]:
    clock = Clock()
    return TokenBudget(per_minute, clock, clock.sleep), clock


def test_the_budget_waits_until_old_tokens_leave_the_minute() -> None:
    tokens, clock = budget()
    tokens.spend(700)
    clock.now = 20
    asyncio.run(tokens.wait_for(400))  # 700 + 400 > 1,000: wait for the first 700 to expire

    assert clock.slept == [40]
    assert tokens.used() == 0


def test_the_budget_does_not_wait_when_tokens_fit() -> None:
    tokens, clock = budget()
    tokens.spend(500)
    asyncio.run(tokens.wait_for(400))
    assert clock.slept == []


def test_a_call_larger_than_the_budget_still_runs_once_the_minute_is_empty() -> None:
    tokens, clock = budget()
    asyncio.run(tokens.wait_for(5_000))
    assert clock.slept == []


def rate_limit(headers: dict[str, str] | None = None, message: str = "429") -> Exception:
    response = httpx.Response(429, headers=headers, request=httpx.Request("POST", "https://x"))
    return httpx.HTTPStatusError(message, request=response.request, response=response)


@pytest.mark.parametrize(
    ("error", "seconds"),
    [
        (rate_limit({"retry-after": "2"}), 2.0),
        (rate_limit(message="Rate limit reached. Please try again in 3.87s. Need more?"), 3.87),
        (rate_limit(), None),  # a 429 that doesn't say how long
        (RuntimeError("Please try again in 3s"), None),  # not a 429
    ],
)
def test_retry_after(error: Exception, seconds: float | None) -> None:
    assert retry_after(error) == seconds


def explain(model: FakeChat, deadline_in: float = 30) -> AgentResult:
    async def go() -> AgentResult:
        deadline = asyncio.get_running_loop().time() + deadline_in
        return await run_agent(model, lodash(), [], deadline=deadline)

    return asyncio.run(go())


def test_a_rate_limit_is_retried_after_the_wait_it_asks_for() -> None:
    wait = {"retry-after": "0.01"}
    model = FakeChat(replies=[rate_limit(wait), rate_limit(wait), submit(GOOD)])
    result = explain(model)

    assert result.draft is not None
    assert len(model.calls) == 3


def test_a_third_rate_limit_is_raised() -> None:
    wait = {"retry-after": "0.01"}
    model = FakeChat(replies=[rate_limit(wait)] * 3)
    with pytest.raises(httpx.HTTPStatusError):
        explain(model)


def test_a_wait_past_the_deadline_is_not_attempted() -> None:
    model = FakeChat(replies=[rate_limit({"retry-after": "60"}), submit(GOOD)])
    with pytest.raises(httpx.HTTPStatusError):
        explain(model, deadline_in=5)
    assert len(model.calls) == 1


def test_tokens_reported_by_the_provider_are_counted() -> None:
    reply = submit(GOOD)
    reply.usage_metadata = {"input_tokens": 900, "output_tokens": 300, "total_tokens": 1_200}
    result = explain(FakeChat(replies=[reply]))
    assert result.tokens == 1_200


def test_a_repeated_tool_call_gets_a_reminder_and_reading_everything_forces_submit() -> None:
    model = FakeChat(
        replies=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "get_advisory_details", "args": {}, "id": "a"},
                    {"name": "get_dependency_path", "args": {}, "id": "p"},
                ],
            ),
            call("get_advisory_details", call_id="again"),
            call("get_fixed_version", call_id="f"),
            submit(GOOD),
        ]
    )
    explain(model)

    repeated = next(
        m for m in model.calls[2] if isinstance(m, ToolMessage) and m.tool_call_id == "again"
    )
    assert repeated.content == "Already returned above."
    assert model.tool_choices == ["any", "any", "any", "submit_explanation"]
