from depguard.graph.capacity import GraphSize, has_room

LIMITS = GraphSize(nodes=1_000, relationships=2_000)
EMPTY = GraphSize(nodes=0, relationships=0)


def test_room_under_90_percent() -> None:
    assert has_room(GraphSize(500, 500), EMPTY, GraphSize(100, 100), LIMITS)


def test_exactly_90_percent_is_allowed() -> None:
    assert has_room(GraphSize(800, 0), EMPTY, GraphSize(100, 1_800), LIMITS)


def test_over_90_percent_of_either_limit_is_refused() -> None:
    assert not has_room(GraphSize(800, 0), EMPTY, GraphSize(101, 0), LIMITS)
    assert not has_room(GraphSize(0, 1_800), EMPTY, GraphSize(1, 1), LIMITS)


def test_replacing_a_service_counts_only_the_difference() -> None:
    old = GraphSize(300, 600)

    # Same size again: fits, even though current + new alone would not.
    assert has_room(GraphSize(900, 1_800), old, GraphSize(300, 600), LIMITS)
    # Larger than before: refused once it crosses 90%.
    assert not has_room(GraphSize(900, 1_800), old, GraphSize(301, 600), LIMITS)
    # Smaller than before: always fits.
    assert has_room(GraphSize(950, 1_900), old, GraphSize(10, 10), LIMITS)
