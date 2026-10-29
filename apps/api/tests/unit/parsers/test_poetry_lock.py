from pathlib import Path

import pytest

from depguard.parsers.models import ParsedService, ParseError
from depguard.parsers.poetry_lock import direct_dependency_constraints, parse_poetry_lock

REAL = Path(__file__).parents[2] / "fixtures" / "real" / "textual"


def parse(lock: str, pyproject: str | None = None) -> ParsedService:
    return parse_poetry_lock(
        lock.encode(), "poetry.lock", pyproject.encode() if pyproject is not None else None
    )


def test_real_textual_lockfile() -> None:
    service = parse_poetry_lock(
        (REAL / "poetry.lock").read_bytes(), "poetry.lock", (REAL / "pyproject.toml").read_bytes()
    )
    entries = {e.name: e for e in service.entries}

    assert len(service.entries) == 111
    assert sum(e.dev for e in service.entries) == 86
    assert entries["rich"].key == "rich==14.2.0"
    assert entries["rich"].dev is False and entries["rich"].direct is True
    assert entries["pytest"].dev is True and entries["pytest"].direct is True


def test_dev_is_read_from_fields_not_lock_version() -> None:
    service = parse(
        """
[[package]]
name = "old-dev"
version = "1.0"
category = "dev"

[[package]]
name = "new-dev"
version = "1.0"
groups = ["dev", "test"]

[[package]]
name = "shared"
version = "1.0"
groups = ["main", "dev"]

[[package]]
name = "no-fields"
version = "1.0"

[metadata]
lock-version = "2.0"
"""
    )
    dev = {e.name: e.dev for e in service.entries}

    assert dev == {"old-dev": True, "new-dev": True, "shared": False, "no-fields": False}


def test_edges_and_direct_from_pyproject() -> None:
    service = parse(
        """
[[package]]
name = "Requests"
version = "2.32.0"
[package.dependencies]
urllib3 = ">=1.21"
charset_normalizer = {version = ">=2", markers = "python_version >= '3.8'"}
missing-by-marker = {version = "*", markers = "sys_platform == 'win32'"}

[[package]]
name = "urllib3"
version = "2.2.0"

[[package]]
name = "charset-normalizer"
version = "3.3.0"
""",
        """
[tool.poetry.dependencies]
python = "^3.10"
requests = "^2"
""",
    )

    assert {(e.parent_key, e.child_key) for e in service.edges} == {
        (None, "requests==2.32.0"),
        ("requests==2.32.0", "urllib3==2.2.0"),
        ("requests==2.32.0", "charset-normalizer==3.3.0"),
    }
    assert [e.name for e in service.entries if e.direct] == ["requests"]


def test_two_versions_of_one_package_get_separate_keys() -> None:
    service = parse(
        """
[[package]]
name = "numpy"
version = "1.26.4"

[[package]]
name = "numpy"
version = "2.1.0"
""",
        '[project]\ndependencies = ["numpy"]\n',
    )

    assert sorted(e.key for e in service.entries) == ["numpy==1.26.4", "numpy==2.1.0"]
    assert all(e.direct for e in service.entries)
    assert all(e.ambiguous for e in service.edges)  # "numpy" alone doesn't say which


def test_git_and_path_sources_are_skipped() -> None:
    service = parse(
        """
[[package]]
name = "mylib"
version = "0.1.0"
[package.source]
type = "git"
url = "https://github.com/o/mylib.git"
"""
    )

    assert service.entries == []
    assert service.skipped[0].reason == "not_from_registry"


def test_without_pyproject_direct_is_guessed_with_a_warning() -> None:
    service = parse(
        """
[[package]]
name = "a"
version = "1"
[package.dependencies]
b = "*"

[[package]]
name = "b"
version = "1"
"""
    )

    assert [e.name for e in service.entries if e.direct] == ["a"]
    assert service.warnings


def test_direct_names_cover_every_pyproject_layout() -> None:
    pyproject = {
        "project": {
            "dependencies": ["Flask>=3", "not a valid requirement!"],
            "optional-dependencies": {"s3": ["boto3"]},
        },
        "dependency-groups": {"lint": ["ruff", {"include-group": "test"}]},
        "tool": {
            "poetry": {
                "dependencies": {"python": "^3.10", "rich": "*"},
                "dev-dependencies": {"black": "*"},
                "group": {"test": {"dependencies": {"pytest": "*"}}},
            }
        },
    }

    found = direct_dependency_constraints(pyproject)

    assert set(found) == {"flask", "boto3", "ruff", "rich", "black", "pytest"}
    assert found["flask"] == [{"version": ">=3", "markers": ""}]
    assert found["rich"] == ["*"]


def test_two_versions_are_picked_by_constraint_and_markers() -> None:
    service = parse(
        """
[[package]]
name = "app-lib"
version = "1.0"
[package.dependencies]
numpy = [
    {version = ">=1.26,<2", markers = "python_version < \\"3.12\\""},
    {version = ">=2.1", markers = "python_version >= \\"3.12\\""},
]
pinned = ">=2"
anything = "*"

[[package]]
name = "numpy"
version = "1.26.4"

[[package]]
name = "numpy"
version = "2.1.0"

[[package]]
name = "pinned"
version = "1.0"

[[package]]
name = "pinned"
version = "2.0"

[[package]]
name = "anything"
version = "1.0"
python-versions = ">=3.8"

[[package]]
name = "anything"
version = "2.0"
python-versions = ">=3.10"
""",
        '[project]\ndependencies = ["app-lib"]\n',
    )
    edges = {(e.parent_key, e.child_key): e.ambiguous for e in service.edges}

    assert edges == {
        (None, "app-lib==1.0"): False,
        # one version per marker branch: both edges are real, neither is ambiguous
        ("app-lib==1.0", "numpy==1.26.4"): False,
        ("app-lib==1.0", "numpy==2.1.0"): False,
        ("app-lib==1.0", "pinned==2.0"): False,
        # nothing narrows the choice: both edges kept and marked
        ("app-lib==1.0", "anything==1.0"): True,
        ("app-lib==1.0", "anything==2.0"): True,
    }


def test_real_textual_lockfile_has_no_ambiguous_edges() -> None:
    service = parse_poetry_lock(
        (REAL / "poetry.lock").read_bytes(), "poetry.lock", (REAL / "pyproject.toml").read_bytes()
    )

    assert not any(e.ambiguous for e in service.edges)


@pytest.mark.parametrize(
    ("lock", "pyproject"),
    [
        ('[[package]]\nname = "a"\nversion = "1"\ndependencies = ["b"]\n', None),
        ('[[package]]\nname = "a"\nversion = "1"\n', '[tool]\npoetry = "x"\n'),
        ('[[package]]\nname = "a"\nversion = "1"\n', '[tool.poetry]\ndependencies = ["a"]\n'),
        ('[[package]]\nname = "a"\nversion = "1"\n', '[project]\ndependencies = "a"\n'),
    ],
)
def test_wrong_shapes_are_parse_errors(lock: str, pyproject: str | None) -> None:
    with pytest.raises(ParseError, match="invalid"):
        parse(lock, pyproject)


def test_invalid_toml_is_a_parse_error() -> None:
    with pytest.raises(ParseError, match="invalid TOML"):
        parse("[[package]\nname=")
