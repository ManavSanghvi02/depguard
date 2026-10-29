import pytest

from depguard.graph.writer import batches, check_edges
from depguard.parsers.models import Edge, Entry, ParsedService


def service(edges: list[Edge]) -> ParsedService:
    return ParsedService(
        lockfile_path="requirements.txt",
        lockfile_type="requirements",
        ecosystem="PyPI",
        entries=[Entry(key="a==1", name="a", version="1", dev=False, direct=True)],
        edges=edges,
        skipped=[],
    )


def test_edges_between_known_entries_pass() -> None:
    check_edges(service([Edge(parent_key=None, child_key="a==1")]))


@pytest.mark.parametrize(
    "edge",
    [
        Edge(parent_key=None, child_key="missing==1"),
        Edge(parent_key="missing==1", child_key="a==1"),
    ],
)
def test_edge_to_a_missing_entry_is_a_bug(edge: Edge) -> None:
    with pytest.raises(ValueError, match="has no entry"):
        check_edges(service([edge]))


def test_batches_of_1000() -> None:
    rows = [{"i": i} for i in range(2_500)]

    assert [len(batch) for batch in batches(rows)] == [1_000, 1_000, 500]
    assert batches([]) == []
