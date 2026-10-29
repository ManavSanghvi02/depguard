"""Build evals/golden_set.json from evals/cases.toml (docs/evals.md).

Usage (from apps/api, or `make golden` from the repo root):
    uv run python scripts/build_golden_set.py          # write evals/golden_set.json
    uv run python scripts/build_golden_set.py --list   # every finding in the case lockfiles

Real data only: the lockfiles named in cases.toml, OSV's advisories and today's KEV and EPSS
files. Every value comes from the code a scan uses (parsers, build_findings, first_fixed,
best_cvss, inputs_for, tier), so the golden set holds what a scan would store. Paths are worked
out from the parsed lockfile, as the Neo4j query would (up to 3 shortest). Reach counts the case
lockfiles that hold the same package version and advisory, as if they were one user's services.

The eval run never fetches anything: rebuilding is a deliberate step, and its diff shows what
changed (new advisory text, new EPSS).
"""

import argparse
import asyncio
import hashlib
import json
import sys
import tomllib
import uuid
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import asdict
from itertools import islice
from pathlib import Path
from typing import Any

import httpx

from depguard.advisories.cache import advisory_row
from depguard.advisories.feeds import EPSS_URL, KEV_URL, parse_epss, parse_kev
from depguard.advisories.osv import get_vuln, make_client, query_batch
from depguard.agent.context import MAX_DETAILS_CHARS, MAX_PATHS, FindingContext
from depguard.db.models import Advisory, EpssScore, Finding
from depguard.evals.golden import CASES_FILE, GOLDEN_FILE, OSV_FIELDS, to_json
from depguard.parsers import lockfile_type
from depguard.parsers.models import Entry, ParsedService
from depguard.scan.ingest import parse_lockfile
from depguard.scan.match import FindingDraft, build_findings, unique_queries
from depguard.scoring.rescore import inputs_for
from depguard.scoring.score import tier

API_DIR = Path(__file__).parents[1]
# Fixed IDs, so a rebuild with unchanged facts gives an identical file.
NAMESPACE = uuid.UUID("6f1f6d0e-55d2-4c55-9c38-4b0f8f0a4b5e")


def download(downloads: dict[str, dict[str, str]]) -> None:
    """Fetch each missing large lockfile at its fixed commit; refuse one whose hash differs."""
    for path, source in downloads.items():
        file = API_DIR / path
        if not file.exists():
            response = httpx.get(source["url"], timeout=60, follow_redirects=True)
            response.raise_for_status()
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(response.content)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        if digest != source["sha256"]:
            raise SystemExit(
                f"{path}: SHA-256 {digest} differs from cases.toml; delete it and retry"
            )


def parse(path: str) -> ParsedService:
    file = API_DIR / path
    kind = lockfile_type(file.name)
    if kind is None:
        raise SystemExit(f"{path}: not a lockfile DepGuard reads")
    pyproject = file.with_name("pyproject.toml")
    extra = pyproject.read_bytes() if kind == "poetry-lock" and pyproject.exists() else None
    return parse_lockfile(kind, file.read_bytes(), file.name, extra)


async def match(
    services: dict[str, ParsedService],
) -> tuple[dict[str, list[FindingDraft]], dict[str, Advisory]]:
    """What a scan finds in each lockfile, and the OSV record of every advisory involved."""
    ids = {path: uuid.uuid5(NAMESPACE, path) for path in services}
    pairs = [(ids[path], service) for path, service in services.items()]
    queries = unique_queries(pairs)
    async with make_client() as client:
        batch = await query_batch(client, list(queries.values()))
        if batch.failed:
            raise SystemExit(f"OSV could not answer for {len(batch.failed)} packages; try again")
        wanted = sorted({i for matches in batch.matches.values() for i in matches})
        records = await asyncio.gather(*(get_vuln(client, i) for i in wanted))
    rows = {r["id"]: Advisory(**advisory_row(r)) for r in records if r is not None}
    result = build_findings(pairs, queries, batch, rows)
    by_path: dict[str, list[FindingDraft]] = defaultdict(list)
    path_of = {service_id: path for path, service_id in ids.items()}
    for draft in result.findings:
        by_path[path_of[draft.service_id]].append(draft)
    return by_path, rows


def shortest_paths(service: ParsedService, key: str) -> list[list[Entry]]:
    """Up to MAX_PATHS shortest paths from a direct dependency down to `key`, in name order."""
    entries = {e.key: e for e in service.entries}
    children: dict[str | None, list[str]] = defaultdict(list)
    for edge in service.edges:
        children[edge.parent_key].append(edge.child_key)
    depth: dict[str, int] = {}
    parents: dict[str, list[str]] = defaultdict(list)
    frontier = sorted(set(children[None]))
    depth.update(dict.fromkeys(frontier, 1))
    while frontier and key not in depth:
        found: set[str] = set()
        for parent in frontier:
            for child in children[parent]:
                if child not in depth or child in found:
                    depth[child] = depth[parent] + 1
                    found.add(child)
                    parents[child].append(parent)
        frontier = sorted(found)

    def walk(target: str) -> Iterator[list[Entry]]:
        if depth[target] == 1:
            yield [entries[target]]
            return
        for parent in sorted(parents[target]):
            for path in walk(parent):
                yield [*path, entries[target]]

    return list(islice(walk(key), MAX_PATHS)) if key in depth else []


