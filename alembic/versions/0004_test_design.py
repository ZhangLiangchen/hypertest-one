"""Canonical test cases and relational risk test coverage.

Revision ID: 0004_test_design
Revises: 0003_risk_planner
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_test_design"
down_revision = "0003_risk_planner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_mission_proposals_type", "mission_proposals", type_="check")
    op.create_check_constraint(
        "ck_mission_proposals_type",
        "mission_proposals",
        "proposal_type IN ('REQUIREMENT', 'RISK', 'TEST_CASE')",
    )
    op.create_table(
        "test_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("source_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("case_fingerprint", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "test_type",
            sa.Enum(
                "FUNCTIONAL",
                "BOUNDARY",
                "NEGATIVE",
                "FAILURE",
                "CONCURRENCY",
                "CONSISTENCY",
                "COMPATIBILITY",
                "SECURITY",
                "PERFORMANCE",
                "RELIABILITY",
                "UPGRADE",
                "DATA",
                "RECOVERY",
                name="ck_test_cases_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum(
                "P0",
                "P1",
                "P2",
                "P3",
                name="ck_test_cases_priority",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("preconditions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("expected_result", sa.Text(), nullable=False),
        sa.Column(
            "lifecycle_status",
            sa.Enum(
                "DRAFT",
                "ACTIVE",
                "SUPERSEDED",
                "DEPRECATED",
                name="ck_test_cases_lifecycle",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column(
            "derived_from_id", sa.Uuid(), sa.ForeignKey("test_cases.id", ondelete="RESTRICT")
        ),
        sa.Column("created_by_type", sa.String(32), nullable=False),
        sa.Column("created_by_ref", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.UniqueConstraint("project_id", "key", name="uq_test_case_key"),
        sa.UniqueConstraint(
            "source_snapshot_id", "case_fingerprint", name="uq_test_case_fingerprint"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="ck_test_case_confidence"
        ),
    )
    op.create_table(
        "risk_test_cases",
        sa.Column(
            "risk_id", sa.Uuid(), sa.ForeignKey("risks.id", ondelete="RESTRICT"), primary_key=True
        ),
        sa.Column(
            "test_case_id",
            sa.Uuid(),
            sa.ForeignKey("test_cases.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("project_id", "source_snapshot_id", "test_type", "lifecycle_status"):
        op.create_index(f"ix_test_cases_{column}", "test_cases", [column])
    op.create_index("ix_risk_test_cases_test_case_id", "risk_test_cases", ["test_case_id"])


def downgrade() -> None:
    # Preserve accepted history: fail rather than invalidate existing TEST_CASE proposals.
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM mission_proposals WHERE proposal_type = 'TEST_CASE') "
            "OR EXISTS (SELECT 1 FROM test_cases)"
        )
    ):
        raise RuntimeError(
            "cannot downgrade while test cases or TEST_CASE proposals exist; preserve canonical history"
        )
    op.drop_table("risk_test_cases")
    op.drop_table("test_cases")
    op.drop_constraint("ck_mission_proposals_type", "mission_proposals", type_="check")
    op.create_check_constraint(
        "ck_mission_proposals_type",
        "mission_proposals",
        "proposal_type IN ('REQUIREMENT', 'RISK')",
    )
