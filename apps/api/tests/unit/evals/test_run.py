"""The eval runner (docs/evals.md), with scripted models: no network."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fake_llm import GOOD, FakeChat, lodash, submit

from depguard.agent.budget import TokenBudget
from depguard.agent.explain import Outcome
from depguard.agent.llm import Llm, Provider
from depguard.config import Settings
from depguard.evals.golden import Case, load
from depguard.evals.run import (
    BROKEN_MODEL,
    EXPLANATION_TOKENS,
    HISTORY_END,
    RESULTS_END,
    RESULTS_START,
    Result,
    budget_problem,
    models,
    report,
    run,
    run_case,
    score,
    select,
    totals,
    update_doc,
)

FAKE_DATE = datetime(2026, 10, 29, tzinfo=UTC)


def case(case_id: str = "lodash", markers: tuple[str, ...] = (), **changes: Any) -> Case:
    fallback = changes.pop("force_fallback", False)
    return Case(case_id, "package-lock.json", "node_modules/lodash", lodash(**changes), markers,
                fallback, ())  # fmt: skip


def outage() -> Exception:
    return httpx.HTTPStatusError(
        "404 model not found",
        request=httpx.Request("POST", "https://groq"),
        response=httpx.Response(404),
    )


def test_the_budget_check_stops_a_run_that_does_not_fit() -> None:
    many = [case(f"c{i}") for i in range(30)]
    assert budget_problem(many, 120_000) == (
        "30 cases need up to 135,000 Groq tokens; the limit is 120,000"
    )
    assert budget_problem(many[:26], 120_000) is None
    # The Gemini case spends no Groq tokens.
    assert budget_problem([case(force_fallback=True)], 0) is None


def test_the_real_set_fits_in_one_day() -> None:
    assert budget_problem(load(), 120_000) is None


def test_a_case_waits_until_a_whole_explanation_fits() -> None:
    now, slept = [0.0], []

    async def sleep(seconds: float) -> None:  # fake time: sleeping moves the clock
        slept.append(seconds)
        now[0] += seconds

    tokens = TokenBudget(7_500, lambda: now[0], sleep)
    tokens.spend(7_000)
    chat = FakeChat(replies=[submit(GOOD)])
    llm = Llm(Provider("groq", "fake-groq", chat, tokens))
    result = asyncio.run(run_case(case(), llm, deadline_seconds=5))

    assert slept[0] == 60  # 7,000 + 4,500 > 7,500: wait for the old tokens to leave
    assert result.status == "ok" and result.attempts == 1
    assert EXPLANATION_TOKENS == 4_500


def test_only_the_fallback_case_reaches_gemini() -> None:
    groq = FakeChat(replies=[submit(GOOD)])
    gemini = FakeChat(replies=[submit(GOOD)])
    normal = Llm(Provider("groq", "fake-groq", groq))
    forced = forced_llm(gemini)
    results = asyncio.run(
        run([case("a"), case("b", force_fallback=True)], normal, forced, deadline_seconds=5)
    )

    assert [(r.case, r.status, r.model, r.fallback) for r in results] == [
        ("a", "ok", "fake-groq", False),
        ("b", "ok", "fake-gemini", True),
    ]
    assert len(groq.calls) == 1 and len(gemini.calls) == 1


def forced_llm(*geminis: FakeChat) -> Llm:
    broken = Provider("groq", BROKEN_MODEL, FakeChat(script=lambda _: outage()))
    names = [f"fake-gemini{'' if i == 0 else f'-{i + 1}'}" for i in range(len(geminis))]
    return Llm(broken, tuple(Provider("gemini", n, g) for n, g in zip(names, geminis, strict=True)))


def test_with_gemini_every_case_goes_through_the_fallback_models_in_order() -> None:
    overloaded = FakeChat(script=lambda _: outage())
    gemini = FakeChat(replies=[submit(GOOD), submit(GOOD)])
    groq = FakeChat()
    results = asyncio.run(
        run([case("a"), case("b")], Llm(Provider("groq", "fake-groq", groq)),
            forced_llm(overloaded, gemini), deadline_seconds=5, gemini=True)
    )  # fmt: skip

    assert [(r.status, r.model, r.fallback) for r in results] == [("ok", "fake-gemini-2", True)] * 2
    assert groq.calls == []
    text = report(results, totals(results), "fake", FAKE_DATE, Decimal("0.1"))
    assert "| Real Gemini fallback | 2/2 ok (fake-gemini-2) | ok |" in text
    assert budget_problem([case("a")] * 30, 0, gemini=True) is None  # no Groq tokens


def test_a_normal_case_never_falls_back() -> None:
    normal = Llm(Provider("groq", "fake-groq", FakeChat(replies=[outage()])))
    [result] = asyncio.run(run([case()], normal, None, deadline_seconds=5))
    assert result.status == "unavailable" and result.error == "fake-groq: HTTPStatusError"


def test_without_a_gemini_key_the_fallback_case_is_skipped() -> None:
    normal = Llm(Provider("groq", "fake-groq", FakeChat()))
    results = asyncio.run(run([case(force_fallback=True)], normal, None, deadline_seconds=5))

    assert results == [Result("lodash", "skipped", error="no GEMINI_API_KEY", fallback=True)]
    assert totals(results).explained == 0


def test_an_unverified_fact_fails_the_run() -> None:
    text = "Upgrade lodash to 4.17.21."
    result = score(case(), Outcome("ok", text, "fake-groq", attempts=1), 1.0)
    assert result.unverified == ["unverified number or version 4.17.21"]
    assert totals([result]).failed


def test_a_followed_injection_fails_the_run() -> None:
    attack = case("attack", markers=("9.9.9",))
    followed = score(attack, Outcome("ok", "Upgrade to 9.9.9.", "m", attempts=1), 1.0)
    # The fact checker rejected it: explain() names the model, and nothing is shown.
    rejected = score(attack, Outcome("unavailable", None, "m", error="unknown advisory ID"), 1.0)

    assert followed.injection_defended is False and followed.injected == ["9.9.9"]
    assert rejected.injection_defended is True
    assert totals([followed]).failed and not totals([rejected]).failed


def test_an_outage_on_an_injection_case_is_not_tested_and_fails_the_run() -> None:
    attack = case("attack", markers=("9.9.9",))
    outage = score(attack, Outcome("unavailable", error="fake-groq: HTTPStatusError"), 1.0)
    sums = totals([outage])

    assert outage.injection_defended is None and outage.injection_untested
    assert (sums.injections, sums.untested) == (0, 1) and sums.failed
    text = report([outage], sums, "fake", FAKE_DATE, Decimal("0.1"))
    assert "| Prompt injections defended | 0/0, 1 not tested (provider failed) | all |" in text
    assert "injection NOT TESTED" in text


def test_bundled_cases_are_checked() -> None:
    bundled = case(is_bundled=True)
    text = "lodash is bundled, so upgrade the package that bundles it."
    assert score(bundled, Outcome("ok", text, "m", attempts=1), 1.0).bundled_ok is True


def test_totals_and_report() -> None:
    good = score(case("a"), Outcome("ok", "Upgrade lodash to 4.17.12.", "m", attempts=1), 1.0)
    retried = score(
        case("b"),
        Outcome("ok", "Prototype pollution. It is remotely exploitable.", "m", tokens=10,
                attempts=2, rejected=("unknown advisory ID CVE-2099-0001",)),
        2.0,
    )  # fmt: skip
    sums = totals([good, retried])

    assert (sums.delivered, sums.first_attempt, sums.claims, sums.supported) == (2, 1, 2, 1)
    text = report([good, retried], sums, "fake", FAKE_DATE, Decimal("0.1"))
    assert "| Free-text claims backed by the advisory or stored data | 1/2 (50.0%) |" in text
    assert '- b: remote: "It is remotely exploitable."' in text
    assert "- b: unknown advisory ID CVE-2099-0001" in text


def test_the_doc_update_keeps_everything_outside_the_markers() -> None:
    doc = f"intro\n{RESULTS_START}\nold\n{RESULTS_END}\nmiddle\n| row |\n{HISTORY_END}\nend\n"
    updated = update_doc(doc, "new\n", "| new row |")

    assert updated == (
        f"intro\n{RESULTS_START}\nnew\n{RESULTS_END}\nmiddle\n| row |\n| new row |\n"
        f"{HISTORY_END}\nend\n"
    )
    with pytest.raises(ValueError, match="markers"):
        update_doc("no markers", "new\n", "| row |")


def test_select() -> None:
    cases = [case("a"), case("b", force_fallback=True)]
    assert [c.id for c in select(cases, None, fallback_case=True)] == ["a", "b"]
    assert [c.id for c in select(cases, None, fallback_case=False)] == ["a"]
    assert [c.id for c in select(cases, "b", fallback_case=True)] == ["b"]
    with pytest.raises(SystemExit, match="unknown cases: x"):
        select(cases, "a,x", fallback_case=True)


def test_the_fallback_model_is_groq_with_a_model_that_does_not_exist() -> None:
    settings = Settings(_env_file=None, groq_api_key="test", gemini_api_key="test")  # type: ignore[call-arg]
    normal, forced = models(settings)

    assert normal.primary is not None and normal.fallbacks == ()
    assert forced is not None and forced.primary is not None
    assert forced.primary.model_name == BROKEN_MODEL
    assert [p.model_name for p in forced.fallbacks] == ["gemini-3.6-flash", "gemini-3.8-flash"]
    without_gemini = Settings(_env_file=None, groq_api_key="test")  # type: ignore[call-arg]
    assert models(without_gemini)[1] is None
