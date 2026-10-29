from depguard.parsers.poetry_constraints import Constraint, Locked, constraints, pick_versions

OLD = Locked(key="lib==1.0", version="1.0", python_versions=">=3.8")
NEW = Locked(key="lib==2.0", version="2.0", python_versions=">=3.10")


def test_constraint_shapes() -> None:
    assert constraints(">=1") == [Constraint(version=">=1")]
    assert constraints({"version": "1.0", "python": "<3.8"}) == [
        Constraint(version="1.0", python="<3.8")
    ]
    assert len(constraints([{"version": "1"}, {"version": "2"}])) == 2
    assert constraints(42) == [Constraint()]  # unknown shape: no constraint at all


def test_version_constraint_picks_one() -> None:
    assert pick_versions("<2", [OLD, NEW]) == {"lib==1.0": False}
    assert pick_versions("2.0", [OLD, NEW]) == {"lib==2.0": False}  # bare version = exact


def test_marker_and_python_versions_pick_one() -> None:
    # Only Python < 3.10 matches the marker, and only OLD supports it.
    spec = {"version": "*", "markers": 'python_version < "3.10"'}

    assert pick_versions(spec, [OLD, NEW]) == {"lib==1.0": False}


def test_platform_markers_are_checked() -> None:
    win = Locked(key="lib==3.0", version="3.0", python_versions="*")
    spec = [
        {"version": "<3", "markers": 'sys_platform != "win32"'},
        {"version": ">=3", "markers": 'sys_platform == "win32"'},
    ]

    assert pick_versions(spec, [OLD, win]) == {"lib==1.0": False, "lib==3.0": False}


def test_a_version_kept_only_for_old_pythons_is_not_dropped() -> None:
    legacy = Locked(key="lib==0.9", version="0.9", python_versions=">=3.6,<3.8")

    assert pick_versions("*", [legacy, NEW]) == {"lib==0.9": True, "lib==2.0": True}


def test_extra_markers_still_narrow() -> None:
    spec = {"version": "*", "markers": 'python_version < "3.10" and extra == "socks"'}

    assert pick_versions(spec, [OLD, NEW]) == {"lib==1.0": False}


def test_nothing_matching_keeps_every_candidate_as_ambiguous() -> None:
    assert pick_versions(">=9", [OLD, NEW]) == {"lib==1.0": True, "lib==2.0": True}


def test_unparseable_constraint_does_not_narrow() -> None:
    assert pick_versions("^1.0", [OLD, NEW]) == {"lib==1.0": True, "lib==2.0": True}


def test_single_candidate_is_never_ambiguous() -> None:
    assert pick_versions(">=9", [OLD]) == {"lib==1.0": False}
    assert pick_versions("*", []) == {}
