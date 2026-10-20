"""ADR-016 registered interactive identities and immutable execution admission."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0019_interactive_mcp"
down_revision = "0018_harness_selection"
branch_labels = None
depends_on = None


def u(name, target=None, *, primary=False, nullable=False, unique=False):
    args = [sa.ForeignKey(target, ondelete="RESTRICT")] if target else []
    return sa.Column(name, sa.Uuid(), *args, primary_key=primary, nullable=nullable, unique=unique)


def s(name, size=128, *, nullable=False, unique=False):
    return sa.Column(name, sa.String(size), nullable=nullable, unique=unique)


def t(name, *, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    op.create_table("interactive_actor_identities", u("id", primary=True), s("actor_ref", unique=True),
        s("registered_by"), s("status", 16), t("created_at"), t("revoked_at", nullable=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED')", name="ck_interactive_actor_status"))
    op.create_table("interactive_client_registrations", u("actor_identity_id", "interactive_actor_identities.id", primary=True),
        u("client_instance_id", primary=True), s("registered_by"), s("status", 16),
        t("created_at"), t("revoked_at", nullable=True), sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED')", name="ck_interactive_client_status"))
    op.create_table("interactive_integration_grants", u("id", primary=True), u("actor_identity_id", "interactive_actor_identities.id"),
        u("client_instance_id"), u("project_id", "projects.id"), sa.Column("scopes", JSONB(), nullable=False),
        s("token_hash", 64, unique=True), s("policy_version", 64), s("registered_by"), s("status", 16),
        t("not_before"), t("expires_at"), t("created_at"), t("revoked_at", nullable=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["actor_identity_id", "client_instance_id"],
            ["interactive_client_registrations.actor_identity_id", "interactive_client_registrations.client_instance_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('ACTIVE','EXPIRED','REVOKED')", name="ck_interactive_integration_status"),
        sa.CheckConstraint("token_hash ~ '^[a-f0-9]{64}$' AND expires_at > not_before AND row_version > 0", name="ck_interactive_integration_validity"),
        sa.CheckConstraint("jsonb_typeof(scopes)='array' AND jsonb_array_length(scopes)>0 AND scopes <@ '[\"task:submit\",\"run:read\",\"evidence:read\",\"report:read\",\"run:execute\"]'::jsonb", name="ck_interactive_integration_scopes"))
    op.create_table("run_execution_selections", u("test_run_id", "test_runs.id", primary=True),
        s("execution_mode", 16), s("execution_driver", 32), s("harness_mode", 32),
        s("harness_host_id", 255, nullable=True), u("node_id", "harness_nodes.id", nullable=True),
        u("source_bundle_transfer_id", "source_bundle_transfers.id", nullable=True), t("created_at"),
        sa.CheckConstraint("(execution_mode='CLOUD' AND harness_mode='SERVER_HOST' AND execution_driver='PLATFORM_MANAGED' AND source_bundle_transfer_id IS NULL) OR (execution_mode='LOCAL' AND harness_mode='LOCAL_CONNECTOR' AND execution_driver IN ('PLATFORM_MANAGED','INTERACTIVE_MCP') AND node_id IS NOT NULL AND source_bundle_transfer_id IS NOT NULL)", name="ck_execution_selection_combination"))
    op.create_table("interactive_submission_receipts", u("id", primary=True),
        u("grant_id", "interactive_integration_grants.id"), u("actor_identity_id", "interactive_actor_identities.id"),
        u("client_instance_id"), u("project_id", "projects.id"), s("submission_key", 255),
        s("normalization_version", 64), s("input_digest", 64), sa.Column("input_manifest", JSONB(), nullable=False),
        s("status", 16), u("test_run_id", "test_runs.id", nullable=True, unique=True),
        u("initial_durable_job_id", "durable_jobs.id", nullable=True, unique=True), s("error_code", 64, nullable=True), t("created_at"),
        sa.UniqueConstraint("actor_identity_id", "client_instance_id", "project_id", "submission_key", name="uq_interactive_submission_key"),
        sa.CheckConstraint("input_digest ~ '^[a-f0-9]{64}$' AND length(btrim(submission_key)) BETWEEN 1 AND 255", name="ck_interactive_submission_input"),
        sa.CheckConstraint("(status='ACCEPTED' AND test_run_id IS NOT NULL AND initial_durable_job_id IS NOT NULL AND error_code IS NULL) OR (status='REJECTED' AND test_run_id IS NULL AND initial_durable_job_id IS NULL AND error_code IS NOT NULL)", name="ck_interactive_submission_result"))
    op.create_table("interactive_execution_bindings", u("id", primary=True),
        u("binding_id", "run_execution_bindings.id", unique=True), u("agent_session_id", "agent_sessions.id", unique=True),
        u("test_run_id", "test_runs.id", unique=True), u("grant_id", "interactive_integration_grants.id"),
        u("actor_identity_id", "interactive_actor_identities.id"), u("client_instance_id"), u("node_id", "harness_nodes.id"),
        s("provider", 64), sa.Column("native_session_id", sa.Text(), nullable=False), sa.Column("workspace_id", sa.Text(), nullable=False),
        s("attach_key", 255), s("normalization_version", 64), s("input_digest", 64),
        sa.Column("attached_epoch", sa.BigInteger(), nullable=False), s("host_attachment_id", 255), s("host_proof_sha256", 64),
        sa.Column("host_proof", JSONB(), nullable=False), t("created_at"),
        sa.UniqueConstraint("actor_identity_id", "client_instance_id", "test_run_id", "attach_key", name="uq_interactive_attach_key"),
        sa.CheckConstraint("input_digest ~ '^[a-f0-9]{64}$' AND host_proof_sha256 ~ '^[a-f0-9]{64}$' AND attached_epoch>0 AND length(btrim(attach_key)) BETWEEN 1 AND 255", name="ck_interactive_attachment_input"),
        sa.CheckConstraint("length(btrim(native_session_id))>0 AND length(btrim(host_attachment_id))>0", name="ck_interactive_attachment_native"))
    op.create_table("interactive_execution_grants", u("id", primary=True),
        u("interactive_binding_id", "interactive_execution_bindings.id"), u("job_id", "durable_jobs.id"),
        u("integration_grant_id", "interactive_integration_grants.id"), s("token_hash", 64, unique=True),
        sa.Column("binding_epoch", sa.BigInteger(), nullable=False), s("claim_identity", 64), s("call_id", 128),
        s("host_attachment_id", 255), s("host_proof_sha256", 64), s("status", 16),
        t("not_before"), t("expires_at"), t("created_at"), sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("interactive_binding_id", "call_id", name="uq_interactive_execution_call"),
        sa.CheckConstraint("status IN ('ACTIVE','EXPIRED','REVOKED')", name="ck_interactive_execution_grant_status"),
        sa.CheckConstraint("binding_epoch>0 AND expires_at>not_before AND token_hash ~ '^[a-f0-9]{64}$'", name="ck_interactive_execution_grant_validity"))
    op.execute(sa.text(GUARD))
    for table in TABLES:
        op.execute(sa.text(f"CREATE TRIGGER interactive_history_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hypertest_guard_interactive()"))


TABLES = ("interactive_actor_identities", "interactive_client_registrations", "interactive_integration_grants",
          "run_execution_selections", "interactive_submission_receipts", "interactive_execution_bindings", "interactive_execution_grants")


def downgrade():
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("retained interactive identities or execution history prevent destructive downgrade")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION hypertest_guard_interactive()")


GUARD = r"""
CREATE FUNCTION hypertest_guard_interactive() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE g interactive_integration_grants%ROWTYPE; r test_runs%ROWTYPE; j durable_jobs%ROWTYPE;
 b run_execution_bindings%ROWTYPE; a agent_sessions%ROWTYPE; n harness_nodes%ROWTYPE;
 x interactive_execution_bindings%ROWTYPE; choice run_execution_selections%ROWTYPE;
 prior run_harness_selections%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'interactive history cannot be deleted'; END IF;
 IF TG_OP='UPDATE' THEN
  IF TG_TABLE_NAME IN ('interactive_actor_identities','interactive_client_registrations','interactive_integration_grants','interactive_execution_grants') THEN
   IF (to_jsonb(NEW)-ARRAY['status','row_version','revoked_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','row_version','revoked_at']) THEN
    RAISE EXCEPTION 'interactive identity and authorization are immutable'; END IF;
   IF OLD.status<>'ACTIVE' OR NEW.status NOT IN ('REVOKED','EXPIRED') OR NEW.row_version<=OLD.row_version THEN
    RAISE EXCEPTION 'interactive authorization cannot reactivate'; END IF;
   RETURN NEW;
  END IF;
  RAISE EXCEPTION 'interactive admission and receipt history is append-only';
 END IF;
 IF TG_TABLE_NAME IN ('interactive_actor_identities','interactive_client_registrations') THEN
  IF NEW.status<>'ACTIVE' OR length(btrim(NEW.registered_by))=0 OR NEW.row_version<1 THEN
   RAISE EXCEPTION 'interactive identity requires explicit registration'; END IF;
  IF TG_TABLE_NAME='interactive_client_registrations' THEN
   IF NOT EXISTS (SELECT 1 FROM interactive_actor_identities WHERE id=NEW.actor_identity_id AND status='ACTIVE') THEN
    RAISE EXCEPTION 'interactive client requires an active registered actor'; END IF;
  END IF;
  RETURN NEW;
 ELSIF TG_TABLE_NAME='interactive_integration_grants' THEN
  IF NEW.status<>'ACTIVE' OR length(btrim(NEW.registered_by))=0 OR NOT EXISTS (
      SELECT 1 FROM interactive_client_registrations c JOIN interactive_actor_identities registered_actor ON registered_actor.id=c.actor_identity_id
      WHERE c.actor_identity_id=NEW.actor_identity_id AND c.client_instance_id=NEW.client_instance_id AND c.status='ACTIVE' AND registered_actor.status='ACTIVE') THEN
   RAISE EXCEPTION 'interactive grant requires registered actor and client'; END IF;
  RETURN NEW;
 ELSIF TG_TABLE_NAME='run_execution_selections' THEN
  SELECT * INTO r FROM test_runs WHERE id=NEW.test_run_id;
  IF EXISTS (SELECT 1 FROM run_execution_bindings WHERE test_run_id=NEW.test_run_id) THEN
   RAISE EXCEPTION 'execution selection must precede the run binding'; END IF;
  IF NEW.node_id IS NOT NULL THEN
   SELECT * INTO n FROM harness_nodes WHERE id=NEW.node_id;
   IF n.registration_status IS DISTINCT FROM 'ACTIVE' OR n.node_kind IS DISTINCT FROM NEW.harness_mode OR n.node_key IS DISTINCT FROM NEW.harness_host_id THEN
    RAISE EXCEPTION 'execution choice requires matching registered node'; END IF;
  END IF;
  IF length(btrim(COALESCE(NEW.harness_host_id,'')))=0 THEN RAISE EXCEPTION 'execution choice requires a stable host'; END IF;
  IF NEW.execution_mode='LOCAL' THEN
   SELECT * INTO prior FROM run_harness_selections WHERE test_run_id=NEW.test_run_id;
   IF prior.node_id IS DISTINCT FROM NEW.node_id OR prior.source_bundle_transfer_id IS DISTINCT FROM NEW.source_bundle_transfer_id THEN
    RAISE EXCEPTION 'interactive execution choice must preserve accepted source selection'; END IF;
  END IF;
  RETURN NEW;
 ELSIF TG_TABLE_NAME='interactive_submission_receipts' THEN
  SELECT * INTO g FROM interactive_integration_grants WHERE id=NEW.grant_id;
  IF g.id IS NULL OR g.actor_identity_id<>NEW.actor_identity_id OR g.client_instance_id<>NEW.client_instance_id OR g.project_id<>NEW.project_id
     OR g.status<>'ACTIVE' OR g.not_before>clock_timestamp() OR g.expires_at<=clock_timestamp() OR NOT g.scopes ? 'task:submit'
     OR NOT EXISTS (SELECT 1 FROM interactive_client_registrations reg JOIN interactive_actor_identities registered_actor ON registered_actor.id=reg.actor_identity_id
                    WHERE reg.actor_identity_id=g.actor_identity_id AND reg.client_instance_id=g.client_instance_id AND reg.status='ACTIVE' AND registered_actor.status='ACTIVE') THEN
   RAISE EXCEPTION 'submission receipt requires current registered submission scope'; END IF;
  IF NEW.status='ACCEPTED' THEN
   SELECT * INTO r FROM test_runs WHERE id=NEW.test_run_id;
   SELECT * INTO j FROM durable_jobs WHERE id=NEW.initial_durable_job_id;
   IF r.id IS NULL OR j.id IS NULL OR r.project_id<>NEW.project_id OR j.test_run_id<>r.id OR j.project_id<>NEW.project_id OR j.job_type<>'ADVANCE_RUN'
      OR NOT EXISTS (SELECT 1 FROM run_execution_selections WHERE test_run_id=r.id) THEN
    RAISE EXCEPTION 'accepted submission requires same-project run selection and initial job'; END IF;
  END IF;
  RETURN NEW;
 ELSIF TG_TABLE_NAME='interactive_execution_bindings' THEN
  SELECT * INTO g FROM interactive_integration_grants WHERE id=NEW.grant_id;
  SELECT * INTO b FROM run_execution_bindings WHERE id=NEW.binding_id;
  SELECT * INTO a FROM agent_sessions WHERE id=NEW.agent_session_id;
  SELECT * INTO n FROM harness_nodes WHERE id=NEW.node_id;
  SELECT * INTO r FROM test_runs WHERE id=NEW.test_run_id;
  SELECT * INTO choice FROM run_execution_selections WHERE test_run_id=NEW.test_run_id;
  IF g.id IS NULL OR b.id IS NULL OR a.id IS NULL OR r.id IS NULL OR n.id IS NULL
     OR g.actor_identity_id<>NEW.actor_identity_id OR g.client_instance_id<>NEW.client_instance_id OR g.project_id<>r.project_id
     OR g.status<>'ACTIVE' OR g.not_before>clock_timestamp() OR g.expires_at<=clock_timestamp() OR NOT g.scopes ? 'run:execute'
     OR NOT EXISTS (SELECT 1 FROM interactive_client_registrations reg JOIN interactive_actor_identities registered_actor ON registered_actor.id=reg.actor_identity_id
                    WHERE reg.actor_identity_id=g.actor_identity_id AND reg.client_instance_id=g.client_instance_id AND reg.status='ACTIVE' AND registered_actor.status='ACTIVE')
     OR choice.execution_driver IS DISTINCT FROM 'INTERACTIVE_MCP' OR choice.execution_mode IS DISTINCT FROM 'LOCAL' OR choice.node_id IS DISTINCT FROM NEW.node_id
     OR b.test_run_id<>r.id OR b.primary_agent_session_id<>a.id OR a.test_run_id<>r.id OR b.harness_host_id<>n.node_key
     OR a.provider<>NEW.provider OR a.provider_session_id IS DISTINCT FROM NEW.native_session_id
     OR a.workspace_id<>NEW.workspace_id OR b.workspace_id<>NEW.workspace_id OR b.binding_epoch<>NEW.attached_epoch
     OR b.status NOT IN ('RESERVED','ACTIVE') OR n.registration_status<>'ACTIVE' OR jsonb_typeof(NEW.host_proof)<>'object'
     OR NOT EXISTS (SELECT 1 FROM node_project_capabilities WHERE node_id=n.id AND project_id=r.project_id AND capability='harness' AND status='ACTIVE')
     OR NOT EXISTS (SELECT 1 FROM harness_device_grants WHERE node_id=n.id AND status='ACTIVE' AND not_before<=clock_timestamp() AND expires_at>clock_timestamp())
     OR NOT EXISTS (SELECT 1 FROM run_harness_placements WHERE binding_id=b.id AND node_id=n.id AND mode='LOCAL_CONNECTOR') THEN
   RAISE EXCEPTION 'interactive attach requires original native session and current device project scope'; END IF;
  RETURN NEW;
 ELSIF TG_TABLE_NAME='interactive_execution_grants' THEN
  SELECT * INTO x FROM interactive_execution_bindings WHERE id=NEW.interactive_binding_id;
  SELECT * INTO b FROM run_execution_bindings WHERE id=x.binding_id;
  SELECT * INTO r FROM test_runs WHERE id=x.test_run_id;
  SELECT * INTO j FROM durable_jobs WHERE id=NEW.job_id;
  SELECT * INTO g FROM interactive_integration_grants WHERE id=NEW.integration_grant_id;
  IF x.id IS NULL OR b.id IS NULL OR j.id IS NULL OR g.id IS NULL OR NEW.status<>'ACTIVE'
     OR g.actor_identity_id<>x.actor_identity_id OR g.client_instance_id<>x.client_instance_id OR g.project_id<>r.project_id
     OR g.status<>'ACTIVE' OR g.not_before>clock_timestamp() OR g.expires_at<=clock_timestamp() OR NOT g.scopes ? 'run:execute'
     OR NOT EXISTS (SELECT 1 FROM interactive_client_registrations reg JOIN interactive_actor_identities registered_actor ON registered_actor.id=reg.actor_identity_id
                    WHERE reg.actor_identity_id=g.actor_identity_id AND reg.client_instance_id=g.client_instance_id AND reg.status='ACTIVE' AND registered_actor.status='ACTIVE')
     OR j.test_run_id<>x.test_run_id OR j.status<>'RUNNING' OR j.lease_token IS NULL OR j.lease_expires_at<=clock_timestamp()
     OR b.binding_epoch<>NEW.binding_epoch OR b.status NOT IN ('RESERVED','ACTIVE')
     OR NOT EXISTS (SELECT 1 FROM harness_nodes WHERE id=x.node_id AND registration_status='ACTIVE')
     OR NOT EXISTS (SELECT 1 FROM node_project_capabilities WHERE node_id=x.node_id AND project_id=r.project_id AND capability='harness' AND status='ACTIVE')
     OR NOT EXISTS (SELECT 1 FROM harness_device_grants WHERE node_id=x.node_id AND status='ACTIVE' AND not_before<=clock_timestamp() AND expires_at>clock_timestamp())
     OR NOT EXISTS (SELECT 1 FROM agent_sessions WHERE id=x.agent_session_id AND provider_session_id=x.native_session_id AND status IN ('CREATED','RUNNING'))
     OR NEW.expires_at>least(j.lease_expires_at,g.expires_at,clock_timestamp()+interval '120 seconds')
     OR NEW.expires_at<=clock_timestamp() OR NEW.not_before>clock_timestamp()+interval '2 seconds'
     OR NEW.host_attachment_id<>x.host_attachment_id OR NEW.host_proof_sha256 !~ '^[a-f0-9]{64}$'
     OR NEW.claim_identity IS DISTINCT FROM encode(sha256(convert_to('hypertest.interactive-mcp/v1alpha1:'||x.id::text||':'||j.lease_token::text,'UTF8')),'hex')
     OR length(btrim(NEW.call_id))=0 THEN
   RAISE EXCEPTION 'interactive execution grant requires current run claim and native attachment'; END IF;
  RETURN NEW;
 END IF;
 RAISE EXCEPTION 'unrecognized interactive history table';
END; $$;
"""
