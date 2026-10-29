from pathlib import Path

import pytest

from depguard.parsers.models import ParsedService, ParseError
from depguard.parsers.requirements_txt import parse_requirements_txt

REAL = Path(__file__).parents[2] / "fixtures" / "real" / "defectdojo"


def parse(text: str) -> ParsedService:
    return parse_requirements_txt(text.encode(), "requirements.txt")


def test_real_defectdojo_requirements() -> None:
    service = parse_requirements_txt((REAL / "requirements.txt").read_bytes(), "requirements.txt")
    entries = {e.name: e for e in service.entries}

    assert len(service.entries) == 67
    assert all(e.direct and not e.dev for e in service.entries)
    assert entries["django"].key == "django==5.2.17"  # "Django" normalised
    assert entries["certifi"].version == "2026.10.19"  # inline comment removed
    assert entries["celery"].version == "5.6.3"  # extras ignored
    # "bleach[css]" has no version, but bleach is pinned on another line, so nothing is skipped.
    assert service.skipped == []


def test_only_exact_pins_are_kept() -> None:
    service = parse(
        "\n".join(
            [
                "pinned==1.0.0",
                "arbitrary===2.0",
                "ranged>=2.0",
                "compatible~=1.4",
                "wildcard==1.*",
                "bare",
                "two-specs==1.0,!=1.1",
            ]
        )
    )

    # The key always uses "==", whichever pin operator the file used.
    assert [e.key for e in service.entries] == ["pinned==1.0.0", "arbitrary==2.0"]
    assert {s.name: s.spec for s in service.skipped} == {
        "ranged": ">=2.0",
        "compatible": "~=1.4",
        "wildcard": "==1.*",
        "bare": "",
        "two-specs": "!=1.1,==1.0",
    }
    assert {s.reason for s in service.skipped} == {"version_unknown"}


def test_line_syntax_variants() -> None:
    text = (
        "﻿# a comment\r\n"
        "-r base.txt\r\n"
        "--index-url https://pypi.org/simple\r\n"
        "hashed==1.0 \\\r\n"
        "    --hash=sha256:abc\r\n"
        "marked==2.0 ; python_version < '3.11'\r\n"
        "dup==1.0\r\n"
        "dup==1.1\r\n"
    )

    service = parse(text)

    assert [e.key for e in service.entries] == ["hashed==1.0", "marked==2.0", "dup==1.1"]
    assert service.edges[0].parent_key is None


def test_urls_paths_and_editables_are_not_from_registry() -> None:
    service = parse(
        "-e .\n"
        "git+https://github.com/o/r.git#egg=r\n"
        "pkg @ https://example.com/pkg-1.0.tar.gz\n"
        "./local/pkg\n"
    )

    assert service.entries == []
    assert [s.reason for s in service.skipped] == ["not_from_registry"] * 4


def test_non_utf8_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_requirements_txt(b"\xff\xfe\x00bad", "requirements.txt")
