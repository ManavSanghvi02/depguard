"""The migration, row-level security and each role's grants (security.md §6)."""

import pytest
from alembic import command
from conftest import TEST_DATABASE, alembic_config, owner_query, with_session
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

TABLES = {
    "profiles", "repos", "services", "scans", "skipped_packages", "advisories", "kev_entries",
    "epss_scores", "findings", "finding_scores", "refresh_runs", "explanations",
}  # fmt: skip


def run(role: str, statement: str) -> None:
    async def test(session: AsyncSession) -> None:
        await session.execute(text(statement))
        await session.rollback()

    with_session(role, test)


def refused(role: str, statement: str) -> bool:
    try:
        run(role, statement)
    except ProgrammingError as error:
        return getattr(error.orig, "pgcode", None) == "42501"  # insufficient_privilege
    return False


def test_migration_downgrades_and_upgrades(postgres: None) -> None:
    command.downgrade(alembic_config(), "base")
    command.upgrade(alembic_config(), "head")


def test_rls_is_on_for_every_table(postgres: None) -> None:
    rows = owner_query(
        TEST_DATABASE,
        lambda connection: connection.fetch(
            "SELECT relname, relrowsecurity FROM pg_class "
            "WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' "
            "AND relname <> 'alembic_version'"
        ),
    )
    assert {row["relname"] for row in rows} == TABLES
    assert all(row["relrowsecurity"] for row in rows)


def test_roles_do_not_bypass_rls_or_own_tables(postgres: None) -> None:
    roles = owner_query(
        TEST_DATABASE,
        lambda connection: connection.fetch(
            "SELECT rolname, rolbypassrls, rolsuper FROM pg_roles "
            "WHERE rolname IN ('depguard_api', 'depguard_refresh') ORDER BY rolname"
        ),
    )
    owners = owner_query(
        TEST_DATABASE,
        lambda connection: connection.fetch(
            "SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'public'"
        ),
    )
    assert [tuple(row) for row in roles] == [
        ("depguard_api", False, False),
        ("depguard_refresh", False, False),
    ]
    assert {row["tableowner"] for row in owners}.isdisjoint({"depguard_api", "depguard_refresh"})


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM profiles",
        "SELECT * FROM skipped_packages",
        "SELECT owner FROM repos",  # only id and user_id
        "UPDATE findings SET is_dev = true",
        "DELETE FROM finding_scores",
        "INSERT INTO advisories (id) VALUES ('GHSA-x')",
        "TRUNCATE findings",
        "SELECT * FROM explanations",
    ],
)
def test_refresh_role_is_refused_outside_its_job(db: None, statement: str) -> None:
    assert refused("depguard_refresh", statement)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT id, user_id FROM repos",
        "SELECT * FROM findings JOIN scans ON scans.id = findings.scan_id",
        "SELECT * FROM finding_scores",
        "TRUNCATE kev_entries, epss_scores",
        "INSERT INTO refresh_runs (status) VALUES ('ok')",
    ],
)
def test_refresh_role_can_do_its_job(db: None, statement: str) -> None:
    run("depguard_refresh", statement)


@pytest.mark.parametrize(
    "statement",
    [
        "TRUNCATE kev_entries",
        "INSERT INTO epss_scores VALUES ('CVE-1', 0.1, 0.5, '2026-10-28')",
        "INSERT INTO refresh_runs (status) VALUES ('ok')",
    ],
)
def test_api_role_cannot_write_refresh_data(db: None, statement: str) -> None:
    assert refused("depguard_api", statement)


def test_api_role_can_read_explanations(db: None) -> None:
    run("depguard_api", "SELECT * FROM explanations")


@pytest.mark.parametrize(
    "statement",
    ["UPDATE explanations SET text = 'changed'", "DELETE FROM explanations"],
)
def test_explanations_are_only_ever_added(db: None, statement: str) -> None:
    # One row per attempt: an explanation that was shown can't be rewritten afterwards.
    assert refused("depguard_api", statement)


def test_api_role_reads_and_writes_application_tables(db: None) -> None:
    run(
        "depguard_api",
        "INSERT INTO profiles (user_id, github_id, github_login) "
        "VALUES (gen_random_uuid(), 1, 'someone')",
    )
    run("depguard_api", "SELECT * FROM kev_entries, epss_scores, refresh_runs")
