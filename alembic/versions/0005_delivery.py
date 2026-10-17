"""Complete the canonical delivery, evidence, finding, and verdict chain.

Revision ID: 0005_delivery
Revises: 0004_test_design
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_delivery"
down_revision = "0004_test_design"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 inferred VARCHAR(11) from its initial enum; implementation proposals need more room.
    op.alter_column(
        "mission_proposals",
        "proposal_type",
        existing_type=sa.String(11),
        type_=sa.String(64),
        existing_nullable=False,
    )
    op.drop_constraint("ck_mission_proposals_type", "mission_proposals", type_="check")
    op.create_check_constraint(
        "ck_mission_proposals_type",
        "mission_proposals",
        "proposal_type IN ('REQUIREMENT', 'RISK', 'TEST_CASE', 'TEST_IMPLEMENTATION', 'FINDING')",
    )
    op.create_table(
        "test_implementations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("repository_url", sa.Text(), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("framework", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=64), nullable=False),
        sa.Column("implementation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("artifact_uri", sa.Text(), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "validation_status",
            sa.Enum(
                "PENDING",
                "VALIDATED",
                "REJECTED",
                "STALE",
                name="ck_test_implementations_validation",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("created_by_type", sa.String(length=32), nullable=False),
        sa.Column("created_by_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "validation_status IN ('PENDING', 'VALIDATED', 'REJECTED', 'STALE')",
            name="ck_test_implementations_validation",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"], ["source_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "key", name="uq_test_implementation_key"),
        sa.UniqueConstraint(
            "source_snapshot_id",
            "implementation_fingerprint",
            name="uq_test_implementation_fingerprint",
        ),
    )
    op.create_index(
        op.f("ix_test_implementations_project_id"),
        "test_implementations",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_test_implementations_source_snapshot_id"),
        "test_implementations",
        ["source_snapshot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_test_implementations_validation_status"),
        "test_implementations",
        ["validation_status"],
        unique=False,
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "classification",
            sa.Enum(
                "PRODUCT_DEFECT",
                "TEST_DEFECT",
                "ENVIRONMENT_FAILURE",
                "INFRA_FAILURE",
                "FLAKY",
                "DATA_ISSUE",
                "EXPECTED_BEHAVIOR",
                "REQUIREMENT_ISSUE",
                "UNKNOWN",
                name="ck_findings_classification",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum(
                "BLOCKER",
                "CRITICAL",
                "MAJOR",
                "MINOR",
                "INFO",
                name="ck_findings_severity",
                native_enum=False,
                create_constraint=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "NEW",
                "TRIAGED",
                "INVALID",
                "CONFIRMED",
                "RESOLVED",
                "CLOSED",
                "REOPENED",
                name="ck_findings_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "resolution",
            sa.Enum(
                "FIXED",
                "DUPLICATE",
                "WONT_FIX",
                "RISK_ACCEPTED",
                "NOT_REPRODUCIBLE",
                "ENVIRONMENT_FIXED",
                "TEST_FIXED",
                name="ck_findings_resolution",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("external_issue_ref", sa.Text(), nullable=True),
        sa.Column("reported_by_type", sa.String(length=32), nullable=False),
        sa.Column("reported_by_ref", sa.Text(), nullable=True),
        sa.Column("confirmed_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "classification IN ('PRODUCT_DEFECT', 'TEST_DEFECT', 'ENVIRONMENT_FAILURE', 'INFRA_FAILURE', 'FLAKY', 'DATA_ISSUE', 'EXPECTED_BEHAVIOR', 'REQUIREMENT_ISSUE', 'UNKNOWN')",
            name="ck_findings_classification",
        ),
        sa.CheckConstraint(
            "resolution IN ('FIXED', 'DUPLICATE', 'WONT_FIX', 'RISK_ACCEPTED', 'NOT_REPRODUCIBLE', 'ENVIRONMENT_FIXED', 'TEST_FIXED')",
            name="ck_findings_resolution",
        ),
        sa.CheckConstraint(
            "severity IN ('BLOCKER', 'CRITICAL', 'MAJOR', 'MINOR', 'INFO')",
            name="ck_findings_severity",
        ),
        sa.CheckConstraint(
            "status IN ('NEW', 'TRIAGED', 'INVALID', 'CONFIRMED', 'RESOLVED', 'CLOSED', 'REOPENED')",
            name="ck_findings_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="ck_finding_confidence"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "key", name="uq_finding_key"),
    )
    op.create_index(
        op.f("ix_findings_classification"), "findings", ["classification"], unique=False
    )
    op.create_index(op.f("ix_findings_project_id"), "findings", ["project_id"], unique=False)
    op.create_index(op.f("ix_findings_severity"), "findings", ["severity"], unique=False)
    op.create_index(op.f("ix_findings_status"), "findings", ["status"], unique=False)
    op.create_index(op.f("ix_findings_test_run_id"), "findings", ["test_run_id"], unique=False)
    op.create_index(
        "uq_finding_active_fingerprint",
        "findings",
        ["project_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("status IN ('NEW', 'TRIAGED', 'CONFIRMED', 'REOPENED')"),
    )
    op.create_table(
        "implementation_test_cases",
        sa.Column("implementation_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["implementation_id"], ["test_implementations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("implementation_id", "test_case_id"),
    )
    op.create_index(
        op.f("ix_implementation_test_cases_test_case_id"),
        "implementation_test_cases",
        ["test_case_id"],
        unique=False,
    )
    op.create_table(
        "verdicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope",
            sa.Enum(
                "TEST_RUN",
                "REQUIREMENT",
                "RISK",
                "RELEASE",
                name="ck_verdicts_scope",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("scope_ref", sa.Text(), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(
                "PASS",
                "FAIL",
                "BLOCKED",
                "INCONCLUSIVE",
                "RETEST_REQUIRED",
                "RISK_ACCEPTED",
                "RELEASE_READY",
                "RELEASE_BLOCKED",
                name="ck_verdicts_decision",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "FINAL",
                "REVOKED",
                name="ck_verdicts_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("state_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("evidence_manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("issued_by_type", sa.String(length=32), nullable=False),
        sa.Column("issued_by_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "decision IN ('PASS', 'FAIL', 'BLOCKED', 'INCONCLUSIVE', 'RETEST_REQUIRED', 'RISK_ACCEPTED', 'RELEASE_READY', 'RELEASE_BLOCKED')",
            name="ck_verdicts_decision",
        ),
        sa.CheckConstraint(
            "scope IN ('TEST_RUN', 'REQUIREMENT', 'RISK', 'RELEASE')", name="ck_verdicts_scope"
        ),
        sa.CheckConstraint(
            "status != 'FINAL' OR (state_snapshot_hash IS NOT NULL AND evidence_manifest_sha256 IS NOT NULL AND finalized_at IS NOT NULL)",
            name="ck_verdict_finalized",
        ),
        sa.CheckConstraint("status IN ('DRAFT', 'FINAL', 'REVOKED')", name="ck_verdicts_status"),
        sa.CheckConstraint("sequence_no > 0", name="ck_verdict_sequence"),
        sa.ForeignKeyConstraint(
            ["policy_snapshot_id"], ["policy_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_run_id", "key", name="uq_verdict_key"),
        sa.UniqueConstraint("test_run_id", "sequence_no", name="uq_verdict_sequence"),
    )
    op.create_index(
        op.f("ix_verdicts_policy_snapshot_id"), "verdicts", ["policy_snapshot_id"], unique=False
    )
    op.create_index(op.f("ix_verdicts_status"), "verdicts", ["status"], unique=False)
    op.create_index(op.f("ix_verdicts_test_run_id"), "verdicts", ["test_run_id"], unique=False)
    op.create_table(
        "finding_requirements",
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requirement_id"], ["requirements.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("finding_id", "requirement_id"),
    )
    op.create_index(
        op.f("ix_finding_requirements_requirement_id"),
        "finding_requirements",
        ["requirement_id"],
        unique=False,
    )
    op.create_table(
        "finding_risks",
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("risk_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["risk_id"], ["risks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("finding_id", "risk_id"),
    )
    op.create_index(op.f("ix_finding_risks_risk_id"), "finding_risks", ["risk_id"], unique=False)
    op.create_table(
        "finding_test_cases",
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("finding_id", "test_case_id"),
    )
    op.create_index(
        op.f("ix_finding_test_cases_test_case_id"),
        "finding_test_cases",
        ["test_case_id"],
        unique=False,
    )
    op.create_table(
        "test_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), nullable=False),
        sa.Column("mission_id", sa.Uuid(), nullable=True),
        sa.Column("execution_request_id", sa.Uuid(), nullable=True),
        sa.Column("retry_of_execution_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                "EXPLORATORY",
                "VALIDATION",
                "OFFICIAL",
                "REPRODUCTION",
                name="ck_test_executions_purpose",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("runner_backend", sa.String(length=64), nullable=False),
        sa.Column("environment_id", sa.String(length=255), nullable=False),
        sa.Column("environment_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_commit", sa.String(length=64), nullable=False),
        sa.Column("execution_spec_sha256", sa.String(length=64), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "PROVISIONING",
                "RUNNING",
                "COLLECTING",
                "COMPLETED",
                "ERROR",
                "TIMED_OUT",
                "CANCELLED",
                name="ck_test_executions_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.Enum(
                "PASS",
                "FAIL",
                "BLOCKED",
                "INCONCLUSIVE",
                "UNKNOWN",
                name="ck_test_executions_outcome",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("runner_instance", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('PASS', 'FAIL', 'BLOCKED', 'INCONCLUSIVE', 'UNKNOWN')",
            name="ck_test_executions_outcome",
        ),
        sa.CheckConstraint(
            "purpose IN ('EXPLORATORY', 'VALIDATION', 'OFFICIAL', 'REPRODUCTION')",
            name="ck_test_executions_purpose",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'PROVISIONING', 'RUNNING', 'COLLECTING', 'COMPLETED', 'ERROR', 'TIMED_OUT', 'CANCELLED')",
            name="ck_test_executions_status",
        ),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["retry_of_execution_id"], ["test_executions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_run_id", "idempotency_key", name="uq_test_execution_idempotency"),
        sa.UniqueConstraint("test_run_id", "key", name="uq_test_execution_key"),
    )
    op.create_index(
        op.f("ix_test_executions_mission_id"), "test_executions", ["mission_id"], unique=False
    )
    op.create_index(
        op.f("ix_test_executions_outcome"), "test_executions", ["outcome"], unique=False
    )
    op.create_index(op.f("ix_test_executions_status"), "test_executions", ["status"], unique=False)
    op.create_index(
        op.f("ix_test_executions_test_run_id"), "test_executions", ["test_run_id"], unique=False
    )
    op.create_table(
        "verdict_findings",
        sa.Column("verdict_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["verdict_id"], ["verdicts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("verdict_id", "finding_id"),
    )
    op.create_index(
        op.f("ix_verdict_findings_finding_id"), "verdict_findings", ["finding_id"], unique=False
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.Column(
            "evidence_type",
            sa.Enum(
                "EXECUTION_METADATA",
                "STDOUT",
                "STDERR",
                "JUNIT",
                "HTTP_REQUEST",
                "HTTP_RESPONSE",
                "LOG",
                "METRIC",
                "TRACE",
                "SCREENSHOT",
                "DATABASE_STATE",
                "FILE_ARTIFACT",
                "GIT_DIFF",
                "ENVIRONMENT_FINGERPRINT",
                "CUSTOM",
                name="ck_evidence_type",
                native_enum=False,
                create_constraint=False,
                length=64,
            ),
            nullable=False,
        ),
        sa.Column(
            "trust_level",
            sa.Enum(
                "RUNNER",
                "SYSTEM",
                "EXTERNAL_VERIFIED",
                "AGENT_REPORTED",
                "USER_PROVIDED",
                name="ck_evidence_trust",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("artifact_uri", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("inline_summary", sa.Text(), nullable=True),
        sa.Column("collector", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "COLLECTED",
                "VERIFIED",
                "REJECTED",
                "SUPERSEDED",
                name="ck_evidence_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "evidence_type IN ('EXECUTION_METADATA', 'STDOUT', 'STDERR', 'JUNIT', 'HTTP_REQUEST', 'HTTP_RESPONSE', 'LOG', 'METRIC', 'TRACE', 'SCREENSHOT', 'DATABASE_STATE', 'FILE_ARTIFACT', 'GIT_DIFF', 'ENVIRONMENT_FINGERPRINT', 'CUSTOM')",
            name="ck_evidence_type",
        ),
        sa.CheckConstraint(
            "status IN ('COLLECTED', 'VERIFIED', 'REJECTED', 'SUPERSEDED')",
            name="ck_evidence_status",
        ),
        sa.CheckConstraint(
            "trust_level IN ('RUNNER', 'SYSTEM', 'EXTERNAL_VERIFIED', 'AGENT_REPORTED', 'USER_PROVIDED')",
            name="ck_evidence_trust",
        ),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_evidence_size"),
        sa.ForeignKeyConstraint(["execution_id"], ["test_executions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_run_id", "key", name="uq_evidence_key"),
        sa.UniqueConstraint("test_run_id", "sha256", "evidence_type", name="uq_evidence_content"),
    )
    op.create_index(op.f("ix_evidence_evidence_type"), "evidence", ["evidence_type"], unique=False)
    op.create_index(op.f("ix_evidence_execution_id"), "evidence", ["execution_id"], unique=False)
    op.create_index(op.f("ix_evidence_status"), "evidence", ["status"], unique=False)
    op.create_index(op.f("ix_evidence_test_run_id"), "evidence", ["test_run_id"], unique=False)
    op.create_table(
        "execution_test_cases",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("implementation_id", sa.Uuid(), nullable=True),
        sa.Column(
            "result",
            sa.Enum(
                "PASS",
                "FAIL",
                "SKIPPED",
                "BLOCKED",
                "ERROR",
                "NOT_RUN",
                name="ck_execution_test_cases_result",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "result IN ('PASS', 'FAIL', 'SKIPPED', 'BLOCKED', 'ERROR', 'NOT_RUN')",
            name="ck_execution_test_cases_result",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_execution_case_duration"
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["test_executions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["implementation_id"], ["test_implementations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("execution_id", "test_case_id"),
    )
    op.create_index(
        op.f("ix_execution_test_cases_implementation_id"),
        "execution_test_cases",
        ["implementation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_execution_test_cases_test_case_id"),
        "execution_test_cases",
        ["test_case_id"],
        unique=False,
    )
    op.create_table(
        "execution_evidence",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_id"], ["test_executions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("execution_id", "evidence_id"),
    )
    op.create_index(
        op.f("ix_execution_evidence_evidence_id"),
        "execution_evidence",
        ["evidence_id"],
        unique=False,
    )
    op.create_table(
        "finding_evidence",
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column(
            "relation_type",
            sa.Enum(
                "SUPPORTS",
                "CONTRADICTS",
                "CONTEXT",
                name="ck_finding_evidence_relation",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "relation_type IN ('SUPPORTS', 'CONTRADICTS', 'CONTEXT')",
            name="ck_finding_evidence_relation",
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("finding_id", "evidence_id"),
    )
    op.create_index(
        op.f("ix_finding_evidence_evidence_id"), "finding_evidence", ["evidence_id"], unique=False
    )
    op.create_table(
        "verdict_evidence",
        sa.Column("verdict_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["verdict_id"], ["verdicts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("verdict_id", "evidence_id"),
    )
    op.create_index(
        op.f("ix_verdict_evidence_evidence_id"), "verdict_evidence", ["evidence_id"], unique=False
    )
    op.add_column("test_runs", sa.Column("current_verdict_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_test_run_current_verdict",
        "test_runs",
        "verdicts",
        ["current_verdict_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # Execution inputs identify a reproducible run and never change after creation.
    op.execute(
        sa.text("""
