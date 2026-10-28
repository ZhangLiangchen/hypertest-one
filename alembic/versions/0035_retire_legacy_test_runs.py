"""Retire old TestRun execution data without truncating shared domains."""
from alembic import op

revision = "0035_retire_legacy_test_runs"
down_revision = "0034_remove_legacy_session_tasks"
branch_labels = None
depends_on = None


def upgrade():
    # Preserve shared Project, actor/grant, Memory, Native, Archive, Cloud,
    # source inputs and connector configuration. Only audited Run-owned events
    # and requests associated with this retired execution profile are removed.
    op.execute("""
        CREATE TEMP TABLE retired_run_events ON COMMIT DROP AS
        SELECT DISTINCT entity_type, entity_id FROM audit_events
        WHERE test_run_id IN (SELECT id FROM test_runs) AND entity_id IS NOT NULL
    """)
    op.execute("""
        DELETE FROM outbox_events o
        WHERE EXISTS (SELECT 1 FROM retired_run_events r
                      WHERE r.entity_type = o.aggregate_type AND r.entity_id = o.aggregate_id)
           OR o.payload->>'test_run_id' IN (SELECT id::text FROM test_runs)
    """)
    op.execute("DELETE FROM audit_events WHERE test_run_id IN (SELECT id FROM test_runs)")
    op.execute("UPDATE worker_heartbeats SET active_job_id = NULL WHERE active_job_id IN (SELECT id FROM durable_jobs)")
    # The connector mailbox is shared with non-run operations. Disable its
    # immutability guard only inside this transaction and delete exact Run links.
    op.execute("ALTER TABLE connector_requests DISABLE TRIGGER connector_request_guard")
    op.execute("""
        DELETE FROM connector_requests
        WHERE dispatch_grant_id IN (SELECT id FROM harness_dispatch_grants)
           OR (operation IN ('issue_create','issue_query')
               AND payload->>'operation_id' IN (SELECT id::text FROM gitlab_issue_operations))
    """)
    op.execute("ALTER TABLE connector_requests ENABLE TRIGGER connector_request_guard")
    # PostgreSQL TRUNCATE RESTRICT considers references even when no referencing
    # rows remain. Remove only these three shared-table FKs, then restore them in
    # the same migration transaction; any unexpected FK blocks the truncation.
    op.execute("ALTER TABLE audit_events DROP CONSTRAINT audit_events_test_run_id_fkey")
    op.execute("ALTER TABLE worker_heartbeats DROP CONSTRAINT worker_heartbeats_active_job_id_fkey")
    op.execute("ALTER TABLE connector_requests DROP CONSTRAINT connector_requests_dispatch_grant_id_fkey")
    op.execute("""
        TRUNCATE TABLE
          agent_sessions, durable_jobs, evidence, execution_evidence,
          execution_test_cases, finding_evidence, finding_requirements, finding_risks,
          findings, finding_test_cases, gitlab_issue_operation_executors,
          gitlab_issue_operations, harness_dispatch_grants,
          interactive_execution_bindings, interactive_execution_grants,
          interactive_submission_receipts, interactive_tool_requests,
          mission_activity_events, mission_attempts, mission_input_requests,
          mission_proposals, missions, run_execution_bindings, run_execution_selections,
          run_harness_placements, run_harness_selections, run_harness_states,
          run_input_requests, run_reports, run_tool_calls, test_executions, test_runs,
          verdict_evidence, verdict_findings, verdicts
        RESTRICT
    """)
    op.execute("ALTER TABLE audit_events ADD CONSTRAINT audit_events_test_run_id_fkey FOREIGN KEY (test_run_id) REFERENCES test_runs(id) ON DELETE RESTRICT")
    op.execute("ALTER TABLE worker_heartbeats ADD CONSTRAINT worker_heartbeats_active_job_id_fkey FOREIGN KEY (active_job_id) REFERENCES durable_jobs(id) ON DELETE RESTRICT")
    op.execute("ALTER TABLE connector_requests ADD CONSTRAINT connector_requests_dispatch_grant_id_fkey FOREIGN KEY (dispatch_grant_id) REFERENCES harness_dispatch_grants(id) ON DELETE RESTRICT")


def downgrade():
    raise RuntimeError("Removed TestRun data cannot be reconstructed")
