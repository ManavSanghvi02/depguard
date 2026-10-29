import itertools
from decimal import Decimal

import pytest

from depguard.scoring.score import ScoreInputs, risk_score, sort_key, tier


def inputs(
    *,
    malicious: bool = False,
    kev: bool = False,
    epss: str | None = None,
    percentile: str | None = None,
    cvss: str | None = None,
    reach: int = 1,
    dev: bool = False,
) -> ScoreInputs:
    return ScoreInputs(
        is_malicious=malicious,
        in_kev=kev,
        epss=Decimal(epss) if epss else None,
        epss_percentile=Decimal(percentile) if percentile else None,
        cvss=Decimal(cvss) if cvss else None,
        reach=reach,
        is_dev=dev,
    )


# One row per rule in ADR-0003's tier table.
@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (inputs(malicious=True), ("fix_now", "malicious")),
        (inputs(malicious=True, dev=True), ("fix_now", "malicious")),  # even in dev
        (inputs(kev=True), ("fix_now", "kev")),
        (inputs(kev=True, epss="0.9"), ("fix_now", "kev")),  # KEV ranks above EPSS-only
        (inputs(epss="0.1"), ("fix_now", "epss")),  # the threshold counts
        (inputs(kev=True, dev=True), ("fix_soon", None)),
        (inputs(epss="0.5", dev=True), ("fix_soon", None)),
        (inputs(cvss="7.0"), ("fix_soon", None)),
        (inputs(cvss="9.8", dev=True), ("monitor", None)),  # high CVSS only counts in production
        (inputs(cvss="6.9", epss="0.099"), ("monitor", None)),
        (inputs(), ("monitor", None)),  # nothing known
    ],
)
def test_tier_rules(given: ScoreInputs, expected: tuple[str, str | None]) -> None:
    assert tier(given) == expected


def test_three_real_findings_from_nodejs_goof() -> None:
    """ADR-0003's worked example: EPSS data of 2026-10-28, rounded to 3 decimals on load."""
    lodash_10744 = inputs(epss="0.050", percentile="0.922", cvss="9.1")
    lodash_8203 = inputs(epss="0.052", percentile="0.925", cvss="7.4")
    dustjs_4264 = inputs(epss="0.012", percentile="0.668", cvss="8.8")

    assert {tier(i) for i in (lodash_10744, lodash_8203, dustjs_4264)} == {("fix_soon", None)}
    assert risk_score(lodash_10744) == Decimal("0.7540")
    assert risk_score(lodash_8203) == Decimal("0.7045")
    assert risk_score(dustjs_4264) == Decimal("0.6180")


def test_missing_values_count_as_zero_and_reach_is_capped() -> None:
    assert risk_score(inputs(reach=0)) == Decimal("0")
    assert risk_score(inputs(reach=10)) == risk_score(inputs(reach=500)) == Decimal("0.2")
    assert risk_score(inputs(percentile="1", cvss="10", reach=10)) == Decimal("1")


def test_scores_are_deterministic() -> None:
    given = inputs(epss="0.3", percentile="0.977", cvss="7.5", reach=3)
    assert len({risk_score(given) for _ in range(100)}) == 1


def test_fix_now_always_ranks_above_everything_else() -> None:
    """Every combination of inputs: sorted by the key, tiers never interleave."""
    combos = itertools.product(
        [False, True],  # malicious
        [False, True],  # KEV
        [None, "0.01", "0.1", "0.97"],  # EPSS
        [None, "0.1", "0.99"],  # percentile
        [None, "5.0", "7.0", "10"],  # CVSS
        [0, 1, 15],  # reach
        [False, True],  # dev
    )
    keyed = []
    for i, (mal, kev, epss, pct, cvss, reach, dev) in enumerate(combos):
        given = inputs(
            malicious=mal, kev=kev, epss=epss, percentile=pct, cvss=cvss, reach=reach, dev=dev
        )
        tier_name, subgroup = tier(given)
        keyed.append(
            (sort_key(tier_name, subgroup, risk_score(given), f"GHSA-{i}", "p"), tier_name)
        )
    order = [tier_name for _, tier_name in sorted(keyed)]
    assert order == sorted(order, key=["fix_now", "fix_soon", "monitor"].index)


def test_subgroups_order_inside_fix_now() -> None:
    low_malicious = sort_key("fix_now", "malicious", Decimal("0"), "MAL-1", "a")
    high_kev = sort_key("fix_now", "kev", Decimal("1"), "GHSA-1", "a")
    high_epss = sort_key("fix_now", "epss", Decimal("1"), "GHSA-1", "a")
    assert sorted([high_epss, high_kev, low_malicious]) == [low_malicious, high_kev, high_epss]


def test_ties_break_on_advisory_then_package() -> None:
    a = sort_key("monitor", None, Decimal("0.5"), "GHSA-a", "zlib")
    b = sort_key("monitor", None, Decimal("0.5"), "GHSA-b", "abc")
    c = sort_key("monitor", None, Decimal("0.5"), "GHSA-b", "abd")
    assert sorted([c, b, a]) == [a, b, c]
