"""The daily bulk files (ADR-0004): CISA KEV (JSON) and FIRST EPSS (gzipped CSV).

Each parser checks that the file looks complete, because the refresh replaces the whole table:
a truncated download must never wipe the data.
"""

import csv
import gzip
import io
import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
EPSS_URL = "https://epss.empiricalsecurity.com/epss_scores-current.csv.gz"
# Far below the real sizes (about 1,800 KEV entries and 300,000 EPSS rows in 2026), far above
# what a broken or cut-off download would give.
MIN_KEV_ENTRIES = 1_000
MIN_EPSS_ROWS = 100_000
SCORE_DATE = re.compile(r"score_date:(\d{4}-\d{2}-\d{2})")

KevRow = tuple[str, date, date | None, bool]  # cve_id, date_added, due_date, known_ransomware
EpssRow = tuple[str, Decimal, Decimal, date]  # cve_id, score, percentile, data_date


class FeedError(Exception):
    """The file is malformed or too small to be complete."""


def round3(value: str) -> Decimal:
    # 3 decimals (ADR-0003): tiny daily changes don't count as an input change.
    return Decimal(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def parse_kev(data: bytes, minimum: int | None = None) -> list[KevRow]:
    minimum = MIN_KEV_ENTRIES if minimum is None else minimum
    try:
        entries = json.loads(data)["vulnerabilities"]
        rows = {
            entry["cveID"]: (
                entry["cveID"],
                date.fromisoformat(entry["dateAdded"]),
                date.fromisoformat(entry["dueDate"]) if entry.get("dueDate") else None,
                entry.get("knownRansomwareCampaignUse") == "Known",
            )
            for entry in entries
        }
    except (ValueError, KeyError, TypeError) as error:
        raise FeedError(f"KEV catalog is malformed: {error}") from error
    if len(rows) < minimum:
        raise FeedError(f"KEV catalog has only {len(rows)} entries; expected at least {minimum}")
    return sorted(rows.values())


def parse_epss(data: bytes, minimum: int | None = None) -> list[EpssRow]:
    minimum = MIN_EPSS_ROWS if minimum is None else minimum
    try:
        text = gzip.decompress(data).decode("utf-8")
        first_line, _, body = text.partition("\n")
        # First line: "#model_version:v2026.06.15,score_date:2026-10-28T12:03:13Z"
        found = SCORE_DATE.search(first_line)
        if found is None:
            raise FeedError("EPSS file has no score date")
        data_date = date.fromisoformat(found.group(1))
        rows = {
            row["cve"]: (row["cve"], round3(row["epss"]), round3(row["percentile"]), data_date)
            for row in csv.DictReader(io.StringIO(body))
        }
    except (OSError, ValueError, KeyError, ArithmeticError) as error:
        raise FeedError(f"EPSS file is malformed: {error}") from error
    if len(rows) < minimum:
        raise FeedError(f"EPSS file has only {len(rows)} rows; expected at least {minimum}")
    return sorted(rows.values())
