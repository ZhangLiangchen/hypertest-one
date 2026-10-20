"""Durable typed interactive transport inbox; execution stays in the original Worker."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0020_interactive_tool_inbox"
down_revision = "0019_interactive_mcp"
branch_labels = None
depends_on = None


def upgrade():
    # Existing grant history remains unchanged. Legacy NULL device identity is
    # rejected by the new execution validators; new grants require exact scope.
    op.add_column("interactive_execution_grants", sa.Column("device_grant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_interactive_execution_exact_device", "interactive_execution_grants",
        "harness_device_grants", ["device_grant_id"], ["id"], ondelete="RESTRICT")
    op.execute(sa.text(EXACT_DEVICE_GUARD))
    op.execute(sa.text("CREATE TRIGGER interactive_exact_device_guard BEFORE INSERT ON interactive_execution_grants FOR EACH ROW EXECUTE FUNCTION hypertest_guard_interactive_exact_device()"))
    op.create_table("interactive_tool_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("interactive_binding_id", sa.Uuid(), sa.ForeignKey("interactive_execution_bindings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("execution_grant_id", sa.Uuid(), sa.ForeignKey("interactive_execution_grants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("integration_grant_id", sa.Uuid(), sa.ForeignKey("interactive_integration_grants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_identity_id", sa.Uuid(), sa.ForeignKey("interactive_actor_identities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_instance_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("durable_jobs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("binding_epoch", sa.BigInteger(), nullable=False),
        sa.Column("claim_identity", sa.String(64), nullable=False),
        sa.Column("tool_call_id", sa.String(255), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("arguments", JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", JSONB(none_as_null=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("interactive_binding_id", "idempotency_key", name="uq_interactive_tool_key"),
        sa.UniqueConstraint("interactive_binding_id", "tool_call_id", name="uq_interactive_tool_call"),
        sa.CheckConstraint("tool_name IN ('get_state','request_mission','complete_mission','request_execution','ask_user','evaluate_gate','submit_report','request_gitlab_issue','get_issue')", name="ck_interactive_tool_name"),
        sa.CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','REJECTED','UNKNOWN')", name="ck_interactive_tool_status"),
        sa.CheckConstraint("binding_epoch>0 AND input_digest ~ '^[a-f0-9]{64}$' AND claim_identity ~ '^[a-f0-9]{64}$' AND length(btrim(idempotency_key)) BETWEEN 1 AND 255 AND length(btrim(tool_call_id)) BETWEEN 1 AND 255", name="ck_interactive_tool_identity"),
        sa.CheckConstraint("jsonb_typeof(arguments)='object' AND octet_length(arguments::text)<=4000000 AND (result IS NULL OR (jsonb_typeof(result)='object' AND octet_length(result::text)<=4000000))", name="ck_interactive_tool_json"))
    op.create_index("ix_interactive_tool_job_queue", "interactive_tool_requests", ["job_id", "status", "created_at"])
    op.execute(sa.text(GUARD))
    op.execute(sa.text("CREATE TRIGGER interactive_tool_history_guard BEFORE INSERT OR UPDATE OR DELETE ON interactive_tool_requests FOR EACH ROW EXECUTE FUNCTION hypertest_guard_interactive_tool_request()"))


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM interactive_tool_requests) OR EXISTS (SELECT 1 FROM interactive_execution_grants WHERE device_grant_id IS NOT NULL)")):
        raise RuntimeError("retained interactive tool delivery history prevents destructive downgrade")
    op.drop_table("interactive_tool_requests")
    op.execute("DROP FUNCTION hypertest_guard_interactive_tool_request()")
    op.execute("DROP TRIGGER interactive_exact_device_guard ON interactive_execution_grants")
    op.execute("DROP FUNCTION hypertest_guard_interactive_exact_device()")
    op.drop_constraint("fk_interactive_execution_exact_device", "interactive_execution_grants", type_="foreignkey")
    op.drop_column("interactive_execution_grants", "device_grant_id")


EXACT_DEVICE_GUARD = r"""
CREATE FUNCTION hypertest_guard_interactive_exact_device() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE attached_node uuid; device harness_device_grants%ROWTYPE;
BEGIN
 SELECT node_id INTO attached_node FROM interactive_execution_bindings WHERE id=NEW.interactive_binding_id;
 SELECT * INTO device FROM harness_device_grants WHERE id=NEW.device_grant_id;
 IF device.id IS NULL OR attached_node IS NULL OR device.node_id<>attached_node
    OR device.status<>'ACTIVE' OR device.not_before>clock_timestamp() OR device.expires_at<=clock_timestamp()
    OR NEW.expires_at>device.expires_at THEN
  RAISE EXCEPTION 'interactive execution requires its exact current device grant'; END IF;
 RETURN NEW;
