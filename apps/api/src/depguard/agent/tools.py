"""The agent's read-only tools. Each is bound to one finding and takes no arguments, so text in an
advisory can't point a tool at other data. Nothing here calls the internet or writes anything."""

import json
from collections.abc import Callable
from typing import Any

from depguard.agent.context import FindingContext


def untrusted(text: str | None) -> str | None:
    """Advisory text comes from public databases; the prompt says to treat it as data only.
    Tags inside it are removed so it can't close the block early."""
    if text is None:
        return None
    cleaned = text.replace("<untrusted>", "").replace("</untrusted>", "")
    return f"<untrusted>{cleaned}</untrusted>"


def as_text(value: object) -> str | None:
    return None if value is None else str(value)


def dependency_path(context: FindingContext) -> dict[str, Any]:
    return {
        "lockfile": context.lockfile_path,
        "direct_dependency": context.is_direct,
        "dev_only": context.is_dev,
        "paths": [" > ".join(f"{name}@{version}" for name, version in p) for p in context.paths],
        "services_affected": context.reach,
    }


def advisory_details(context: FindingContext) -> dict[str, Any]:
    return {
        "advisory_id": context.advisory_id,
        "aliases": list(context.aliases),
        "malicious_package": context.is_malicious,
        "summary": untrusted(context.summary),
        "details": untrusted(context.details),
        "cvss": as_text(context.cvss),
        "cvss_version": context.cvss_version,
        "in_cisa_kev": context.in_kev,
        "epss": as_text(context.epss),
        "epss_percentile": as_text(context.epss_percentile),
    }


def fixed_version(context: FindingContext) -> dict[str, Any]:
    return {
        "installed_version": context.installed_version,
        "fixed_version": context.fixed_version,
        "major_version_bump": context.major_bump,
        "bundled_inside_another_package": context.is_bundled,
    }


READ_TOOLS: dict[str, tuple[str, Callable[[FindingContext], dict[str, Any]]]] = {
    "get_dependency_path": (
        "How the vulnerable package gets into the project: lockfile, paths, services affected.",
        dependency_path,
    ),
    "get_advisory_details": (
        "The advisory: IDs, summary, details, CVSS, CISA KEV and EPSS exploit data.",
        advisory_details,
    ),
    "get_fixed_version": (
        "Installed and fixed versions, whether the fix is a major bump, whether it is bundled.",
        fixed_version,
    ),
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}},
        },
    }
    for name, (description, _) in READ_TOOLS.items()
]


def run_tool(name: str, context: FindingContext) -> str:
    """Compact JSON without empty fields: every token is resent on each later LLM call."""
    if name not in READ_TOOLS:
        return json.dumps({"error": f"unknown tool {name}"})
    result = {k: v for k, v in READ_TOOLS[name][1](context).items() if v not in (None, [])}
    return json.dumps(result, separators=(",", ":"))