async def feeds() -> tuple[set[str], dict[str, EpssScore]]:
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        kev_file, epss_file = await asyncio.gather(client.get(KEV_URL), client.get(EPSS_URL))
    kev_file.raise_for_status()
    epss_file.raise_for_status()
    kev = {row[0] for row in parse_kev(kev_file.content)}
    epss = {
        cve: EpssScore(cve_id=cve, score=score, percentile=percentile, data_date=data_date)
        for cve, score, percentile, data_date in parse_epss(epss_file.content)
    }
    return kev, epss


def pick(drafts: list[FindingDraft], case: dict[str, Any]) -> FindingDraft:
    found = [
        d
        for d in drafts
        if d.entry.name == case["package"]
        and d.entry.version == case["version"]
        and d.advisory.advisory_id == case["advisory"]
        and d.entry.key == case.get("key", d.entry.key)
    ]
    if len(found) != 1:
        keys = ", ".join(d.entry.key for d in found)
        raise SystemExit(
            f"case {case['id']}: {len(found)} matching findings; set `key` to one of: {keys}"
        )
    return found[0]


def reach(by_path: dict[str, list[FindingDraft]], draft: FindingDraft) -> int:
    same = (draft.entry.name, draft.installed_version_norm, draft.advisory.advisory_id)
    return sum(
        any((d.entry.name, d.installed_version_norm, d.advisory.advisory_id) == same for d in ds)
        for ds in by_path.values()
    )


def build(
    case: dict[str, Any],
    services: dict[str, ParsedService],
    by_path: dict[str, list[FindingDraft]],
    rows: dict[str, Advisory],
    kev: set[str],
    epss: dict[str, EpssScore],
) -> dict[str, Any]:
    service = services[case["lockfile"]]
    draft = pick(by_path[case["lockfile"]], case)
    advisory = draft.advisory
    finding = Finding(
        aliases=list(advisory.ids),
        is_malicious=advisory.is_malicious,
        cvss=advisory.cvss,
        is_dev=draft.entry.dev,
    )
    count = reach(by_path, draft)
    inputs = inputs_for(finding, count, kev, epss)
    tier_name, subgroup = tier(inputs)
    main = rows[advisory.advisory_id]
    details = (main.raw or {}).get("details")
    if case.get("injection"):
        # The attack goes first, so it survives the cut to MAX_DETAILS_CHARS.
        details = f"{case['injection']}\n\n{details or ''}"
    dates = [s.data_date for s in epss.values()]
    context = FindingContext(
        finding_id=uuid.uuid5(NAMESPACE, case["id"]),
        repo_id=uuid.uuid5(NAMESPACE, case["lockfile"]),
        repo_private=False,  # every case lockfile comes from a public repo or is hand-made
        ecosystem=service.ecosystem,
        package=draft.entry.name,
        installed_version=draft.entry.version,
        lockfile_path=Path(case["lockfile"]).name,
        fixed_version=draft.fixed_version,
        major_bump=draft.major_bump,
        is_bundled=draft.entry.bundled,
        is_dev=draft.entry.dev,
        is_direct=draft.entry.direct,
        is_malicious=advisory.is_malicious,
        advisory_id=advisory.advisory_id,
        aliases=advisory.ids,
        summary=advisory.summary,
        details=details[:MAX_DETAILS_CHARS] if isinstance(details, str) else None,
        cvss=advisory.cvss,
        cvss_version=main.cvss_version,
        in_kev=inputs.in_kev,
        epss=inputs.epss,
        epss_percentile=inputs.epss_percentile,
        reach=count,
        reach_complete=True,
        tier=tier_name,
        subgroup=subgroup,
        data_date=max(dates) if dates else None,
        paths=tuple(
            tuple((e.name, e.version) for e in path)
            for path in shortest_paths(service, draft.entry.key)
        ),
    )
    members = [rows[i] for i in advisory.ids if i in rows]
    return {
        "id": case["id"],
        "lockfile": case["lockfile"],
        "dep_key": draft.entry.key,
        "injection_markers": case.get("injection_markers", []),
        "force_fallback": case.get("force_fallback", False),
        "context": to_json(asdict(context)),
        "osv": [{k: (m.raw or {})[k] for k in OSV_FIELDS if k in (m.raw or {})} for m in members],
    }


def list_findings(services: dict[str, ParsedService], by_path: dict[str, Any]) -> None:
    for path in services:
        for d in sorted(by_path[path], key=lambda d: (d.entry.name, d.advisory.advisory_id)):
            a, e = d.advisory, d.entry
            flags = [f for f, on in (("dev", e.dev), ("direct", e.direct),
                     ("bundled", e.bundled), ("malicious", a.is_malicious)) if on]  # fmt: skip
            print(
                f"{path} | {e.name} {e.version} | {a.advisory_id} | {','.join(a.ids)} |"
                f" cvss {a.cvss} | fixed {d.fixed_version} major={d.major_bump} | {' '.join(flags)}"
            )


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="print the findings to choose from")
    args = parser.parse_args(argv)

    config = tomllib.loads(CASES_FILE.read_text(encoding="utf-8"))
    cases = config["case"]
    download(config.get("downloads", {}))
    services = {path: parse(path) for path in dict.fromkeys(c["lockfile"] for c in cases)}
    by_path, rows = await match(services)
    if args.list:
        list_findings(services, by_path)
        return 0
    kev, epss = await feeds()
    golden = [build(case, services, by_path, rows, kev, epss) for case in cases]
    GOLDEN_FILE.write_text(json.dumps(golden, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {len(golden)} cases to {GOLDEN_FILE.relative_to(API_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
