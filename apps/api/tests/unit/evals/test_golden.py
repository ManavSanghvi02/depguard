"""The golden set (docs/evals.md): OSV's own records give the stored facts, and the set covers
what the evals promise to measure."""

from dataclasses import asdict
from typing import cast

import pytest

from depguard.advisories.cvss import best_cvss
from depguard.evals.golden import Case, load, to_context, to_json
from depguard.parsers.models import Ecosystem
from depguard.scoring.score import ScoreInputs, tier
from depguard.versions import first_fixed, highest, is_major_bump

CASES = load()
NORMAL = [c for c in CASES if not c.is_injection and not c.force_fallback]


def ids(case: Case) -> str:
    return case.id


def test_the_set_covers_what_docs_evals_promises() -> None:
    assert len({c.id for c in CASES}) == len(CASES)
    assert len(NORMAL) == 20
    assert {c.context.ecosystem for c in NORMAL} == {"npm", "PyPI"}
    assert sum(c.context.is_bundled for c in NORMAL) >= 2
    assert sum(c.is_injection for c in CASES) >= 3
    fallback = [c for c in CASES if c.force_fallback]
    assert len(fallback) == 1 and fallback[0].context.repo_private is False
    contexts = [c.context for c in NORMAL]
    assert any(c.in_kev for c in contexts)
    assert any(c.is_malicious for c in contexts)
    assert any(c.is_dev for c in contexts)
    assert any(c.major_bump for c in contexts)
    assert any(c.fixed_version is None for c in contexts)
    assert any(c.epss is None for c in contexts)
    assert any(c.cvss is None for c in contexts)
    assert any(len(c.paths) > 1 for c in contexts)


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_osv_records_give_the_stored_facts(case: Case) -> None:
    """Our version and CVSS code, run on OSV's recorded data, gives what the golden set says.
    Some values were also spot-checked against osv.dev (docs/evals.md)."""
    context = case.context
    ecosystem = cast(Ecosystem, context.ecosystem)
    names = {i for record in case.osv for i in (record["id"], *record.get("aliases", []))}
    assert names == set(context.aliases)
    assert context.advisory_id in names

    fixes = [
        fixed
        for record in case.osv
        if (fixed := first_fixed(record.get("affected", []), ecosystem, context.package,
                                 context.installed_version))
    ]  # fmt: skip
    fixed = highest(ecosystem, fixes)
    assert fixed == context.fixed_version
    expected_major = fixed is not None and is_major_bump(
        ecosystem, context.installed_version, fixed
    )
    assert context.major_bump == expected_major

    scores = [s for record in case.osv if (s := best_cvss(record)) is not None]
    assert (max(s.score for s in scores) if scores else None) == context.cvss


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_tier_follows_from_the_stored_inputs(case: Case) -> None:
    c = case.context
    inputs = ScoreInputs(c.is_malicious, c.in_kev, c.epss, c.epss_percentile, c.cvss, c.reach,
                         c.is_dev)  # fmt: skip
    assert tier(inputs) == (c.tier, c.subgroup)


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_every_path_ends_at_the_package(case: Case) -> None:
    c = case.context
    assert c.paths
    assert all(path[-1] == (c.package, c.installed_version) for path in c.paths)


@pytest.mark.parametrize("case", [c for c in CASES if c.is_injection], ids=ids)
def test_the_attack_reaches_the_agent(case: Case) -> None:
    """The injected text is inside the details the agent reads (not cut off at 600 characters)."""
    details = (case.context.details or "").lower()
    assert any(marker.lower() in details for marker in case.injection_markers)


def test_contexts_survive_the_round_trip_to_json() -> None:
    for case in CASES:
        assert to_context(to_json(asdict(case.context))) == case.context


def test_an_unknown_or_missing_field_is_rejected() -> None:
    values = to_json(asdict(CASES[0].context))
    del values["reach"]
    with pytest.raises(ValueError, match="reach"):
        to_context(values)
