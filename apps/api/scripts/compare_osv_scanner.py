"""Compare DepGuard's findings with OSV-Scanner's on the same lockfiles (spec §7, correctness).

Usage (from apps/api, or `make compare` from the repo root):
    uv run python scripts/compare_osv_scanner.py [LOCKFILE ...] [--repo OWNER/NAME ...]

LOCKFILE is a local lockfile; --repo downloads a public repo's lockfiles the way a scan does
(needs GITHUB_READ_TOKEN). With no arguments, the real lockfiles in tests/fixtures/real are used.
Needs `osv-scanner` on PATH (`winget install Google.OSVScanner`). Prints a Markdown report.

Both sides use OSV's data, so a difference means the two tools read the lockfile differently
(which packages, which versions) or merge aliases differently. Each one must be explained in the
documented list (phase 4b).
"""

import argparse
import asyncio
import json
import shutil
import subprocess  # noqa: S404 (runs osv-scanner, a fixed program, with list arguments)
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from depguard.advisories.cache import advisory_row
from depguard.advisories.osv import get_vuln, make_client, query_batch
from depguard.config import get_settings
from depguard.db.models import Advisory
from depguard.github.cache import ByteCache
from depguard.github.client import GitHubReader
from depguard.github.client import make_client as make_github_client
from depguard.parsers import lockfile_type
from depguard.parsers.models import Ecosystem, ParsedService
from depguard.parsers.names import normalize_pypi_name
from depguard.scan.ingest import ingest_repo, parse_lockfile
from depguard.scan.match import build_findings, unique_queries
from depguard.versions import normalize

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures" / "real"
# osv-scanner recognises lockfiles by name; anything else needs "<type>:<path>".
OSV_SCANNER_TYPES = {
    "package-lock": "package-lock.json",
    "poetry-lock": "poetry.lock",
    "uv-lock": "uv.lock",
    "requirements": "requirements.txt",
}

Package = tuple[str, str, str]  # (ecosystem, normalised name, normalised version)
Groups = dict[Package, list[frozenset[str]]]  # each finding = the set of IDs and aliases it covers


@dataclass(frozen=True)
class Difference:
    package: Package
    side: str  # "DepGuard only" or "OSV-Scanner only"
    ids: frozenset[str]


def package_key(ecosystem: str, name: str, version: str) -> Package:
    if ecosystem == "PyPI":
        name = normalize_pypi_name(name)
    return ecosystem, name, normalize(cast(Ecosystem, ecosystem), version)


def compare(ours: Groups, theirs: Groups) -> list[Difference]:
    """A finding matches if it shares any ID or alias with one on the other side for the same
    package version, so the two tools may pick different main IDs."""
    differences = []
    for package in sorted(ours.keys() | theirs.keys()):
        mine, other = ours.get(package, []), theirs.get(package, [])
        differences += [
            Difference(package, "DepGuard only", ids)
            for ids in mine
            if not any(ids & o for o in other)
        ]
        differences += [
            Difference(package, "OSV-Scanner only", ids)
            for ids in other
            if not any(ids & m for m in mine)
        ]
    return differences


async def our_groups(service: ParsedService) -> Groups:
    """DepGuard's matching on one lockfile, without a database: the same OSV calls and the same
    merging as a scan (scan/match.py)."""
    services = [(uuid.uuid4(), service)]
    queries = unique_queries(services)
    async with make_client() as client:
        batch = await query_batch(client, list(queries.values()))
        if batch.failed:
            raise SystemExit(f"OSV failed for {len(batch.failed)} packages; try again")
        ids = sorted({i for matches in batch.matches.values() for i in matches})
        records = await asyncio.gather(*(get_vuln(client, i) for i in ids))
    rows = {r["id"]: Advisory(**advisory_row(r)) for r in records if r is not None}
    result = build_findings(services, queries, batch, rows)
    groups: Groups = {}
    for finding in result.findings:
        key = package_key(finding.ecosystem, finding.entry.name, finding.entry.version)
        found = frozenset(finding.advisory.ids)
        if found not in groups.setdefault(key, []):
            groups[key].append(found)
    return groups


def scanner_groups(report: dict[str, Any]) -> Groups:
    groups: Groups = {}
    for result in report.get("results", []):
        for item in result.get("packages", []):
            package = item["package"]
            key = package_key(package["ecosystem"], package["name"], package["version"])
            by_id = {v["id"]: v for v in item.get("vulnerabilities", [])}
            for group in item.get("groups", []):
                ids = set(group.get("ids", [])) | set(group.get("aliases", []))
                for vuln_id in group.get("ids", []):
                    ids |= set(by_id.get(vuln_id, {}).get("aliases", []))
                if frozenset(ids) not in groups.setdefault(key, []):
                    groups[key].append(frozenset(ids))
    return groups


