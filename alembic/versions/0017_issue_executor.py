"""ADR-015 immutable Issue executor selection; no historical backfill."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0017_issue_executor"
down_revision = "0016_source_transfer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A creation authority can be consumed only once even if the local journal
    # has been lost between connections. UNKNOWN/expired rows retain this claim.
    op.execute(sa.text("CREATE UNIQUE INDEX uq_issue_create_delivery ON connector_requests ((payload->>'operation_id')) WHERE operation='issue_create'"))
    op.create_table("gitlab_issue_operation_executors",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("operation_id", sa.UUID(), sa.ForeignKey("gitlab_issue_operations.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("executor_mode", sa.String(32), nullable=False),
        sa.Column("executor_node_id", sa.UUID(), sa.ForeignKey("harness_nodes.id", ondelete="RESTRICT")),
        sa.Column("capability_id", sa.UUID(), sa.ForeignKey("node_project_capabilities.id", ondelete="RESTRICT")),
        sa.Column("device_grant_id", sa.UUID(), sa.ForeignKey("harness_device_grants.id", ondelete="RESTRICT")),
        sa.Column("integration_id", sa.String(128), nullable=False),
        sa.Column("delegation_sha256", sa.String(64), nullable=False),
        sa.Column("delegation", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("executor_mode IN ('SERVER_HOST','LOCAL_CONNECTOR')", name="ck_issue_executor_mode"),
        sa.CheckConstraint("(executor_mode='LOCAL_CONNECTOR') = (executor_node_id IS NOT NULL AND capability_id IS NOT NULL AND device_grant_id IS NOT NULL)", name="ck_issue_executor_node"))
    op.execute(sa.text("""
CREATE FUNCTION hypertest_guard_issue_executor() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE issue gitlab_issue_operations%ROWTYPE; run_project uuid;
BEGIN
    IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Issue executor history is append-only'; END IF;
    SELECT * INTO issue FROM gitlab_issue_operations WHERE id=NEW.operation_id;
    IF NOT FOUND OR issue.status<>'PENDING' THEN RAISE EXCEPTION 'executor requires pending operation'; END IF;
    SELECT project_id INTO run_project FROM test_runs WHERE id=issue.test_run_id;
    IF NEW.executor_mode='LOCAL_CONNECTOR' AND (
        NOT EXISTS (SELECT 1 FROM harness_nodes WHERE id=NEW.executor_node_id AND node_kind='LOCAL_CONNECTOR' AND registration_status='ACTIVE') OR
        NOT EXISTS (SELECT 1 FROM node_project_capabilities WHERE id=NEW.capability_id AND node_id=NEW.executor_node_id AND project_id=run_project AND capability='issue_executor' AND status='ACTIVE') OR
        NOT EXISTS (SELECT 1 FROM harness_device_grants WHERE id=NEW.device_grant_id AND node_id=NEW.executor_node_id AND status='ACTIVE' AND not_before<=clock_timestamp() AND expires_at>clock_timestamp())) THEN
        RAISE EXCEPTION 'Issue executor requires current project capability and device grant';
    END IF;
    IF NEW.executor_mode='SERVER_HOST' AND num_nonnulls(NEW.executor_node_id,NEW.capability_id,NEW.device_grant_id)<>0 THEN
        RAISE EXCEPTION 'server Issue executor cannot select local authorization';
    END IF;
    IF length(btrim(NEW.integration_id))=0 OR NEW.delegation_sha256 !~ '^[a-f0-9]{64}$' OR jsonb_typeof(NEW.delegation)<>'object'
       OR NEW.delegation->>'operation_id' IS DISTINCT FROM issue.id::text
       OR NEW.delegation->>'input_sha256' IS DISTINCT FROM issue.input_sha256
       OR NEW.delegation->>'test_run_id' IS DISTINCT FROM issue.test_run_id::text
       OR NEW.delegation->>'binding_id' IS DISTINCT FROM issue.binding_id::text
       OR NEW.delegation->>'durable_job_id' IS DISTINCT FROM issue.durable_job_id::text
       OR NEW.delegation->>'finding_id' IS DISTINCT FROM issue.finding_id::text
       OR NEW.delegation->>'project_id' IS DISTINCT FROM run_project::text
       OR NEW.delegation->>'integration_id' IS DISTINCT FROM NEW.integration_id
       OR NEW.delegation->>'node_id' IS DISTINCT FROM COALESCE(NEW.executor_node_id::text,'SERVER_HOST')
       OR NEW.delegation->'draft' IS DISTINCT FROM issue.draft
       OR NEW.delegation->>'base_url' IS DISTINCT FROM issue.authorization->>'base_url'
       OR NEW.delegation->'gitlab_project_id' IS DISTINCT FROM issue.authorization->'project_id'
       OR NEW.delegation->'assignee_id' IS DISTINCT FROM issue.authorization->'assignee_id'
       OR NEW.delegation->>'correlation' IS DISTINCT FROM ('HTISSUE-'||replace(issue.id::text,'-','')) THEN
        RAISE EXCEPTION 'Issue executor requires fixed operation input';
    END IF;
    RETURN NEW;
END; $$
"""))
    op.execute(sa.text("CREATE TRIGGER issue_executor_guard BEFORE INSERT OR UPDATE OR DELETE ON gitlab_issue_operation_executors FOR EACH ROW EXECUTE FUNCTION hypertest_guard_issue_executor()"))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM gitlab_issue_operation_executors)")):
        raise RuntimeError("retained Issue executor history prevents destructive downgrade")
    op.drop_table("gitlab_issue_operation_executors")
    op.execute(sa.text("DROP FUNCTION hypertest_guard_issue_executor()"))
    op.drop_index("uq_issue_create_delivery", table_name="connector_requests")
