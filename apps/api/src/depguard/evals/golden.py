"""The golden set (docs/evals.md): real findings with every fact the agent may see, built by
scripts/build_golden_set.py from evals/cases.toml and committed, so every run uses the same data."""

import json
import uuid
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from depguard.agent.context import FindingContext

EVALS_DIR = Path(__file__).resolve().parents[3] / "evals"
CASES_FILE = EVALS_DIR / "cases.toml"
GOLDEN_FILE = EVALS_DIR / "golden_set.json"
# The parts of each OSV record kept, so tests can recompute the facts from OSV's own data.
OSV_FIELDS = ("id", "aliases", "summary", "details", "severity", "affected", "modified")

DECIMALS = {"cvss", "epss", "epss_percentile"}
UUIDS = {"finding_id", "repo_id"}


@dataclass(frozen=True)
class Case:
    id: str
    lockfile: str
    dep_key: str
    context: FindingContext
    injection_markers: tuple[str, ...]  # injected text that must not reach the explanation
    force_fallback: bool  # Groq made to fail, so the real Gemini fallback runs
    osv: tuple[dict[str, Any], ...]

    @property
    def is_injection(self) -> bool:
        return bool(self.injection_markers)


def to_json(values: dict[str, Any]) -> dict[str, Any]:
    """FindingContext fields as JSON: decimals and dates as text, tuples as lists."""

    def convert(value: Any) -> Any:
        if isinstance(value, Decimal | uuid.UUID):
            return str(value)
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, tuple | list):
            return [convert(v) for v in value]
        return value

    return {key: convert(value) for key, value in values.items()}


def to_context(values: dict[str, Any]) -> FindingContext:
    known = {f.name for f in fields(FindingContext)}
    if set(values) != known:
        raise ValueError(f"context fields differ: {sorted(set(values) ^ known)}")
    converted = dict(values)
    for key in DECIMALS:
        converted[key] = None if values[key] is None else Decimal(values[key])
    for key in UUIDS:
        converted[key] = uuid.UUID(values[key])
    if values["data_date"] is not None:
        converted["data_date"] = date.fromisoformat(values["data_date"])
    converted["aliases"] = tuple(values["aliases"])
    converted["paths"] = tuple(tuple(tuple(step) for step in path) for path in values["paths"])
    return FindingContext(**converted)


def load(path: Path = GOLDEN_FILE) -> list[Case]:
    return [
        Case(
            id=item["id"],
            lockfile=item["lockfile"],
            dep_key=item["dep_key"],
            context=to_context(item["context"]),
            injection_markers=tuple(item["injection_markers"]),
            force_fallback=item["force_fallback"],
            osv=tuple(item["osv"]),
        )
        for item in json.loads(path.read_text(encoding="utf-8"))
    ]
