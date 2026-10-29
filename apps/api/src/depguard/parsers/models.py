"""What the parsers produce: one ParsedService per lockfile."""

from typing import Literal

from pydantic import BaseModel

Ecosystem = Literal["npm", "PyPI"]  # OSV's ecosystem names
LockfileType = Literal["package-lock", "poetry-lock", "uv-lock", "requirements"]
SkipReason = Literal["version_unknown", "not_from_registry"]


class ParseError(Exception):
    """The lockfile is malformed or in a format we don't support. Fails that service only."""


class Entry(BaseModel):
    # npm: install path (node_modules/a/node_modules/b). PyPI: "name==version" (ADR-0006).
    key: str
    name: str
    version: str
    dev: bool
    direct: bool


class Edge(BaseModel):
    parent_key: str | None  # None = the service itself (a direct dependency)
    child_key: str
    # Poetry only: the lock holds several versions of the child and nothing says which one
    # the parent uses, so there is an edge to each (parsers/poetry_constraints.py).
    ambiguous: bool = False


class SkippedPackage(BaseModel):
    name: str
    spec: str  # what the file said, e.g. ">=2.0" or a git URL
    reason: SkipReason


class ParsedService(BaseModel):
    lockfile_path: str
    lockfile_type: LockfileType
    ecosystem: Ecosystem
    entries: list[Entry]
    edges: list[Edge]
    skipped: list[SkippedPackage]
    warnings: list[str] = []
