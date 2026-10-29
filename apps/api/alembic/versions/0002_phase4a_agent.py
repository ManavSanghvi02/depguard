"""Phase 4a: explanations table, findings.is_bundled, repos.is_private.

Same security pattern as 0001: RLS on, and depguard_api gets only what it needs. Explanations are
only ever added (one row per attempt), so the API may read and insert them, not change them.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "findings",
        sa.Column("is_bundled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("repos", sa.Column("is_private", sa.Boolean(), nullable=True))
    op.create_table(
        "explanations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("data_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("fact_check_passed", sa.Boolean(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('ok', 'unavailable')", name="explanation_status"),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "explanations_latest", "explanations", ["finding_id", "created_at"], unique=False
    )
    op.create_index(op.f("ix_explanations_cache_key"), "explanations", ["cache_key"], unique=False)

    op.execute("ALTER TABLE explanations ENABLE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT ON explanations TO depguard_api")
    op.execute(
        "CREATE POLICY depguard_api_select ON explanations FOR SELECT TO depguard_api USING (true)"
    )
    op.execute(
        "CREATE POLICY depguard_api_insert ON explanations FOR INSERT TO depguard_api"
        " WITH CHECK (true)"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_explanations_cache_key"), table_name="explanations")
    op.drop_index("explanations_latest", table_name="explanations")
    op.drop_table("explanations")
    op.drop_column("repos", "is_private")
    op.drop_column("findings", "is_bundled")
