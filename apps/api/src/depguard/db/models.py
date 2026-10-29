"""Postgres tables (architecture §5.2). Roles, grants and row-level security are in the
migration."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def cascade(target: str) -> Mapped[uuid.UUID]:
    # Deleting a repo deletes its services, scans, findings and scores (security.md §11).
    return mapped_column(ForeignKey(target, ondelete="CASCADE"), index=True)


class Profile(Base):
    __tablename__ = "profiles"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)  # Supabase auth user ID
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True)  # numeric; logins can change
    github_login: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class Repo(Base):
    __tablename__ = "repos"
    __table_args__ = (UniqueConstraint("user_id", "owner", "name"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = cascade("profiles.user_id")
    owner: Mapped[str] = mapped_column(Text)  # lowercase: GitHub names are case-insensitive
    name: Mapped[str] = mapped_column(Text)
    default_branch: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class Service(Base):
    """One lockfile. Its ID is also the Neo4j Service node's ID."""

    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("repo_id", "lockfile_path"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    repo_id: Mapped[uuid.UUID] = cascade("repos.id")
    lockfile_path: Mapped[str] = mapped_column(Text)
    ecosystem: Mapped[str] = mapped_column(Text)
    lockfile_type: Mapped[str] = mapped_column(Text)


class Scan(Base):
    __tablename__ = "scans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'partial', 'failed')", name="scan_status"
        ),
        Index("scans_repo_created", "repo_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text)
    partial_reasons: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'"))
    commit_sha: Mapped[str | None] = mapped_column(Text)
    data_date: Mapped[date | None] = mapped_column(Date)  # the EPSS snapshot the scores used
    # OSV checked every package (no osv_unavailable skips). Only such scans count for reach.
    osv_complete: Mapped[bool | None]
    created_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class SkippedPackage(Base):
    __tablename__ = "skipped_packages"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('version_unknown', 'not_from_registry', 'osv_unavailable')",
            name="skip_reason",
        ),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = cascade("scans.id")
    service_id: Mapped[uuid.UUID] = cascade("services.id")
    name: Mapped[str] = mapped_column(Text)
    spec: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)


class Advisory(Base):
    """OSV cache. `raw` is null for an ID whose details couldn't be fetched yet."""

    __tablename__ = "advisories"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    summary: Mapped[str | None] = mapped_column(Text)
    cvss_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    cvss_vector: Mapped[str | None] = mapped_column(Text)
    cvss_version: Mapped[str | None] = mapped_column(Text)
    is_malicious: Mapped[bool] = mapped_column(server_default=text("false"))
    withdrawn: Mapped[bool] = mapped_column(server_default=text("false"))
    modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KevEntry(Base):
    __tablename__ = "kev_entries"
    cve_id: Mapped[str] = mapped_column(Text, primary_key=True)
    date_added: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    known_ransomware: Mapped[bool]


class EpssScore(Base):
    __tablename__ = "epss_scores"
    cve_id: Mapped[str] = mapped_column(Text, primary_key=True)
    # Rounded to 3 decimals on load (ADR-0003), so tiny daily changes don't add score rows.
    score: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    percentile: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    data_date: Mapped[date] = mapped_column(Date)


class Finding(Base):
    """One per (lockfile entry, merged advisory group)."""

    __tablename__ = "findings"
    __table_args__ = (UniqueConstraint("scan_id", "service_id", "dep_key", "advisory_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = cascade("scans.id")
    service_id: Mapped[uuid.UUID] = cascade("services.id")
    dep_key: Mapped[str] = mapped_column(Text)  # the Neo4j Dep key, for paths
    ecosystem: Mapped[str] = mapped_column(Text)
    package: Mapped[str] = mapped_column(Text)
    installed_version: Mapped[str] = mapped_column(Text)  # as the lockfile spells it
    installed_version_norm: Mapped[str] = mapped_column(Text)  # for reach: 1.0 == 1.0.0
    advisory_id: Mapped[str] = mapped_column(ForeignKey("advisories.id"))  # the group's main ID
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text))  # every ID in the group, incl. CVEs
    summary: Mapped[str | None] = mapped_column(Text)
    cvss: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))  # highest in the group
    is_malicious: Mapped[bool]
    fixed_version: Mapped[str | None] = mapped_column(Text)
    major_bump: Mapped[bool]
    is_dev: Mapped[bool]
    is_direct: Mapped[bool]


class FindingScore(Base):
    """A new row only when an input changed (ADR-0003). The latest row is the current score."""

    __tablename__ = "finding_scores"
    __table_args__ = (Index("finding_scores_latest", "finding_id", "created_at"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"))
    data_date: Mapped[date | None] = mapped_column(Date)
    in_kev: Mapped[bool]
    epss: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    epss_percentile: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    cvss: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    reach: Mapped[int]
    # False if a repo of this user had no fully checked scan, so reach may be too low.
    reach_complete: Mapped[bool] = mapped_column(server_default=text("true"))
    tier: Mapped[str] = mapped_column(Text)
    subgroup: Mapped[str | None] = mapped_column(Text)
    risk_score: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    created_at: Mapped[datetime] = created_at()


class RefreshRun(Base):
    __tablename__ = "refresh_runs"
    id: Mapped[uuid.UUID] = uuid_pk()
    ran_at: Mapped[datetime] = created_at()
    status: Mapped[str] = mapped_column(Text)  # ok / failed
    kev_count: Mapped[int | None]
    epss_count: Mapped[int | None]
    epss_date: Mapped[date | None] = mapped_column(Date)
    rescored: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(Text)
