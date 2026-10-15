"""agent to canonical write loop

Revision ID: 0002_agent_canonical_loop
Revises: 0001_foundation
Create Date: 2026-10-15
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_agent_canonical_loop"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    requirement_type = sa.Enum(
        "FUNCTIONAL", "NON_FUNCTIONAL", "CONSTRAINT", "COMPATIBILITY", "PERFORMANCE",
        "RELIABILITY", "SECURITY", "OPERABILITY",
        name="ck_requirements_type", native_enum=False, create_constraint=True,
    )
    requirement_priority = sa.Enum(
        "P0", "P1", "P2", "P3",
        name="ck_requirements_priority", native_enum=False, create_constraint=True,
    )
    requirement_source_type = sa.Enum(
        "PRD", "ISSUE", "API_SPEC", "DESIGN_DOC", "GIT_DIFF", "CODE", "MANUAL",
        name="ck_requirements_source_type", native_enum=False, create_constraint=True,
    )
    requirement_lifecycle = sa.Enum(
        "ACTIVE", "SUPERSEDED", "DEPRECATED",
        name="ck_requirements_lifecycle", native_enum=False, create_constraint=True,
    )
    agent_session_status = sa.Enum(
        "CREATED", "RUNNING", "CLOSED", "FAILED",
        name="ck_agent_sessions_status", native_enum=False, create_constraint=True,
    )
    attempt_status = sa.Enum(
        "CREATED", "RUNNING", "SUBMITTED", "ACCEPTED", "REJECTED", "FAILED", "CANCELLED",
        name="ck_mission_attempts_status", native_enum=False, create_constraint=True,
    )
    proposal_type = sa.Enum(
        "REQUIREMENT",
        name="ck_mission_proposals_type", native_enum=False, create_constraint=True,
    )
    proposal_operation = sa.Enum(
        "CREATE", "UPDATE", "DEPRECATE", "LINK", "UNLINK",
        name="ck_mission_proposals_operation", native_enum=False, create_constraint=True,
    )
    proposal_status = sa.Enum(
        "SUBMITTED", "VALIDATING", "ACCEPTED", "REJECTED", "SUPERSEDED",
        name="ck_mission_proposals_status", native_enum=False, create_constraint=True,
    )

    op.create_table(
        "requirements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), sa.ForeignKey("source_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("logical_key", sa.String(255)),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("requirement_type", requirement_type, nullable=False),
        sa.Column("priority", requirement_priority, nullable=False),
        sa.Column("source_type", requirement_source_type, nullable=False),
        sa.Column("source_ref", sa.Text()),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("lifecycle_status", requirement_lifecycle, nullable=False, server_default="ACTIVE"),
        sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey("requirements.id", ondelete="RESTRICT")),
        sa.Column("created_by_type", sa.String(32), nullable=False),
        sa.Column("created_by_ref", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.UniqueConstraint("project_id", "key", name="uq_requirement_key"),
        sa.UniqueConstraint(
            "source_snapshot_id",
            "source_fingerprint",
            name="uq_requirement_source_fingerprint",
        ),
    )

    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("test_run_id", sa.Uuid(), sa.ForeignKey("test_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("harness", sa.String(64), nullable=False),
        sa.Column("provider_session_id", sa.Text()),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("status", agent_session_status, nullable=False, server_default="CREATED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("provider", "provider_session_id", name="uq_agent_provider_session"),
    )

    op.create_table(
        "mission_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("mission_id", sa.Uuid(), sa.ForeignKey("missions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("agent_session_id", sa.Uuid(), sa.ForeignKey("agent_sessions.id", ondelete="RESTRICT")),
        sa.Column("provider", sa.String(64)),
        sa.Column("harness", sa.String(64)),
        sa.Column("provider_run_ref", sa.Text()),
        sa.Column("status", attempt_status, nullable=False, server_default="CREATED"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("result_payload", sa.JSON()),
        sa.Column("provider_metadata", sa.JSON(), nullable=False),
        sa.UniqueConstraint("mission_id", "attempt_no", name="uq_mission_attempt_number"),
    )

    op.create_table(
        "mission_proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("mission_id", sa.Uuid(), sa.ForeignKey("missions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("mission_attempts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("proposal_type", proposal_type, nullable=False),
        sa.Column("operation", proposal_operation, nullable=False),
        sa.Column("idempotency_key", sa.String(512), nullable=False),
        sa.Column("object_payload", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text()),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("status", proposal_status, nullable=False, server_default="SUBMITTED"),
        sa.Column("validation_errors", sa.JSON()),
        sa.Column("accepted_entity_type", sa.String(64)),
        sa.Column("accepted_entity_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "mission_id",
            "idempotency_key",
            name="uq_mission_proposal_idempotency",
        ),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), sa.ForeignKey("test_runs.id", ondelete="RESTRICT")),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_ref", sa.Text()),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.Uuid()),
        sa.Column("before_state", sa.JSON()),
        sa.Column("after_state", sa.JSON()),
        sa.Column("event_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )

    op.create_index("ix_requirements_project_id", "requirements", ["project_id"])
    op.create_index("ix_requirements_source_snapshot_id", "requirements", ["source_snapshot_id"])
    op.create_index("ix_requirements_logical_key", "requirements", ["logical_key"])
    op.create_index("ix_agent_sessions_test_run_id", "agent_sessions", ["test_run_id"])
    op.create_index("ix_mission_attempts_mission_id", "mission_attempts", ["mission_id"])
    op.create_index("ix_mission_proposals_mission_id", "mission_proposals", ["mission_id"])
    op.create_index("ix_mission_proposals_status", "mission_proposals", ["status"])
    op.create_index("ix_audit_events_test_run_id", "audit_events", ["test_run_id"])
    op.create_index("ix_outbox_events_published_at", "outbox_events", ["published_at"])


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("audit_events")
    op.drop_table("mission_proposals")
    op.drop_table("mission_attempts")
    op.drop_table("agent_sessions")
    op.drop_table("requirements")
