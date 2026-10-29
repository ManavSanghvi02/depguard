"""A scripted chat model for agent tests (no network), and a sample finding to explain."""

import asyncio
import uuid
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import Field

from depguard.agent.context import FindingContext
from depguard.agent.llm import Llm, Provider

Reply = AIMessage | Exception
Script = Callable[[list[BaseMessage]], Reply]

GOOD: dict[str, Any] = {
    "summary": "lodash 4.17.4 lets an attacker change objects it merges (GHSA-jf85-cpcp-j695).",
    "why_it_matters": "Its CVSS score is 9.1 and EPSS puts it in the 92nd percentile.",
    "what_to_do": "Upgrade lodash to 4.17.12.",
    "cited_ids": ["GHSA-jf85-cpcp-j695", "CVE-2019-10744"],
}
# Passes the fact check for any finding: it states no IDs, versions or numbers.
GENERIC: dict[str, Any] = {
    "summary": "This package has a known security flaw.",
    "why_it_matters": "Attackers may be able to use it against the project.",
    "what_to_do": "Upgrade it to the fixed version DepGuard shows.",
    "cited_ids": [],
}


def call(name: str, args: dict[str, Any] | None = None, call_id: str = "c") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


def submit(args: dict[str, Any], call_id: str = "s") -> AIMessage:
    return call("submit_explanation", args, call_id)


class FakeChat(BaseChatModel):
    """Answers from a list of replies, or from a function of the messages. An Exception reply is
    raised, as a provider error would be. Records what each call saw."""

    replies: list[Any] = Field(default_factory=list)  # Any: pydantic would coerce an Exception
    script: Script | None = None
    delay: float = 0
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    tool_choices: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(
        self, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any
    ) -> Runnable[LanguageModelInput, AIMessage]:
        return self.bind(tool_choice=tool_choice)

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        raise NotImplementedError("the agent only calls the model asynchronously")

    async def _agenerate(
        self, messages: list[BaseMessage], *args: Any, **kwargs: Any
    ) -> ChatResult:
        self.calls.append(list(messages))
        self.tool_choices.append(kwargs.get("tool_choice"))
        if self.delay:
            await asyncio.sleep(self.delay)
        reply = self.script(messages) if self.script else self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])


def reads_then_submits(args: dict[str, Any]) -> Script:
    """Reads the advisory first, then submits `args`, for every finding."""

    def script(messages: list[BaseMessage]) -> Reply:
        read = any(getattr(m, "tool_call_id", None) == "read" for m in messages)
        return submit(args) if read else call("get_advisory_details", call_id="read")

    return script


def llm(primary: FakeChat | None = None, fallback: FakeChat | None = None) -> Llm:
    return Llm(
        Provider("groq", "fake-groq", primary) if primary else None,
        Provider("gemini", "fake-gemini", fallback) if fallback else None,
    )


def lodash(**changes: Any) -> FindingContext:
    """Real facts for lodash 4.17.4 in nodejs-goof (EPSS of 2026-10-28)."""
    values: dict[str, Any] = {
        "finding_id": uuid.uuid4(),
        "repo_id": uuid.uuid4(),
        "repo_private": False,
        "ecosystem": "npm",
        "package": "lodash",
        "installed_version": "4.17.4",
        "lockfile_path": "package-lock.json",
        "fixed_version": "4.17.12",
        "major_bump": False,
        "is_bundled": False,
        "is_dev": False,
        "is_direct": True,
        "is_malicious": False,
        "advisory_id": "GHSA-jf85-cpcp-j695",
        "aliases": ("CVE-2019-10744", "GHSA-jf85-cpcp-j695"),
        "summary": "Prototype Pollution in lodash",
        "details": "Versions of lodash before 4.17.12 are vulnerable to Prototype Pollution.",
        "cvss": Decimal("9.1"),
        "cvss_version": "3.1",
        "in_kev": False,
        "epss": Decimal("0.050"),
        "epss_percentile": Decimal("0.922"),
        "reach": 1,
        "reach_complete": True,
        "tier": "fix_soon",
        "subgroup": "epss",
        "data_date": date(2026, 10, 28),
        "paths": ((("lodash", "4.17.4"),),),
    }
    values.update(changes)
    return FindingContext(**values)
