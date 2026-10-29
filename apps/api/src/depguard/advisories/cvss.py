"""CVSS base scores from an OSV record. OSV gives vectors, not numbers, so the `cvss` library
computes the score. v3.x is preferred so advisories are comparable; v4.0 only if there's no v3
(ADR-0003). v2 is ignored: no npm/PyPI advisory has only v2 in practice, and its scale differs."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from cvss import CVSS3, CVSS4, CVSSError


@dataclass(frozen=True)
class Cvss:
    score: Decimal
    vector: str
    version: str  # "3.1", "3.0" or "4.0"


def _scores(record: dict[str, Any]) -> list[Cvss]:
    # Severity can sit on the advisory or on each affected package.
    entries = list(record.get("severity", []))
    for affected in record.get("affected", []):
        entries += affected.get("severity", [])
    found = []
    for entry in entries:
        vector = entry.get("score", "")
        try:
            if entry.get("type") == "CVSS_V3":
                parsed: CVSS3 | CVSS4 = CVSS3(vector)
                version = vector.split("/")[0].removeprefix("CVSS:")
            elif entry.get("type") == "CVSS_V4":
                parsed, version = CVSS4(vector), "4.0"
            else:
                continue
        except CVSSError:
            continue  # a malformed vector: treat as no score rather than fail the scan
        found.append(Cvss(Decimal(str(parsed.base_score)), vector, version))
    return found


def best_cvss(record: dict[str, Any]) -> Cvss | None:
    """The highest v3.x score, else the highest v4.0 score, else None."""
    scores = _scores(record)
    v3 = [s for s in scores if s.version.startswith("3")]
    candidates = v3 or scores
    return max(candidates, key=lambda s: (s.score, s.vector)) if candidates else None
