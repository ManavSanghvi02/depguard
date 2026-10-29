"""Tier, subgroup, risk score and sort key (ADR-0003). Pure functions: same inputs, same output.

Decimal, not float, so a score is exactly the same on every machine and run.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Tier = Literal["fix_now", "fix_soon", "monitor"]
Subgroup = Literal["malicious", "kev", "epss"]

EPSS_THRESHOLD = Decimal("0.1")  # tier rule: raw EPSS probability
CVSS_THRESHOLD = Decimal("7")
WEIGHT_EPSS = Decimal("0.5")  # applied to the EPSS *percentile*
WEIGHT_CVSS = Decimal("0.3")
WEIGHT_REACH = Decimal("0.2")
REACH_CAP = 10

TIER_RANK: dict[str, int] = {"fix_now": 0, "fix_soon": 1, "monitor": 2}
SUBGROUP_RANK: dict[str | None, int] = {"malicious": 0, "kev": 1, "epss": 2, None: 3}


@dataclass(frozen=True)
class ScoreInputs:
    is_malicious: bool
    in_kev: bool
    epss: Decimal | None
    epss_percentile: Decimal | None
    cvss: Decimal | None
    reach: int  # services of this user whose latest scan has this package version and advisory
    is_dev: bool


def tier(inputs: ScoreInputs) -> tuple[Tier, Subgroup | None]:
    """The tier, and inside "fix now" the subgroup (malicious -> KEV -> EPSS only)."""
    exploited = inputs.in_kev or (inputs.epss or 0) >= EPSS_THRESHOLD
    if inputs.is_malicious:
        # Malicious code often runs at install time, so even a dev dependency is urgent.
        return "fix_now", "malicious"
    if exploited and not inputs.is_dev:
        return "fix_now", "kev" if inputs.in_kev else "epss"
    if exploited or ((inputs.cvss or 0) >= CVSS_THRESHOLD and not inputs.is_dev):
        return "fix_soon", None
    return "monitor", None


def risk_score(inputs: ScoreInputs) -> Decimal:
    """0.5 × EPSS percentile + 0.3 × CVSS/10 + 0.2 × min(reach, 10)/10, in 0–1, 4 decimals.

    The percentile rather than the raw probability: outside "fix now", EPSS is below 0.1 by
    definition, so the raw value would barely move the score (ADR-0003). Missing values count as 0.
    """
    score = (
        WEIGHT_EPSS * (inputs.epss_percentile or 0)
        + WEIGHT_CVSS * (inputs.cvss or 0) / 10
        + WEIGHT_REACH * min(inputs.reach, REACH_CAP) / REACH_CAP
    )
    return score.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def sort_key(
    tier_name: str, subgroup: str | None, score: Decimal, advisory_id: str, package: str
) -> tuple[int, int, Decimal, str, str]:
    """Ascending order = most urgent first. Advisory ID then package name break ties, so the
    same findings always come out in the same order."""
    return TIER_RANK[tier_name], SUBGROUP_RANK[subgroup], -score, advisory_id, package
