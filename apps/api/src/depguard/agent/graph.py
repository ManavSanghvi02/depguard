"""The explanation agent as a LangGraph graph (ADR-0013).

agent -> tools -> agent ... -> check -> done, or back to agent once with the problems found.
The LLM reads facts through the read-only tools and answers with `submit_explanation`; the check
validates the schema and runs the deterministic fact checker. Limits: MAX_TOOL_CALLS reads (then
only submitting is allowed) and MAX_ATTEMPTS submissions.

Tokens: each LLM call resends the conversation, so a tool's result is sent in full only once (a
repeated call gets a short reminder), and once every tool was read only `submit_explanation` is
offered. Each call waits for the token budget and retries a rate limit as the provider asks.
"""

import asyncio
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import ValidationError

from depguard.agent import fact_check
from depguard.agent.budget import TokenBudget, estimate_tokens, retry_after, tokens_used
from depguard.agent.context import FindingContext
from depguard.agent.prompt import SYSTEM_PROMPT, first_message
from depguard.agent.schema import SUBMIT_TOOL, ExplanationDraft
from depguard.agent.tools import READ_TOOLS, TOOL_DEFINITIONS, run_tool

MAX_TOOL_CALLS = 4
MAX_ATTEMPTS = 2  # the first submission and one retry
MAX_RATE_LIMIT_RETRIES = 2  # per LLM call, and only if the wait fits in the deadline
# Graph steps; the limits above stop well before this. It only guards against a bug.
RECURSION_LIMIT = 20
SUBMIT = "submit_explanation"


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    tool_calls: int
    read: list[str]  # tools whose result was already sent
    tokens: int
    attempts: int
    draft: ExplanationDraft | None  # set only when it passed the check
    problems: list[str]


@dataclass(frozen=True)
class AgentResult:
    draft: ExplanationDraft | None
    problems: list[str]  # why the last submission was rejected
    tokens: int  # as counted by the provider, all calls together


def build_graph(
    model: BaseChatModel,
    context: FindingContext,
    budget: TokenBudget | None = None,
    deadline: float | None = None,
) -> Any:
    any_tool = model.bind_tools([*TOOL_DEFINITIONS, SUBMIT_TOOL], tool_choice="any")
    submit_only = model.bind_tools([SUBMIT_TOOL], tool_choice=SUBMIT)

    async def agent(state: AgentState) -> dict[str, Any]:
        done_reading = set(state["read"]) >= set(READ_TOOLS)
        limit = done_reading or state["tool_calls"] >= MAX_TOOL_CALLS
        reply, tokens = await call_model(
            submit_only if limit else any_tool, state["messages"], budget, deadline
        )
        return {"messages": [reply], "tokens": state["tokens"] + tokens}

    def tools(state: AgentState) -> dict[str, Any]:
        calls = last_calls(state)
        read = list(state["read"])
        results = []
        for c in calls:
            already = c["name"] in read
            content = "Already returned above." if already else run_tool(c["name"], context)
            results.append(ToolMessage(content, tool_call_id=c["id"]))
            read.append(c["name"])
        return {"messages": results, "tool_calls": state["tool_calls"] + len(calls), "read": read}

    def check(state: AgentState) -> dict[str, Any]:
        calls = last_calls(state)
        submit = next((c for c in calls if c["name"] == SUBMIT), None)
        draft, problems = None, ["no submit_explanation call"]
        if submit is not None:
            try:
                draft = ExplanationDraft.model_validate(submit["args"])
                problems = fact_check.check(draft, context)
            except ValidationError as error:
                problems = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors()]
        feedback = (
            "Accepted."
            if not problems
            else "Rejected. Fix these and call submit_explanation again: " + "; ".join(problems)
        )
        # Every tool call needs an answer before the LLM is called again.
        replies: list[AnyMessage] = [
            ToolMessage(feedback if c is submit else "Ignored.", tool_call_id=c["id"])
            for c in calls
        ]
        return {
            "messages": replies or [HumanMessage(feedback)],
            "attempts": state["attempts"] + 1,
            "draft": None if problems else draft,
            "problems": problems,
        }

    def after_agent(state: AgentState) -> Literal["tools", "check"]:
        calls = last_calls(state)
        return "tools" if calls and all(c["name"] != SUBMIT for c in calls) else "check"

    def after_check(state: AgentState) -> Literal["agent", "__end__"]:
        if state["problems"] and state["attempts"] < MAX_ATTEMPTS:
            return "agent"
        return "__end__"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("check", check)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", after_agent)
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("check", after_check)
    return graph.compile()


async def call_model(
    bound: Any, messages: list[AnyMessage], budget: TokenBudget | None, deadline: float | None
) -> tuple[AIMessage, int]:
    """One LLM call: wait for the budget, then retry a rate limit as the provider asks."""
    estimate = estimate_tokens(list(messages))
    for retry in range(MAX_RATE_LIMIT_RETRIES + 1):
        if budget:
            await budget.wait_for(estimate)
        try:
            reply: AIMessage = await bound.ainvoke(messages)
        except Exception as error:
            wait = retry_after(error)
            loop_time = asyncio.get_running_loop().time()
            too_late = deadline is not None and loop_time + wait > deadline if wait else True
            if wait is None or retry == MAX_RATE_LIMIT_RETRIES or too_late:
                raise
            await asyncio.sleep(wait)
            continue
        tokens = tokens_used(reply, estimate)
        if budget:
            budget.spend(tokens)
        return reply, tokens
    raise AssertionError("unreachable")  # the loop returns or raises


def last_calls(state: AgentState) -> list[Any]:
    last = state["messages"][-1]
    return list(last.tool_calls) if isinstance(last, AIMessage) else []


async def run_agent(
    model: BaseChatModel,
    context: FindingContext,
    callbacks: list[BaseCallbackHandler],
    budget: TokenBudget | None = None,
    deadline: float | None = None,
) -> AgentResult:
    """LLM errors (timeouts, rate limits that can't be waited out, outages) are raised; the caller
    decides what's next. `deadline` is an event-loop time."""
    state = await build_graph(model, context, budget, deadline).ainvoke(
        {
            "messages": [SystemMessage(SYSTEM_PROMPT), HumanMessage(first_message(context))],
            "tool_calls": 0,
            "read": [],
            "tokens": 0,
            "attempts": 0,
            "draft": None,
            "problems": [],
        },
        config={"recursion_limit": RECURSION_LIMIT, "callbacks": callbacks},
    )
    return AgentResult(state["draft"], state["problems"], state["tokens"])
