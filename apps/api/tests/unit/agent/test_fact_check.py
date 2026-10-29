from typing import Any

import pytest
from fake_llm import GOOD, lodash

from depguard.agent.fact_check import check
from depguard.agent.schema import ExplanationDraft


def problems(**changes: Any) -> list[str]:
    return check(ExplanationDraft(**{**GOOD, **changes}), lodash())


def test_an_explanation_using_only_stored_facts_passes() -> None:
    assert problems() == []


def test_text_without_ids_versions_or_numbers_passes() -> None:
    draft = ExplanationDraft(
        summary="A flaw.", why_it_matters="It can be abused.", what_to_do="Upgrade.", cited_ids=[]
    )
    assert check(draft, lodash()) == []


def test_an_invented_advisory_id_fails() -> None:
    assert problems(summary="lodash also has CVE-2020-8203.") == [
        "unknown advisory ID CVE-2020-8203"
    ]


def test_a_cited_id_from_another_advisory_fails() -> None:
    assert problems(cited_ids=["GHSA-p6mc-m468-83gw"]) == [
        "unknown advisory ID GHSA-p6mc-m468-83gw",
        "cited ID GHSA-p6mc-m468-83gw is not this finding's advisory",
    ]


def test_a_wrong_fixed_version_fails() -> None:
    assert problems(what_to_do="Upgrade lodash to 4.17.21.") == [
        "unverified number or version 4.17.21"
    ]


@pytest.mark.parametrize("number", ["9.8", "0.5", "7"])
def test_a_number_not_in_stored_data_fails(number: str) -> None:
    assert problems(why_it_matters=f"Its CVSS score is {number}.") == [
        f"unverified number or version {number}"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "EPSS is 0.050 and the percentile 0.922.",
        "EPSS gives a 5% chance; it is in the 92.2% percentile.",
        "It is in the 92nd percentile of CVSS 3.1 scores.",
        "Installed: v4.17.4. Fixed: v4.17.12.",
        "It reaches 1 service, as of 2026-10-28.",
    ],
)
def test_stored_numbers_pass_in_any_usual_form(text: str) -> None:
    assert problems(why_it_matters=text) == []


def test_digits_in_package_names_are_not_numbers() -> None:
    context = lodash(package="html5-parser", paths=((("html5-parser", "4.17.4"),),))
    draft = ExplanationDraft(**{**GOOD, "summary": "html5-parser has a flaw."})
    assert check(draft, context) == []


def test_ids_are_compared_without_case() -> None:
    assert problems(cited_ids=["ghsa-jf85-cpcp-j695"]) == []


def test_a_malicious_package_without_scores_rejects_any_score() -> None:
    context = lodash(cvss=None, epss=None, epss_percentile=None, cvss_version=None)
    draft = ExplanationDraft(**{**GOOD, "why_it_matters": "Its CVSS score is 9.1."})
    assert check(draft, context) == ["unverified number or version 9.1"]