def run_osv_scanner(path: Path, kind: str) -> Groups:
    executable = shutil.which("osv-scanner")
    if executable is None:
        raise SystemExit("osv-scanner not found; install it with: winget install Google.OSVScanner")
    target = f"{OSV_SCANNER_TYPES[kind]}:{path}"
    # Exit code 1 just means "vulnerabilities found"; anything above is an error.
    done = subprocess.run(  # noqa: S603
        # --no-resolve: without it, osv-scanner resolves requirements.txt's transitive
        # dependencies and guesses their versions, which DepGuard never does (ADR-0002).
        [executable, "scan", "source", "--format=json", "--no-resolve", f"--lockfile={target}"],
        capture_output=True,
        encoding="utf-8",  # osv-scanner writes UTF-8; Windows would assume cp1252
        check=False,
    )
    if done.returncode > 1:
        raise SystemExit(f"osv-scanner failed on {path}: {done.stderr.strip()}")
    return scanner_groups(json.loads(done.stdout or "{}"))


def report(label: str, ours: Groups, theirs: Groups) -> str:
    def count(groups: Groups) -> int:
        return sum(len(found) for found in groups.values())

    differences = compare(ours, theirs)
    lines = [
        f"### {label}",
        "",
        f"DepGuard {count(ours)} findings · OSV-Scanner {count(theirs)}"
        f" · differences {len(differences)}",
    ]
    if differences:
        lines += ["", "| Package | Version | Side | IDs |", "|---|---|---|---|"]
        lines += [
            f"| {d.package[1]} | {d.package[2]} | {d.side} | {', '.join(sorted(d.ids))} |"
            for d in differences
        ]
    return "\n".join(lines) + "\n"


async def compare_file(path: Path, label: str, pyproject: bytes | None = None) -> str:
    kind = lockfile_type(path.as_posix())
    if kind is None:
        return f"### {label}\n\nnot a supported lockfile\n"
    service = parse_lockfile(kind, path.read_bytes(), path.name, pyproject)
    return report(label, await our_groups(service), run_osv_scanner(path, kind))


async def compare_repo(owner_and_name: str) -> list[str]:
    owner, _, name = owner_and_name.partition("/")
    settings = get_settings()
    if not settings.github_read_token:
        raise SystemExit("GITHUB_READ_TOKEN is not set (needed for --repo)")
    async with make_github_client(settings.github_read_token) as github:
        reader = GitHubReader(github, ByteCache(max_bytes=64_000_000))
        ingest = await ingest_repo(reader, owner, name, settings)
        tree = {f.path: f for f in (await reader.tree(owner, name, ingest.commit_sha)).files}
        sections = []
        with tempfile.TemporaryDirectory() as folder:
            for service in ingest.services:
                local = Path(folder) / PurePosixPath(service.lockfile_path).name
                local.write_bytes(await reader.blob(owner, name, tree[service.lockfile_path].sha))
                label = f"{owner_and_name}@{ingest.commit_sha[:7]}: {service.lockfile_path}"
                kind = lockfile_type(service.lockfile_path)
                assert kind is not None  # noqa: S101 (ingest only returns supported lockfiles)
                sections.append(
                    report(label, await our_groups(service), run_osv_scanner(local, kind))
                )
    return sections


def default_files() -> list[tuple[Path, bytes | None]]:
    textual = FIXTURES / "textual"
    return [
        (FIXTURES / "defectdojo" / "package-lock.json", None),
        (FIXTURES / "defectdojo" / "requirements.txt", None),
        (FIXTURES / "full-stack-fastapi-template" / "uv.lock", None),
        (textual / "poetry.lock", (textual / "pyproject.toml").read_bytes()),
    ]


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("lockfiles", nargs="*", type=Path)
    parser.add_argument("--repo", action="append", default=[], metavar="OWNER/NAME")
    args = parser.parse_args(argv)

    files: list[tuple[Path, bytes | None]] = [(path, None) for path in args.lockfiles]
    if not files and not args.repo:
        files = default_files()
    sections = ["# DepGuard vs OSV-Scanner", ""]
    for path, pyproject in files:
        sections.append(await compare_file(path, path.as_posix(), pyproject))
    for repo in args.repo:
        sections += await compare_repo(repo)
    print("\n".join(sections))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