END; $$;
"""


GUARD = r"""
CREATE FUNCTION hypertest_guard_interactive_tool_request() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE attachment interactive_execution_bindings%ROWTYPE; short interactive_execution_grants%ROWTYPE;
 integration interactive_integration_grants%ROWTYPE; bound run_execution_bindings%ROWTYPE;
 task durable_jobs%ROWTYPE; operation run_tool_calls%ROWTYPE; allowed_arguments text[];
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'interactive tool history cannot be deleted'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['status','result','error_code','claimed_at','finished_at']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['status','result','error_code','claimed_at','finished_at']) THEN
   RAISE EXCEPTION 'interactive tool identity, arguments and authorization are immutable'; END IF;
  IF OLD.status IN ('SUCCEEDED','REJECTED') THEN RAISE EXCEPTION 'terminal interactive tool cannot replay'; END IF;
  IF OLD.status='UNKNOWN' THEN
   SELECT * INTO attachment FROM interactive_execution_bindings WHERE id=OLD.interactive_binding_id;
   SELECT * INTO operation FROM run_tool_calls WHERE binding_id=attachment.binding_id AND idempotency_key=OLD.idempotency_key;
   IF operation.id IS NULL OR operation.tool_name<>OLD.tool_name OR operation.input_sha256<>OLD.input_digest
      OR NOT ((NEW.status='SUCCEEDED' AND operation.status='SUCCEEDED') OR (NEW.status='REJECTED' AND operation.status='FAILED'))
      OR NEW.result IS DISTINCT FROM operation.result OR NEW.claimed_at IS DISTINCT FROM OLD.claimed_at THEN
    RAISE EXCEPTION 'unknown interactive tool permits only exact recorded-operation reconciliation'; END IF;
  ELSIF NOT ((OLD.status='QUEUED' AND NEW.status IN ('RUNNING','REJECTED','UNKNOWN')) OR
             (OLD.status='RUNNING' AND NEW.status IN ('SUCCEEDED','REJECTED','UNKNOWN'))) THEN
   RAISE EXCEPTION 'invalid interactive tool delivery transition';
  END IF;
  IF OLD.status='RUNNING' AND NEW.claimed_at IS DISTINCT FROM OLD.claimed_at THEN
   RAISE EXCEPTION 'interactive tool claim time is immutable'; END IF;
  IF OLD.status='RUNNING' AND NEW.status IN ('SUCCEEDED','REJECTED') THEN
   SELECT * INTO attachment FROM interactive_execution_bindings WHERE id=NEW.interactive_binding_id;
   SELECT * INTO bound FROM run_execution_bindings WHERE id=attachment.binding_id;
   SELECT * INTO task FROM durable_jobs WHERE id=NEW.job_id;
   IF bound.id IS NULL OR task.id IS NULL OR task.test_run_id<>attachment.test_run_id
      OR bound.binding_epoch<>NEW.binding_epoch OR bound.status NOT IN ('RESERVED','ACTIVE','WAITING_INPUT','CLOSED')
      OR task.status<>'RUNNING' OR task.lease_token IS NULL OR task.lease_expires_at<=clock_timestamp()
      OR NEW.claim_identity IS DISTINCT FROM encode(sha256(convert_to('hypertest.interactive-mcp/v1alpha1:'||attachment.id::text||':'||task.lease_token::text,'UTF8')),'hex') THEN
    RAISE EXCEPTION 'stale interactive Worker cannot publish a tool outcome'; END IF;
  END IF;
 ELSE
  IF NEW.status<>'QUEUED' OR NEW.result IS NOT NULL OR NEW.error_code IS NOT NULL
     OR NEW.claimed_at IS NOT NULL OR NEW.finished_at IS NOT NULL THEN
   RAISE EXCEPTION 'interactive tool request must start queued without an outcome'; END IF;
 END IF;
 IF NEW.status='RUNNING' AND (NEW.claimed_at IS NULL OR NEW.finished_at IS NOT NULL OR NEW.result IS NOT NULL OR NEW.error_code IS NOT NULL) THEN
  RAISE EXCEPTION 'running interactive tool requires its first claim time'; END IF;
 IF NEW.status IN ('SUCCEEDED','REJECTED','UNKNOWN') AND NEW.finished_at IS NULL THEN
  RAISE EXCEPTION 'settled interactive tool requires finish time'; END IF;
 IF NEW.status='SUCCEEDED' AND (NEW.result IS NULL OR NEW.error_code IS NOT NULL) THEN
  RAISE EXCEPTION 'successful interactive tool requires a result'; END IF;
 IF NEW.status='REJECTED' AND NEW.result IS NULL AND NEW.error_code IS NULL THEN
  RAISE EXCEPTION 'rejected interactive tool requires a controlled outcome'; END IF;

 allowed_arguments := CASE NEW.tool_name
  WHEN 'get_state' THEN ARRAY['resource','collection','path','evidence_id','entity_id','mission_id','offset','limit']
  WHEN 'request_mission' THEN ARRAY['idempotency_key','mission_type']
  WHEN 'complete_mission' THEN ARRAY['idempotency_key','mission_id','attempt_id','result']
  WHEN 'request_execution' THEN ARRAY['idempotency_key']
  WHEN 'ask_user' THEN ARRAY['idempotency_key','scope','request']
  WHEN 'evaluate_gate' THEN ARRAY['idempotency_key']
  WHEN 'submit_report' THEN ARRAY['idempotency_key','schema_version','test_run_id','source_snapshot_id','policy_snapshot_id','commit_sha','summary','markdown','execution_keys','evidence_keys','finding_keys','verdict_key','unresolved']
  WHEN 'request_gitlab_issue' THEN ARRAY['idempotency_key','finding_id','title','description','assignee']
  WHEN 'get_issue' THEN ARRAY['operation_id'] END;
 IF allowed_arguments IS NULL OR (NEW.arguments-allowed_arguments)<>'{}'::jsonb
    OR (NEW.tool_name NOT IN ('get_state','get_issue') AND NEW.arguments->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key) THEN
  RAISE EXCEPTION 'interactive tool requires a strict supported business schema'; END IF;

 -- Rejection/unknown marking does not require a still-valid execution lease.
 -- A new request or actual consumption always does; an inbox is no authority.
 IF TG_OP='INSERT' OR NEW.status='RUNNING' THEN
  SELECT * INTO attachment FROM interactive_execution_bindings WHERE id=NEW.interactive_binding_id;
  SELECT * INTO short FROM interactive_execution_grants WHERE id=NEW.execution_grant_id;
  SELECT * INTO integration FROM interactive_integration_grants WHERE id=NEW.integration_grant_id;
  SELECT * INTO bound FROM run_execution_bindings WHERE id=attachment.binding_id;
  SELECT * INTO task FROM durable_jobs WHERE id=NEW.job_id;
  IF attachment.id IS NULL OR short.id IS NULL OR integration.id IS NULL OR bound.id IS NULL OR task.id IS NULL
     OR attachment.actor_identity_id<>NEW.actor_identity_id OR attachment.client_instance_id<>NEW.client_instance_id
     OR short.interactive_binding_id<>attachment.id OR short.integration_grant_id<>integration.id
     OR short.job_id<>task.id OR short.binding_epoch<>NEW.binding_epoch OR short.claim_identity<>NEW.claim_identity
     OR integration.actor_identity_id<>NEW.actor_identity_id OR integration.client_instance_id<>NEW.client_instance_id
     OR integration.project_id<>task.project_id OR NOT integration.scopes ? 'run:execute'
     OR integration.status<>'ACTIVE' OR integration.not_before>clock_timestamp() OR integration.expires_at<=clock_timestamp()
     OR short.status<>'ACTIVE' OR short.not_before>clock_timestamp() OR short.expires_at<=clock_timestamp()
     OR bound.test_run_id<>attachment.test_run_id OR task.test_run_id<>attachment.test_run_id
     OR bound.binding_epoch<>NEW.binding_epoch OR bound.status NOT IN ('RESERVED','ACTIVE')
     OR task.status<>'RUNNING' OR task.lease_token IS NULL OR task.lease_expires_at<=clock_timestamp()
     OR NEW.claim_identity IS DISTINCT FROM encode(sha256(convert_to('hypertest.interactive-mcp/v1alpha1:'||attachment.id::text||':'||task.lease_token::text,'UTF8')),'hex')
     OR NOT EXISTS (SELECT 1 FROM interactive_client_registrations reg JOIN interactive_actor_identities principal ON principal.id=reg.actor_identity_id
          WHERE reg.actor_identity_id=NEW.actor_identity_id AND reg.client_instance_id=NEW.client_instance_id AND reg.status='ACTIVE' AND principal.status='ACTIVE')
     OR NOT EXISTS (SELECT 1 FROM harness_nodes WHERE id=attachment.node_id AND registration_status='ACTIVE')
     OR NOT EXISTS (SELECT 1 FROM node_project_capabilities WHERE node_id=attachment.node_id AND project_id=task.project_id AND capability='harness' AND status='ACTIVE')
     OR NOT EXISTS (SELECT 1 FROM harness_device_grants WHERE id=short.device_grant_id AND node_id=attachment.node_id AND status='ACTIVE' AND not_before<=clock_timestamp() AND expires_at>clock_timestamp()) THEN
   RAISE EXCEPTION 'interactive tool requires the original current Worker claim and registered execution scope'; END IF;
  IF TG_OP='INSERT' THEN
   PERFORM id FROM test_runs WHERE id=attachment.test_run_id FOR UPDATE;
   IF (SELECT count(*) FROM interactive_tool_requests WHERE job_id=NEW.job_id AND status IN ('QUEUED','RUNNING'))>=256 THEN
    RAISE EXCEPTION 'interactive tool transport inbox capacity exceeded'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END; $$;
"""
