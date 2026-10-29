from typing import Any

import pytest

from depguard.parsers.models import Ecosystem
from depguard.versions import first_fixed, is_major_bump, normalize


@pytest.mark.parametrize(
    ("ecosystem", "a", "b"),
    [
        ("PyPI", "1.0", "1.0.0"),
        ("PyPI", "2.0.0-rc.1", "2.0.0rc1"),
        ("PyPI", "1.0.POST1", "1.0.post1"),
        ("npm", "1.2.3", "1.2.3"),
    ],
)
def test_equal_versions_normalize_the_same(ecosystem: Ecosystem, a: str, b: str) -> None:
    assert normalize(ecosystem, a) == normalize(ecosystem, b)


def test_different_versions_stay_different() -> None:
    assert normalize("PyPI", "1.0") != normalize("PyPI", "1.0.1")
    assert normalize("npm", "1.0.0") != normalize("npm", "1.0.0-beta")


def test_unparseable_versions_are_kept() -> None:
    assert normalize("npm", "v1.2") == "v1.2"
    assert normalize("PyPI", "not a version") == "not a version"


# Real affected ranges from OSV (GHSA-jf85-cpcp-j695, GHSA-q3w9-g74q-vp5f, GHSA-p6mc-m468-83gw).
LODASH: list[dict[str, Any]] = [
    {
        "package": {"ecosystem": "npm", "name": "lodash"},
        "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "4.17.12"}]}],
    },
    {
        "package": {"ecosystem": "npm", "name": "lodash-es"},
        "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "4.17.14"}]}],
    },
]


def test_first_fixed_uses_only_the_matching_package() -> None:
    assert first_fixed(LODASH, "npm", "lodash", "4.17.4") == "4.17.12"
    assert first_fixed(LODASH, "npm", "lodash-es", "4.17.4") == "4.17.14"
    assert first_fixed(LODASH, "PyPI", "lodash", "4.17.4") is None


def test_prerelease_fix_is_reported_as_published() -> None:
    affected = [
        {
            "package": {"ecosystem": "npm", "name": "express-fileupload"},
            "ranges": [
                {"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.1.6-alpha.6"}]}
            ],
        }
    ]
    assert first_fixed(affected, "npm", "express-fileupload", "0.0.5") == "1.1.6-alpha.6"


def test_smallest_fix_above_the_installed_version_across_ranges() -> None:
    affected = [
        {
            "package": {"ecosystem": "PyPI", "name": "Django"},
            "ranges": [
                {
                    "type": "ECOSYSTEM",
                    # Out of order on purpose: OSV doesn't promise sorted events.
                    "events": [
                        {"fixed": "4.2.8"},
                        {"introduced": "4.2"},
                        {"introduced": "0"},
                        {"fixed": "3.2.23"},
                    ],
                },
                {"type": "ECOSYSTEM", "events": [{"introduced": "5.0"}, {"fixed": "5.0.1"}]},
            ],
        }
    ]
    assert first_fixed(affected, "PyPI", "django", "3.2.1") == "3.2.23"  # names are PEP 503
    assert first_fixed(affected, "PyPI", "django", "4.2.3") == "4.2.8"
    assert first_fixed(affected, "PyPI", "django", "5.0") == "5.0.1"


@pytest.mark.parametrize(
    ("installed", "fixed"),
    [
        ("0.9", "1.0"),  # below the first fix
        ("1.0", None),  # exactly the fixed version: not affected by the first range
        ("1.5", None),  # between a fix and the next introduced
        ("2.0", "2.5"),  # exactly the re-introduced version
        ("2.5", None),  # the second fix
    ],
)
def test_range_edges(installed: str, fixed: str | None) -> None:
    affected = [
        {
            "package": {"ecosystem": "PyPI", "name": "lib"},
            "ranges": [
                {
                    "type": "ECOSYSTEM",
                    "events": [
                        {"introduced": "0"},
                        {"fixed": "1.0"},
                        {"introduced": "2.0"},
                        {"fixed": "2.5"},
                    ],
                }
            ],
        }
    ]
    assert first_fixed(affected, "PyPI", "lib", installed) == fixed


def test_last_affected_means_no_known_fix() -> None:
    affected = [
        {
            "package": {"ecosystem": "npm", "name": "lodash.set"},
            "ranges": [
                {"type": "SEMVER", "events": [{"introduced": "3.7.0"}, {"last_affected": "4.3.2"}]}
            ],
        }
    ]
    assert first_fixed(affected, "npm", "lodash.set", "4.3.2") is None
    assert first_fixed(affected, "npm", "lodash.set", "4.0.0") is None


def test_git_ranges_and_bad_versions_give_no_fix() -> None:
    affected = [
        {
            "package": {"ecosystem": "npm", "name": "a"},
            "ranges": [{"type": "GIT", "events": [{"introduced": "0"}, {"fixed": "abc123"}]}],
        }
    ]
    assert first_fixed(affected, "npm", "a", "1.0.0") is None
    assert first_fixed(LODASH, "npm", "lodash", "not-semver") is None


@pytest.mark.parametrize(
    ("ecosystem", "installed", "fixed", "major"),
    [
        ("npm", "4.17.4", "4.17.12", False),
        ("npm", "2.5.0", "3.0.0", True),
        ("npm", "0.2.4", "0.3.0", True),  # below 1.0 the minor is the breaking number
        ("npm", "0.2.4", "0.2.5", False),
        ("npm", "0.0.1", "0.0.2", True),  # below 0.1.0 even the patch is breaking
        ("npm", "0.0.5", "1.1.6-alpha.6", True),
        ("PyPI", "3.2.1", "3.2.23", False),
        ("PyPI", "1.26.0", "2.0.0", True),
        ("PyPI", "nonsense", "2.0.0", False),
    ],
)
def test_major_bump(ecosystem: Ecosystem, installed: str, fixed: str, major: bool) -> None:
    assert is_major_bump(ecosystem, installed, fixed) is major
