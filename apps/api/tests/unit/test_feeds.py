import gzip
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from depguard.advisories.feeds import FeedError, parse_epss, parse_kev

FEEDS = Path(__file__).parents[1] / "fixtures" / "feeds"
KEV = (FEEDS / "kev-sample.json").read_bytes()
EPSS = gzip.compress((FEEDS / "epss-sample.csv").read_bytes())


def test_kev_sample_parses() -> None:
    rows = parse_kev(KEV, minimum=1)

    assert len(rows) == 4
    assert all(cve.startswith("CVE-") and isinstance(added, date) for cve, added, _, _ in rows)
    assert sum(ransomware for *_, ransomware in rows) == 2


def test_epss_sample_parses_and_rounds_to_3_decimals() -> None:
    rows = {row[0]: row for row in parse_epss(EPSS, minimum=1)}

    assert rows["CVE-2019-10744"] == (
        "CVE-2019-10744",
        Decimal("0.050"),
        Decimal("0.922"),
        date(2026, 10, 28),
    )
    assert rows["CVE-2021-4264"][1:3] == (Decimal("0.012"), Decimal("0.668"))


def test_too_small_files_are_refused() -> None:
    # The real minimums: a cut-off download must never replace the tables.
    with pytest.raises(FeedError, match="only 4 entries"):
        parse_kev(KEV)
    with pytest.raises(FeedError, match="only 7 rows"):
        parse_epss(EPSS)


@pytest.mark.parametrize(
    "data",
    [b"not json", json.dumps({"vulnerabilities": [{"cveID": "CVE-1"}]}).encode()],
)
def test_malformed_kev_is_refused(data: bytes) -> None:
    with pytest.raises(FeedError):
        parse_kev(data, minimum=0)


@pytest.mark.parametrize(
    "data",
    [
        b"not gzip",
        gzip.compress(b"cve,epss,percentile\nCVE-1,0.1,0.5\n"),  # no score date line
        gzip.compress(b"#score_date:2026-10-28\ncve,epss,percentile\nCVE-1,abc,0.5\n"),
    ],
)
def test_malformed_epss_is_refused(data: bytes) -> None:
    with pytest.raises(FeedError):
        parse_epss(data, minimum=0)
