"""Phase 3 schema: tables, the depguard_api and depguard_refresh roles, row-level security.

Grants and policies follow security.md §6. RLS is on for every table, so a role sees no rows unless
a policy allows it; neither role owns a table or has BYPASSRLS.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ROLES = ("depguard_api", "depguard_refresh")
TABLES = [
    "profiles",
    "repos",
    "services",
    "scans",
    "skipped_packages",
    "advisories",
    "kev_entries",
    "epss_scores",
    "findings",
    "finding_scores",
    "refresh_runs",
]
# Written only by the daily refresh; the API just reads them.
API_READ_ONLY = {"kev_entries", "epss_scores", "refresh_runs"}
# depguard_refresh: table -> (grant, actions that need a policy). TRUNCATE skips row policies, so
# it is granted only where a full replace is the point.
REFRESH_ACCESS = {
    "kev_entries": (
        "SELECT, INSERT, UPDATE, DELETE, TRUNCATE",
        ["SELECT", "INSERT", "UPDATE", "DELETE"],
    ),
    "epss_scores": (
        "SELECT, INSERT, UPDATE, DELETE, TRUNCATE",
        ["SELECT", "INSERT", "UPDATE", "DELETE"],
    ),
    "refresh_runs": ("SELECT, INSERT", ["SELECT", "INSERT"]),
    "finding_scores": ("SELECT, INSERT", ["SELECT", "INSERT"]),
    "findings": ("SELECT", ["SELECT"]),
    "scans": ("SELECT", ["SELECT"]),
    "services": ("SELECT", ["SELECT"]),
    "advisories": ("SELECT", ["SELECT"]),
    "repos": ("SELECT (id, user_id)", ["SELECT"]),  # to group reach by user; no names
}


def policy(table: str, role: str, action: str) -> str:
    name = f"{role}_{action.lower()}"
    if action == "INSERT":
        return f"CREATE POLICY {name} ON {table} FOR INSERT TO {role} WITH CHECK (true)"
    if action in ("SELECT", "DELETE"):
        return f"CREATE POLICY {name} ON {table} FOR {action} TO {role} USING (true)"
    return f"CREATE POLICY {name} ON {table} FOR {action} TO {role} USING (true) WITH CHECK (true)"


def secure() -> None:
    for role in ROLES:
        # NOLOGIN until `make migrate` sets a password from the role's URL
        # (db/set_role_passwords.py).
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') "
            f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$"
        )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {', '.join(ROLES)}")
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

        # depguard_api: read/write on application tables. Isolation between users is enforced in
        # API code and tests, not here (security.md §7).
        if table in API_READ_ONLY:
            op.execute(f"GRANT SELECT ON {table} TO depguard_api")
            op.execute(policy(table, "depguard_api", "SELECT"))
        else:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO depguard_api")
            op.execute(policy(table, "depguard_api", "ALL"))

        if table in REFRESH_ACCESS:
            grant, actions = REFRESH_ACCESS[table]
            op.execute(f"GRANT {grant} ON {table} TO depguard_refresh")
            for action in actions:
                op.execute(policy(table, "depguard_refresh", action))


def upgrade() -> None:
    op.create_table(
        "advisories",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column(
            "aliases", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("cvss_score", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("cvss_vector", sa.Text(), nullable=True),
        sa.Column("cvss_version", sa.Text(), nullable=True),
        sa.Column("is_malicious", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("withdrawn", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("modified", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "epss_scores",
        sa.Column("cve_id", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("percentile", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("data_date", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("cve_id"),
    )
    op.create_table(
        "kev_entries",
        sa.Column("cve_id", sa.Text(), nullable=False),
        sa.Column("date_added", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("known_ransomware", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("cve_id"),
    )
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("github_login", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("github_id"),
    )
    op.create_table(
        "refresh_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "ran_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("kev_count", sa.Integer(), nullable=True),
        sa.Column("epss_count", sa.Integer(), nullable=True),
        sa.Column("epss_date", sa.Date(), nullable=True),
        sa.Column("rescored", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "repos",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("default_branch", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["profiles.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "owner", "name"),
    )
    op.create_index(op.f("ix_repos_user_id"), "repos", ["user_id"], unique=False)
    op.create_table(
        "scans",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "partial_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("commit_sha", sa.Text(), nullable=True),
        sa.Column("data_date", sa.Date(), nullable=True),
        sa.Column("osv_complete", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'partial', 'failed')", name="scan_status"
        ),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("scans_repo_created", "scans", ["repo_id", "created_at"], unique=False)
    op.create_table(
        "services",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("repo_id", sa.UUID(), nullable=False),
        sa.Column("lockfile_path", sa.Text(), nullable=False),
        sa.Column("ecosystem", sa.Text(), nullable=False),
        sa.Column("lockfile_type", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["repo_id"], ["repos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repo_id", "lockfile_path"),
    )
    op.create_index(op.f("ix_services_repo_id"), "services", ["repo_id"], unique=False)
    op.create_table(
        "findings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("scan_id", sa.UUID(), nullable=False),
        sa.Column("service_id", sa.UUID(), nullable=False),
        sa.Column("dep_key", sa.Text(), nullable=False),
        sa.Column("ecosystem", sa.Text(), nullable=False),
        sa.Column("package", sa.Text(), nullable=False),
        sa.Column("installed_version", sa.Text(), nullable=False),
        sa.Column("installed_version_norm", sa.Text(), nullable=False),
        sa.Column("advisory_id", sa.Text(), nullable=False),
        sa.Column("aliases", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("cvss", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("is_malicious", sa.Boolean(), nullable=False),
        sa.Column("fixed_version", sa.Text(), nullable=True),
        sa.Column("major_bump", sa.Boolean(), nullable=False),
        sa.Column("is_dev", sa.Boolean(), nullable=False),
        sa.Column("is_direct", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["advisory_id"],
            ["advisories.id"],
        ),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scan_id", "service_id", "dep_key", "advisory_id"),
    )
    op.create_index(op.f("ix_findings_scan_id"), "findings", ["scan_id"], unique=False)
    op.create_index(op.f("ix_findings_service_id"), "findings", ["service_id"], unique=False)
    op.create_table(
        "skipped_packages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("scan_id", sa.UUID(), nullable=False),
        sa.Column("service_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("spec", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "reason IN ('version_unknown', 'not_from_registry', 'osv_unavailable')",
            name="skip_reason",
        ),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_skipped_packages_scan_id"), "skipped_packages", ["scan_id"], unique=False
    )
    op.create_index(
        op.f("ix_skipped_packages_service_id"), "skipped_packages", ["service_id"], unique=False
    )
    op.create_table(
        "finding_scores",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("data_date", sa.Date(), nullable=True),
        sa.Column("in_kev", sa.Boolean(), nullable=False),
        sa.Column("epss", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("epss_percentile", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("cvss", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("reach", sa.Integer(), nullable=False),
        sa.Column("reach_complete", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("subgroup", sa.Text(), nullable=True),
        sa.Column("risk_score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "finding_scores_latest", "finding_scores", ["finding_id", "created_at"], unique=False
    )
    secure()


def downgrade() -> None:
    op.drop_index("finding_scores_latest", table_name="finding_scores")
    op.drop_table("finding_scores")
    op.drop_index(op.f("ix_skipped_packages_service_id"), table_name="skipped_packages")
    op.drop_index(op.f("ix_skipped_packages_scan_id"), table_name="skipped_packages")
    op.drop_table("skipped_packages")
    op.drop_index(op.f("ix_findings_service_id"), table_name="findings")
    op.drop_index(op.f("ix_findings_scan_id"), table_name="findings")
    op.drop_table("findings")
    op.drop_index(op.f("ix_services_repo_id"), table_name="services")
    op.drop_table("services")
    op.drop_index("scans_repo_created", table_name="scans")
    op.drop_table("scans")
    op.drop_index(op.f("ix_repos_user_id"), table_name="repos")
    op.drop_table("repos")
    op.drop_table("refresh_runs")
    op.drop_table("profiles")
    op.drop_table("kev_entries")
    op.drop_table("epss_scores")
    op.drop_table("advisories")
    # The roles stay: they belong to the whole Postgres server and other databases may use them.
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {', '.join(ROLES)}")
