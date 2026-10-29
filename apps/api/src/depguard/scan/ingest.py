"""Scan steps 2–3: find a repo's lockfiles, download them, and parse each into a service."""

from pathlib import PurePosixPath

from pydantic import BaseModel

from depguard.config import Settings
from depguard.github.client import GitHubReader, TreeFile
from depguard.parsers import lockfile_type
from depguard.parsers.models import LockfileType, ParsedService, ParseError
from depguard.parsers.npm_lock import parse_package_lock
from depguard.parsers.poetry_lock import parse_poetry_lock
from depguard.parsers.requirements_txt import parse_requirements_txt
from depguard.parsers.uv_lock import parse_uv_lock

# Lockfiles inside these folders are installed packages or test data, not services of the repo.
EXCLUDED_FOLDERS = {"node_modules", "test", "tests", "__tests__", "fixtures", "testdata"}


class FailedService(BaseModel):
    lockfile_path: str
    error: str


class IngestResult(BaseModel):
    owner: str
    repo: str
    commit_sha: str
    services: list[ParsedService]
    failed_services: list[FailedService]
    partial_reasons: list[str]
    # False if GitHub truncated the tree or the lockfile cap was hit: lockfiles missing from this
    # result may still exist, so their stored graphs must not be treated as stale.
    all_lockfiles_seen: bool


def select_lockfiles(files: list[TreeFile]) -> list[tuple[TreeFile, LockfileType]]:
    selected = []
    for file in sorted(files, key=lambda f: f.path):
        kind = lockfile_type(file.path)
        folders = PurePosixPath(file.path).parts[:-1]
        if kind is not None and not EXCLUDED_FOLDERS.intersection(folders):
            selected.append((file, kind))
    return selected


def parse_lockfile(
    kind: LockfileType, content: bytes, path: str, pyproject: bytes | None
) -> ParsedService:
    if kind == "package-lock":
        return parse_package_lock(content, path)
    if kind == "poetry-lock":
        return parse_poetry_lock(content, path, pyproject)
    if kind == "uv-lock":
        return parse_uv_lock(content, path)
    return parse_requirements_txt(content, path)


async def ingest_repo(
    reader: GitHubReader, owner: str, repo: str, settings: Settings
) -> IngestResult:
    commit_sha = await reader.latest_commit(owner, repo)
    tree = await reader.tree(owner, repo, commit_sha)
    files_by_path = {file.path: file for file in tree.files}

    partial_reasons: list[str] = []
    if tree.truncated:
        partial_reasons.append(
            "GitHub truncated the repository's file list; some lockfiles may be missing"
        )

    selected = select_lockfiles(tree.files)
    limit = settings.max_lockfiles_per_repo
    all_lockfiles_seen = not tree.truncated and len(selected) <= limit
    if len(selected) > limit:
        partial_reasons.append(
            f"{len(selected)} lockfiles found; only the first {limit} were scanned"
        )
        selected = selected[:limit]

    services: list[ParsedService] = []
    failed: list[FailedService] = []
    for file, kind in selected:
        if file.size > settings.max_lockfile_bytes:
            megabytes = settings.max_lockfile_bytes // 1_000_000
            failed.append(
                FailedService(lockfile_path=file.path, error=f"larger than {megabytes} MB")
            )
            continue
        content = await reader.blob(owner, repo, file.sha)

        pyproject = None
        if kind == "poetry-lock":
            # poetry.lock doesn't say which packages are direct; the pyproject.toml beside it does.
            sibling = files_by_path.get(str(PurePosixPath(file.path).with_name("pyproject.toml")))
            if sibling is not None and sibling.size <= settings.max_lockfile_bytes:
                pyproject = await reader.blob(owner, repo, sibling.sha)

        try:
            service = parse_lockfile(kind, content, file.path, pyproject)
        except ParseError as error:
            failed.append(FailedService(lockfile_path=file.path, error=str(error)))
            continue
        if len(service.entries) > settings.max_entries_per_service:
            limit = settings.max_entries_per_service
            message = f"{len(service.entries)} dependencies; the limit is {limit}"
            failed.append(FailedService(lockfile_path=file.path, error=message))
            continue
        partial_reasons += [f"{file.path}: {warning}" for warning in service.warnings]
        services.append(service)

    return IngestResult(
        owner=owner,
        repo=repo,
        commit_sha=commit_sha,
        services=services,
        failed_services=failed,
        partial_reasons=partial_reasons,
        all_lockfiles_seen=all_lockfiles_seen,
    )
