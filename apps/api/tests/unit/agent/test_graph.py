import asyncio

from fake_llm import GOOD, FakeChat, call, lodash, submit
from langchain_core.messages import ToolMessage

from depguard.agent.graph import MAX_TOOL_CALLS, AgentResult, run_agent


def run(model: FakeChat) -> AgentResult:
    return asyncio.run(run_agent(model, lodash(), []))


def tool_messages(model: FakeChat) -> list[str]:
    return [str(m.content) for m in model.calls[-1] if isinstance(m, ToolMessage)]


def test_reads_tools_then_submits() -> None:
    model = FakeChat(
        replies=[call("get_advisory_details", call_id="a"), call("get_fixed_version", call_id="f"),
                 submit(GOOD)]
    )  # fmt: skip
    result = run(model)

    assert result.draft is not None and result.problems == []
    assert result.draft.what_to_do == "Upgrade lodash to 4.17.12."
    assert model.tool_choices == ["any", "any", "any"]
    advisory, fixed = tool_messages(model)
    assert '"cvss":"9.1"' in advisory and "<untrusted>Prototype Pollution" in advisory
    assert '"fixed_version":"4.17.12"' in fixed


def test_a_failed_fact_check_is_retried_once_with_the_problems() -> None:
    model = FakeChat(replies=[submit({**GOOD, "what_to_do": "Upgrade to 4.17.21."}), submit(GOOD)])
    result = run(model)

    assert result.draft is not None
    assert "unverified number or version 4.17.21" in tool_messages(model)[0]
    # The evals still see the first attempt's problem after the retry passed.
    assert result.attempts == 2
    assert result.rejected == ("unverified number or version 4.17.21",)


def test_two_failed_submissions_give_no_explanation() -> None:
    bad = {**GOOD, "summary": "See CVE-2099-0001."}
    model = FakeChat(replies=[submit(bad), submit(bad)])
    result = run(model)

    assert result.draft is None
    assert result.problems == ["unknown advisory ID CVE-2099-0001"]
    assert len(model.calls) == 2


def test_an_answer_that_breaks_the_schema_is_a_failed_attempt() -> None:
    model = FakeChat(replies=[submit({"summary": "x"}), submit({**GOOD, "extra": "no"})])
    result = run(model)

    assert result.draft is None
    assert "extra: Extra inputs are not permitted" in result.problems


def test_after_the_step_limit_only_submitting_is_allowed() -> None:
    reads = [call("get_dependency_path", call_id=f"r{i}") for i in range(MAX_TOOL_CALLS)]
    model = FakeChat(replies=[*reads, submit(GOOD)])
    result = run(model)

    assert result.draft is not None
    assert model.tool_choices == ["any"] * MAX_TOOL_CALLS + ["submit_explanation"]


def test_plain_text_without_a_tool_call_is_a_failed_attempt() -> None:
    from langchain_core.messages import AIMessage

    model = FakeChat(replies=[AIMessage(content="Here you go"), submit(GOOD)])
    assert run(model).draft is not None
