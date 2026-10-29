"""Rate-limit handling for LLM calls (ADR-0013).

- TokenBudget: a tokens-per-minute budget per provider, so a call waits *before* it would hit the
  provider's limit. One process and one finding at a time, so a simple sliding window is enough.
- retry_after: how long a 429 asks us to wait, if it says.
"""

import asyncio
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable

from langchain_core.messages import AIMessage, BaseMessage

WINDOW_SECONDS = 60.0
OUTPUT_RESERVE = 400  # tokens kept free for the reply, which isn't known before the call
# Groq's message when it doesn't send a header: "Please try again in 3.87s."
RETRY_IN = re.compile(r"try again in (\d+(?:\.\d+)?)s")


class TokenBudget:
    def __init__(
        self,
        per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.per_minute = per_minute
        self.clock = clock
        self.sleep = sleep
        self.spent: deque[tuple[float, int]] = deque()  # (when, tokens)

    def used(self) -> int:
        cutoff = self.clock() - WINDOW_SECONDS
        while self.spent and self.spent[0][0] <= cutoff:
            self.spent.popleft()
        return sum(tokens for _, tokens in self.spent)

    async def wait_for(self, tokens: int) -> None:
        """Wait until `tokens` more fit in the last minute's budget."""
        while self.spent and self.used() + tokens > self.per_minute:
            await self.sleep(self.spent[0][0] + WINDOW_SECONDS - self.clock())

    def spend(self, tokens: int) -> None:
        self.spent.append((self.clock(), tokens))


def estimate_tokens(messages: list[BaseMessage]) -> int:
    """About 4 characters per token, plus room for the reply. Only used to decide whether to
    wait; the real count from the provider is what gets spent."""
    return (
        sum(len(str(m.content)) + len(str(getattr(m, "tool_calls", ""))) for m in messages) // 4
        + OUTPUT_RESERVE
    )


def tokens_used(reply: AIMessage, estimate: int) -> int:
    usage = reply.usage_metadata
    return usage["total_tokens"] if usage else estimate


def retry_after(error: BaseException) -> float | None:
    """Seconds a rate-limit error asks us to wait; None if it isn't one or doesn't say."""
    response = getattr(error, "response", None)
    status = getattr(error, "status_code", None) or getattr(response, "status_code", None)
    if status != 429:
        return None
    header = getattr(response, "headers", {}).get("retry-after")
    try:
        if header is not None:
            return float(header)
    except ValueError:
        pass
    match = RETRY_IN.search(str(error))
    return float(match.group(1)) if match else None
