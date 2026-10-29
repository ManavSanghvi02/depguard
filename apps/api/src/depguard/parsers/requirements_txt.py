"""requirements*.txt: only exact `==` / `===` pins are used; anything else is skipped (ADR-0002).

The file is a flat list, so every entry is direct and production (file names like
requirements-dev.txt aren't reliable), and there are no edges between entries.
"""

import re

from packaging.requirements import InvalidRequirement, Requirement

from depguard.parsers.common import sorted_edges
from depguard.parsers.models import Entry, ParsedService, ParseError, SkippedPackage, SkipReason
from depguard.parsers.names import normalize_pypi_name, pypi_key

# pip treats '#' as a comment at the start of a line or after whitespace.
COMMENT = re.compile(r"(^|\s)#.*$")
EDITABLE_OPTIONS = ("-e", "--editable")


def logical_lines(text: str) -> list[str]:
    """Join lines ending in a backslash, as pip does."""
    lines: list[str] = []
    current = ""
    for raw in text.splitlines():  # also handles CRLF
        if raw.endswith("\\"):
            current += raw[:-1] + " "
        else:
            lines.append(current + raw)
            current = ""
    if current:
        lines.append(current)
    return lines


def exact_version(requirement: Requirement) -> str | None:
    specifiers = list(requirement.specifier)
    if len(specifiers) != 1:
        return None
    spec = specifiers[0]
    if spec.operator not in ("==", "===") or "*" in spec.version:
        return None
    return spec.version


def parse_requirements_txt(content: bytes, lockfile_path: str) -> ParsedService:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ParseError(f"not UTF-8 text: {error}") from error

    entries: dict[str, Entry] = {}  # by name: a later pin of the same package wins
    skipped: list[SkippedPackage] = []

    for line in logical_lines(text):
        line = COMMENT.sub("", line).strip()
        if not line:
            continue
        if line.startswith(EDITABLE_OPTIONS):
            target = line.split(maxsplit=1)[-1]
            skipped.append(SkippedPackage(name=target, spec=target, reason="not_from_registry"))
            continue
        if line.startswith("-"):
            continue  # -r, -c, --index-url, ...: options, not packages
        line = line.split(" --", 1)[0].strip()  # drop per-line options such as --hash
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            # A bare URL or local path (git+https://..., ./pkg) or something pip-specific.
            is_url_or_path = "://" in line or line.startswith((".", "/"))
            reason: SkipReason = "not_from_registry" if is_url_or_path else "version_unknown"
            skipped.append(SkippedPackage(name=line, spec=line, reason=reason))
            continue

        name = normalize_pypi_name(requirement.name)
        if requirement.url:  # name @ https://...
            skipped.append(
                SkippedPackage(name=name, spec=requirement.url, reason="not_from_registry")
            )
            continue
        version = exact_version(requirement)
        if version is None:
            spec = str(requirement.specifier)
            skipped.append(SkippedPackage(name=name, spec=spec, reason="version_unknown"))
            continue
        # Environment markers are ignored: keeping the entry can only over-report a risk.
        entries[name] = Entry(
            key=pypi_key(name, version), name=name, version=version, dev=False, direct=True
        )

    return ParsedService(
        lockfile_path=lockfile_path,
        lockfile_type="requirements",
        ecosystem="PyPI",
        entries=list(entries.values()),
        edges=sorted_edges({(None, entry.key) for entry in entries.values()}),
        # "bleach==6.4.0" plus "bleach[css]": the second line adds extras, not an unknown version.
        skipped=[s for s in skipped if s.name not in entries],
    )
