"""risk canonical state and planner support

Revision ID: 0003_risk_planner
Revises: 0002_agent_canonical_loop
Create Date: 2026-10-15
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_risk_planner"
down_revision = "0002_agent_canonical_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    risk_category = sa.Enum(
        "FUNCTIONAL", "BOUNDARY", "FAILURE", "CONCURRENCY", "CONSISTENCY",
        "COMPATIBILITY", "SECURITY", "PERFORMANCE", "RELIABILITY", "OBSERVABILITY",
        "UPGRADE", "DATA",
        name="ck_risks_category", native_enum=False, create_constraint=True,
    )
    risk_severity = sa.Enum(
        "CRITICAL", "HIGH", "MEDIUM", "LOW",
        name="ck_risks_severity", native_enum=False, create_constraint=True,
    )
    risk_probability = sa.Enum(
        "HIGH", "MEDIUM", "LOW", "UNKNOWN",
        name="ck_risks_probability", native_enum=False, create_constraint=True,
    )
    risk_lifecycle = sa.Enum(
        "OPEN", "ACCEPTED", "MITIGATED", "OBSOLETE",
        name="ck_risks_lifecycle", native_enum=False, create_constraint=True,
    )

    op.drop_constraint("ck_mission_proposals_type", "mission_proposals", type_="check")
    op.create_check_constraint(
        "ck_mission_proposals_type",
        "mission_proposals",
        "proposal_type IN ('REQUIREMENT', 'RISK')",
    )

    op.create_table(
        "risks",
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
        sa.Column("risk_fingerprint", sa.String(64), nullable=False),
        sa.Column("category", risk_category, nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", risk_severity, nullable=False),
        sa.Column("probability", risk_probability, nullable=False),
        sa.Column("rationale", sa.Text()),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("lifecycle_status", risk_lifecycle, nullable=False, server_default="OPEN"),
        sa.Column("disposition", sa.Text()),
        sa.Column("created_by_type", sa.String(32), nullable=False),
        sa.Column("created_by_ref", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.UniqueConstraint("project_id", "key", name="uq_risk_key"),
        sa.UniqueConstraint(
            "source_snapshot_id",
            "risk_fingerprint",
            name="uq_risk_source_fingerprint",
        ),
    )

    op.create_table(
        "requirement_risks",
        sa.Column(
            "requirement_id",
            sa.Uuid(),
            sa.ForeignKey("requirements.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "risk_id",
            sa.Uuid(),
            sa.ForeignKey("risks.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("relation_type", sa.String(32), nullable=False, server_default="ADDRESSES"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_risks_project_id", "risks", ["project_id"])
    op.create_index("ix_risks_source_snapshot_id", "risks", ["source_snapshot_id"])
    op.create_index("ix_risks_category", "risks", ["category"])
    op.create_index("ix_risks_severity", "risks", ["severity"])
    op.create_index("ix_requirement_risks_risk_id", "requirement_risks", ["risk_id"])


def downgrade() -> None:
    op.drop_index("ix_requirement_risks_risk_id", table_name="requirement_risks")
    op.drop_table("requirement_risks")
    op.drop_index("ix_risks_severity", table_name="risks")
    op.drop_index("ix_risks_category", table_name="risks")
    op.drop_index("ix_risks_source_snapshot_id", table_name="risks")
    op.drop_index("ix_risks_project_id", table_name="risks")
    op.drop_table("risks")
    op.drop_constraint("ck_mission_proposals_type", "mission_proposals", type_="check")
    op.create_check_constraint(
        "ck_mission_proposals_type",
        "mission_proposals",
        "proposal_type IN ('REQUIREMENT')",
    )
