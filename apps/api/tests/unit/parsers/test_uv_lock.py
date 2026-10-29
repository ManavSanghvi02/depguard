from pathlib import Path

from depguard.parsers.models import ParsedService
from depguard.parsers.uv_lock import parse_uv_lock

REAL = Path(__file__).parents[2] / "fixtures" / "real"


def parse(lock: str) -> ParsedService:
    return parse_uv_lock(lock.encode(), "uv.lock")


def test_real_fastapi_template_lockfile() -> None:
    content = (REAL / "full-stack-fastapi-template" / "uv.lock").read_bytes()
    service = parse_uv_lock(content, "uv.lock")
    entries = {e.name: e for e in service.entries}

    assert len(service.entries) == 79  # 80 packages minus the project itself ("app")
    assert "app" not in entries
    assert sum(e.dev for e in service.entries) == 15
    assert entries["fastapi"].key == "fastapi==0.141.1"
    assert entries["fastapi"].direct is True and entries["fastapi"].dev is False
    assert entries["pytest"].dev is True  # [package.dev-dependencies]
    assert entries["zizmor"].dev is True  # [manifest.dependency-groups]
    assert entries["sqlalchemy"].direct is False and entries["sqlalchemy"].dev is False


def test_real_empty_lockfile_gives_an_empty_service() -> None:
    service = parse_uv_lock((REAL / "textual" / "uv.lock").read_bytes(), "uv.lock")

    assert service.entries == [] and service.edges == []


PROJECT = """
[[package]]
name = "app"
version = "0.1.0"
source = { editable = "." }
dependencies = [{ name = "web", extra = ["fast"] }]

[package.dev-dependencies]
dev = [{ name = "pytest" }]
"""


def test_dev_means_unreachable_from_production() -> None:
    service = parse(
        PROJECT
        + """
[[package]]
name = "web"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "shared" }]

[package.optional-dependencies]
fast = [{ name = "speedups" }]

[[package]]
name = "pytest"
version = "8.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "shared" }, { name = "pluggy" }]

[[package]]
name = "shared"
version = "1.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "pluggy"
version = "1.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "speedups"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
"""
    )
    dev = {e.name: e.dev for e in service.entries}

    # shared is used by both, so it is production; speedups comes in through web[fast].
    assert dev == {"web": False, "pytest": True, "shared": False, "pluggy": True, "speedups": False}
    assert ("web==1.0", "speedups==1.0") in {(e.parent_key, e.child_key) for e in service.edges}


def test_forked_versions_follow_the_version_in_the_reference() -> None:
    service = parse(
        """
[[package]]
name = "app"
version = "0.1.0"
source = { virtual = "." }
dependencies = [
    { name = "numpy", version = "1.26.4", marker = "python_full_version < '3.10'" },
    { name = "numpy", version = "2.1.0", marker = "python_full_version >= '3.10'" },
]

[[package]]
name = "numpy"
version = "1.26.4"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "numpy"
version = "2.1.0"
source = { registry = "https://pypi.org/simple" }
"""
    )

    assert sorted(e.key for e in service.entries) == ["numpy==1.26.4", "numpy==2.1.0"]
    assert all(e.direct for e in service.entries)


def test_git_and_path_sources_are_skipped() -> None:
    service = parse(
        """
[[package]]
name = "mylib"
version = "0.1.0"
source = { git = "https://github.com/o/mylib?rev=abc#abc" }

[[package]]
name = "local"
version = "0.1.0"
source = { path = "../local" }
"""
    )

    assert service.entries == []
    assert {s.reason for s in service.skipped} == {"not_from_registry"}
