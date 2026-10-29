from compare_osv_scanner import Difference, compare, package_key, scanner_groups

LODASH = package_key("npm", "lodash", "4.17.4")
JINJA = package_key("PyPI", "Jinja2", "2.10.0")


def test_findings_match_on_any_shared_id() -> None:
    ours = {LODASH: [frozenset({"GHSA-jf85-cpcp-j695", "CVE-2019-10744"})]}
    theirs = {LODASH: [frozenset({"CVE-2019-10744"})]}  # a different main ID, same problem

    assert compare(ours, theirs) == []


def test_differences_name_the_side_that_has_the_finding() -> None:
    ours = {LODASH: [frozenset({"GHSA-a"})], JINJA: [frozenset({"PYSEC-1"})]}
    theirs = {LODASH: [frozenset({"GHSA-a"}), frozenset({"GHSA-b"})]}

    assert compare(ours, theirs) == [  # sorted by package: PyPI before npm
        Difference(JINJA, "DepGuard only", frozenset({"PYSEC-1"})),
        Difference(LODASH, "OSV-Scanner only", frozenset({"GHSA-b"})),
    ]


def test_names_and_versions_are_normalised() -> None:
    assert JINJA == ("PyPI", "jinja2", "2.10")


def test_scanner_report_groups_include_aliases() -> None:
    report = {
        "results": [
            {
                "packages": [
                    {
                        "package": {"name": "Jinja2", "version": "2.10", "ecosystem": "PyPI"},
                        "vulnerabilities": [
                            {"id": "GHSA-462w-v97r-4m45", "aliases": ["CVE-2019-10906"]},
                            {"id": "PYSEC-2019-217", "aliases": ["CVE-2019-10906"]},
                        ],
                        "groups": [{"ids": ["GHSA-462w-v97r-4m45", "PYSEC-2019-217"]}],
                    }
                ]
            }
        ]
    }

    assert scanner_groups(report) == {
        JINJA: [frozenset({"GHSA-462w-v97r-4m45", "PYSEC-2019-217", "CVE-2019-10906"})]
    }
