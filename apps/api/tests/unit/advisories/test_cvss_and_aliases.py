from decimal import Decimal

from fake_osv import recorded_vuln

from depguard.advisories.aliases import AdvisoryFacts, merge, representative
from depguard.advisories.cvss import best_cvss


def record(vuln_id: str) -> dict[str, object]:
    found = recorded_vuln(vuln_id)
    assert found is not None
    return found


def test_cvss_scores_from_real_vectors() -> None:
    scores = {
        vuln_id: best_cvss(record(vuln_id))
        for vuln_id in ("GHSA-jf85-cpcp-j695", "GHSA-c6rp-wrp9-qr4q", "GHSA-p6mc-m468-83gw")
    }
    assert {k: v.score if v else None for k, v in scores.items()} == {
        "GHSA-jf85-cpcp-j695": Decimal("9.1"),
        "GHSA-c6rp-wrp9-qr4q": Decimal("8.8"),
        "GHSA-p6mc-m468-83gw": Decimal("7.4"),
    }


def test_v3_is_preferred_over_v4() -> None:
    # GHSA-462w-v97r-4m45 (jinja2) has both a v3.1 and a v4.0 vector.
    cvss = best_cvss(record("GHSA-462w-v97r-4m45"))
    assert cvss is not None and cvss.version.startswith("3")


def test_v4_is_used_when_there_is_no_v3() -> None:
    cvss = best_cvss(record("PYSEC-2026-1471"))
    assert cvss is not None and cvss.version == "4.0"


def test_missing_or_broken_severity_gives_none() -> None:
    assert best_cvss(record("MAL-2025-20690")) is None
    assert best_cvss({"severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/garbage"}]}) is None


def facts(
    vuln_id: str, *aliases: str, cvss: str | None = None, fix: str | None = None
) -> AdvisoryFacts:
    return AdvisoryFacts(
        id=vuln_id,
        aliases=aliases,
        summary=f"about {vuln_id}",
        cvss=Decimal(cvss) if cvss else None,
        fixed_version=fix,
    )


def test_real_ghsa_and_pysec_pair_becomes_one_finding() -> None:
    ghsa, pysec = record("GHSA-462w-v97r-4m45"), record("PYSEC-2019-217")
    merged = merge(
        [
            facts(str(ghsa["id"]), *ghsa["aliases"], cvss="5.4"),  # type: ignore[misc]
            facts(str(pysec["id"]), *pysec["aliases"]),  # type: ignore[misc]
        ]
    )

    assert len(merged) == 1
    assert merged[0].advisory_id == "GHSA-462w-v97r-4m45"
    assert merged[0].cve_ids == ["CVE-2019-10906"]
    assert merged[0].cvss == Decimal("5.4")
    assert merged[0].summary == "about GHSA-462w-v97r-4m45"


def test_merging_is_transitive() -> None:
    # A and C share nothing directly, but both share an alias with B.
    merged = merge(
        [facts("PYSEC-1", "CVE-1"), facts("GHSA-b", "CVE-1", "CVE-2"), facts("OSV-c", "CVE-2")]
    )
    assert [m.ids for m in merged] == [("CVE-1", "CVE-2", "GHSA-b", "OSV-c", "PYSEC-1")]


def test_unrelated_advisories_stay_apart_and_sorted() -> None:
    merged = merge([facts("GHSA-z"), facts("GHSA-a")])
    assert [m.advisory_id for m in merged] == ["GHSA-a", "GHSA-z"]


def test_group_takes_highest_cvss_every_fix_and_malicious_flag() -> None:
    merged = merge(
        [
            facts("GHSA-a", "MAL-1", cvss="7.5", fix="1.2.0"),
            facts("MAL-1", "GHSA-a", fix="1.3.0"),
            facts("PYSEC-a", "GHSA-a", cvss="9.8"),
        ]
    )
    assert len(merged) == 1
    assert merged[0].cvss == Decimal("9.8")
    assert merged[0].is_malicious
    assert sorted(merged[0].fixed_versions) == ["1.2.0", "1.3.0"]


def test_representative_order() -> None:
    assert representative(["PYSEC-1", "MAL-1", "GHSA-b", "GHSA-a"]) == "GHSA-a"
    assert representative(["OSV-1", "MAL-1", "PYSEC-1"]) == "PYSEC-1"
    assert representative(["OSV-2", "MAL-9"]) == "MAL-9"
    assert representative(["OSV-2", "OSV-1"]) == "OSV-1"
