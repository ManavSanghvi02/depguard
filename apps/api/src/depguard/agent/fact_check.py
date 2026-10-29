"""The deterministic fact check (ADR-0013): every advisory ID, version and number in an explanation
must come from the stored finding. Anything else is reported, and the explanation is rejected.

Pure code, no I/O and no LLM, so "no invented facts" is something a unit test can prove.
"""

import re
from decimal import Decimal, InvalidOperation

from depguard.agent.context import FindingContext
from depguard.agent.schema import ExplanationDraft

# The ID formats OSV uses for npm and PyPI advisories.
ID_PATTERN = re.compile(
    r"\b(?:CVE-\d{4}-\d{4,}|GHSA(?:-[0-9a-z]{4}){3}|PYSEC-\d{4}-\d+|MAL-\d{4}-\d+|OSV-\d{4}-\d+)\b",
    re.IGNORECASE,
)
# A number, version or date: 7.5, 4.17.21, v2.0.0-beta.1, 95.4%, 95th, 2026-10-28. Digits inside
# words are skipped.
NUMBER_PATTERN = re.compile(
    r"(?<![\w.])v?(?P<number>\d+(?:\.\d+)*)(?P<rest>-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?"
    r"(?P<unit>%|st|nd|rd|th)?(?!\w)"
)


def check(draft: ExplanationDraft, context: FindingContext) -> list[str]:
    """The unverified facts in the draft; an empty list passes."""
    text = " ".join([draft.text(), *draft.cited_ids])
    problems: list[str] = []

    known_ids = {i.upper() for i in (context.advisory_id, *context.aliases)}
    for match in ID_PATTERN.finditer(text):
        if match.group().upper() not in known_ids:
            problems.append(f"unknown advisory ID {match.group()}")
    for cited in draft.cited_ids:
        if cited.upper() not in known_ids:
            problems.append(f"cited ID {cited} is not this finding's advisory")
    text = ID_PATTERN.sub(" ", text)

    # Names can contain digits (html5, py3dns); they aren't facts to check.
    for name in sorted(names(context), key=len, reverse=True):
        text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)

    versions, numbers, percents = allowed(context)
    for match in NUMBER_PATTERN.finditer(text):
        token = match.group().removeprefix("v")
        unit = match.group("unit")
        if token.removesuffix(unit or "") in versions:
            continue
        value = to_decimal(match.group("number"))
        if match.group("rest") is None and value is not None:
            if value in (percents if unit else numbers):
                continue
        problems.append(f"unverified number or version {match.group()}")
    return problems


def names(context: FindingContext) -> set[str]:
    found = {context.package, context.lockfile_path}
    found.update(name for path in context.paths for name, _ in path)
    return found


def allowed(context: FindingContext) -> tuple[set[str], set[Decimal], set[Decimal]]:
    """Version strings, plain numbers and percentages that the stored data contains."""
    versions = {context.installed_version}
    versions.update(version for path in context.paths for _, version in path)
    if context.fixed_version:
        versions.add(context.fixed_version)
    if context.data_date:
        versions.add(context.data_date.isoformat())

    numbers = {Decimal(context.reach), Decimal(len(context.paths))}
    for value in (context.cvss, context.epss, context.epss_percentile):
        if value is not None:
            numbers.add(value)
    if context.cvss_version:
        cvss_version = to_decimal(context.cvss_version)
        if cvss_version is not None:
            numbers.update({cvss_version, Decimal(int(cvss_version))})

    # EPSS 0.123 may be written as 12.3% or 12%; the percentile 0.954 as 95.4%, 95% or 95th.
    percents: set[Decimal] = set()
    for value in (context.epss, context.epss_percentile):
        if value is not None:
            percent = value * 100
            percents.update({percent, round(percent, 1), Decimal(round(percent))})
    return versions, numbers, percents


def to_decimal(text: str) -> Decimal | None:
    if text.count(".") > 1:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None
