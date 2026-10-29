import tomllib
from typing import Any

from depguard.parsers.models import Edge, ParseError


def load_toml(content: bytes) -> dict[str, Any]:
    try:
        return tomllib.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ParseError(f"invalid TOML: {error}") from error


def sorted_edges(
    edges: set[tuple[str | None, str]], ambiguous: set[tuple[str | None, str]] | None = None
) -> list[Edge]:
    # Sorted so the same lockfile always gives the same output.
    ambiguous = ambiguous or set()
    return [
        Edge(parent_key=p, child_key=c, ambiguous=(p, c) in ambiguous)
        for p, c in sorted(edges, key=lambda e: (e[0] or "", e[1]))
    ]