CREATE FUNCTION hypertest_guard_execution_inputs() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['status', 'outcome', 'started_at', 'finished_at',
            'exit_code', 'error_code', 'error_message', 'runner_instance', 'row_version'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['status', 'outcome', 'started_at', 'finished_at',
            'exit_code', 'error_code', 'error_message', 'runner_instance', 'row_version']) THEN
        RAISE EXCEPTION 'execution input is immutable; create a new execution';
    END IF;
    RETURN NEW;
END;
$$;""")
    )
    op.execute(
        sa.text("""
CREATE TRIGGER execution_inputs_immutable BEFORE UPDATE ON test_executions
    FOR EACH ROW EXECUTE FUNCTION hypertest_guard_execution_inputs();
""")
    )
    op.execute(
        sa.text("""
CREATE FUNCTION hypertest_guard_evidence_content() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['status', 'verified_at', 'rejection_reason'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['status', 'verified_at', 'rejection_reason']) THEN
        RAISE EXCEPTION 'evidence content is immutable';
    END IF;
    RETURN NEW;
END;
$$;""")
    )
    op.execute(
        sa.text("""
CREATE TRIGGER evidence_content_immutable BEFORE UPDATE ON evidence
    FOR EACH ROW EXECUTE FUNCTION hypertest_guard_evidence_content();
