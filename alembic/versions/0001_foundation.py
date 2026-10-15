"""foundation control-plane schema

Revision ID: 0001_foundation
Revises:
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    project_status = sa.Enum(
        "ACTIVE", "ARCHIVED", name="ck_projects_status", native_enum=False, create_constraint=True
    )
    test_run_status = sa.Enum(
        "CREATED", "ANALYZING", "DESIGNING", "IMPLEMENTING", "EXECUTING",
        "DIAGNOSING", "VERIFYING", "BLOCKED", "COMPLETED", "CANCELLED",
        name="ck_test_runs_status", native_enum=False, create_constraint=True,
    )
    mission_type = sa.Enum(
        "ANALYZE_REQUIREMENTS", "ANALYZE_IMPACT", "ANALYZE_RISKS", "DESIGN_TESTS",
        "REVIEW_TESTS", "IMPLEMENT_TESTS", "REVIEW_IMPLEMENTATION", "DIAGNOSE_FAILURE",
        "INVESTIGATE_FINDING", "REPAIR_TEST", "RETEST_ANALYSIS", "VERIFY_COVERAGE",
        name="ck_missions_type", native_enum=False, create_constraint=True,
    )
    priority = sa.Enum(
        "P0", "P1", "P2", "P3", name="ck_missions_priority", native_enum=False,
        create_constraint=True,
    )
    mission_status = sa.Enum(
        "CREATED", "READY", "DISPATCHED", "RUNNING", "WAITING_INPUT",
        "WAITING_EXECUTION", "SUBMITTED", "VERIFYING", "RETRYING", "COMPLETED",
        "FAILED", "CANCELLED", "EXPIRED",
        name="ck_missions_status", native_enum=False, create_constraint=True,
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("repository_url", sa.Text()),
        sa.Column("default_branch", sa.String(255), nullable=False, server_default="main"),
        sa.Column("status", project_status, nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
    )

    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("repository_url", sa.Text(), nullable=False),
        sa.Column("commit_sha", sa.String(64), nullable=False),
        sa.Column("branch", sa.String(255)),
        sa.Column("prd_sha256", sa.String(64), nullable=False),
        sa.Column("prd_artifact_uri", sa.Text()),
        sa.Column("configuration_sha256", sa.String(64), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "source_fingerprint", name="uq_source_snapshot_fingerprint"),
    )

    op.create_table(
        "policy_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("policy_name", sa.String(255), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_uri", sa.Text()),
        sa.Column("compiled_policy", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "content_sha256", name="uq_policy_snapshot_content"),
    )

    op.create_table(
        "test_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), sa.ForeignKey("source_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("policy_snapshot_id", sa.Uuid(), sa.ForeignKey("policy_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("trigger_type", sa.String(64), nullable=False),
        sa.Column("trigger_ref", sa.Text()),
        sa.Column("status", test_run_status, nullable=False, server_default="CREATED"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.UniqueConstraint("project_id", "key", name="uq_test_run_key"),
    )

    op.create_table(
        "missions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), sa.ForeignKey("test_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mission_type", mission_type, nullable=False),
        sa.Column("priority", priority, nullable=False, server_default="P1"),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("protocol_version", sa.String(32), nullable=False, server_default="v1alpha1"),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("spec_sha256", sa.String(64), nullable=False),
        sa.Column("status", mission_status, nullable=False, server_default="CREATED"),
        sa.Column("idempotency_key", sa.String(512), nullable=False),
        sa.Column("current_attempt_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.UniqueConstraint("test_run_id", "key", name="uq_mission_key"),
        sa.UniqueConstraint("test_run_id", "idempotency_key", name="uq_mission_idempotency"),
    )

    op.create_index("ix_source_snapshots_project_id", "source_snapshots", ["project_id"])
    op.create_index("ix_test_runs_project_id", "test_runs", ["project_id"])
    op.create_index("ix_test_runs_status", "test_runs", ["status"])
    op.create_index("ix_missions_test_run_id", "missions", ["test_run_id"])
    op.create_index("ix_missions_status", "missions", ["status"])


def downgrade() -> None:
    op.drop_table("missions")
    op.drop_table("test_runs")
    op.drop_table("policy_snapshots")
    op.drop_table("source_snapshots")
    op.drop_table("projects")