""")
    )
    op.execute(
        sa.text("""
CREATE FUNCTION hypertest_guard_final_verdict() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status IN ('FINAL', 'REVOKED') THEN
            RAISE EXCEPTION 'final verdict is append-only; preserve decision history';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status IN ('FINAL', 'REVOKED') THEN
        IF (to_jsonb(NEW) - ARRAY['status', 'revoked_at'])
           IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'revoked_at'])
           OR NOT (OLD.status = 'FINAL' AND NEW.status = 'REVOKED' AND NEW.revoked_at IS NOT NULL) THEN
            RAISE EXCEPTION 'final verdict is append-only; issue a new verdict';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;""")
    )
    op.execute(
        sa.text("""
CREATE TRIGGER final_verdict_append_only BEFORE UPDATE OR DELETE ON verdicts
    FOR EACH ROW EXECUTE FUNCTION hypertest_guard_final_verdict();
""")
    )


def downgrade() -> None:
    connection = op.get_bind()
    protected_tables = (
        "test_implementations",
        "test_executions",
        "evidence",
        "findings",
        "verdicts",
    )
    for table in protected_tables:
        if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("cannot downgrade canonical delivery history")
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM mission_proposals "
            "WHERE proposal_type IN ('TEST_IMPLEMENTATION', 'FINDING'))"
        )
    ):
        raise RuntimeError("cannot downgrade canonical delivery proposals")
    op.execute(sa.text("DROP TRIGGER final_verdict_append_only ON verdicts"))
    op.execute(sa.text("DROP FUNCTION hypertest_guard_final_verdict()"))
    op.execute(sa.text("DROP TRIGGER evidence_content_immutable ON evidence"))
    op.execute(sa.text("DROP FUNCTION hypertest_guard_evidence_content()"))
    op.execute(sa.text("DROP TRIGGER execution_inputs_immutable ON test_executions"))
    op.execute(sa.text("DROP FUNCTION hypertest_guard_execution_inputs()"))
    op.drop_constraint("fk_test_run_current_verdict", "test_runs", type_="foreignkey")
    op.drop_column("test_runs", "current_verdict_id")
    op.drop_table("verdict_evidence")
    op.drop_table("finding_evidence")
    op.drop_table("execution_evidence")
    op.drop_table("execution_test_cases")
    op.drop_table("evidence")
    op.drop_table("verdict_findings")
    op.drop_table("test_executions")
    op.drop_table("finding_test_cases")
    op.drop_table("finding_risks")
    op.drop_table("finding_requirements")
    op.drop_table("verdicts")
    op.drop_table("implementation_test_cases")
    op.drop_table("findings")
    op.drop_table("test_implementations")
    op.drop_constraint("ck_mission_proposals_type", "mission_proposals", type_="check")
    op.create_check_constraint(
        "ck_mission_proposals_type",
        "mission_proposals",
        "proposal_type IN ('REQUIREMENT', 'RISK', 'TEST_CASE')",
    )
    op.alter_column(
        "mission_proposals",
        "proposal_type",
        existing_type=sa.String(64),
        type_=sa.String(11),
        existing_nullable=False,
    )
