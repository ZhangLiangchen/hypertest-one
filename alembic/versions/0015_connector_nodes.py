"""ADR-015 device identity, fixed placement and durable connector dispatch; no history backfill."""
import re

import sqlalchemy as sa

from alembic import op

revision = "0015_connector_nodes"
down_revision = "0014_harness_operations"
branch_labels = None
depends_on = None

def upgrade():
    op.execute(sa.text("\nCREATE TABLE harness_nodes (\n\tid UUID NOT NULL, \n\tnode_key VARCHAR(128) NOT NULL, \n\towner_identity_id VARCHAR(128) NOT NULL, \n\tnode_kind VARCHAR(32) NOT NULL, \n\tdisplay_name VARCHAR(128) NOT NULL, \n\tregistration_status VARCHAR(16) NOT NULL, \n\tpresence VARCHAR(16) NOT NULL, \n\tcapabilities JSONB NOT NULL, \n\tconnection_generation BIGINT NOT NULL, \n\tlast_seen_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trow_version BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_harness_node_kind CHECK (node_kind IN ('SERVER_HOST','LOCAL_CONNECTOR')), \n\tCONSTRAINT ck_harness_node_status CHECK (registration_status IN ('PENDING','ACTIVE','REVOKED')), \n\tCONSTRAINT ck_harness_node_presence CHECK (presence IN ('UNKNOWN','ONLINE','OFFLINE')), \n\tCONSTRAINT ck_harness_node_version CHECK (connection_generation >= 0 AND row_version > 0), \n\tUNIQUE (node_key)\n)\n\n"))
    op.execute(sa.text("\nCREATE TABLE harness_device_grants (\n\tid UUID NOT NULL, \n\tnode_id UUID NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\tkey_version VARCHAR(64) NOT NULL, \n\toperator_identity_id VARCHAR(128) NOT NULL, \n\tpolicy_version VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tnot_before TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trow_version BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_device_grant_status CHECK (status IN ('ACTIVE','EXPIRED','REVOKED')), \n\tCONSTRAINT ck_device_grant_validity CHECK (expires_at > not_before AND row_version > 0), \n\tFOREIGN KEY(node_id) REFERENCES harness_nodes (id) ON DELETE RESTRICT, \n\tUNIQUE (token_hash)\n)\n\n"))
    op.execute(sa.text("\nCREATE TABLE node_project_capabilities (\n\tid UUID NOT NULL, \n\tnode_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tcapability VARCHAR(32) NOT NULL, \n\tconstraints JSONB NOT NULL, \n\tpolicy_version VARCHAR(64) NOT NULL, \n\toperator_identity_id VARCHAR(128) NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\trow_version BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_node_capability CHECK (capability IN ('harness','source_acquisition','issue_executor')), \n\tCONSTRAINT ck_node_capability_status CHECK (status IN ('ACTIVE','REVOKED')), \n\tFOREIGN KEY(node_id) REFERENCES harness_nodes (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT\n)\n\n"))
    op.execute(sa.text("CREATE UNIQUE INDEX uq_node_active_capability ON node_project_capabilities (node_id, project_id, capability) WHERE status='ACTIVE'"))
    op.execute(sa.text("\nCREATE TABLE run_harness_placements (\n\tid UUID NOT NULL, \n\ttest_run_id UUID NOT NULL, \n\tbinding_id UUID NOT NULL, \n\tnode_id UUID NOT NULL, \n\tmode VARCHAR(32) NOT NULL, \n\tsource_transfer_kind VARCHAR(32) NOT NULL, \n\tsource_bundle_transfer_id UUID, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_harness_placement_mode CHECK (mode IN ('SERVER_HOST','LOCAL_CONNECTOR')), \n\tCONSTRAINT ck_harness_placement_source CHECK (source_transfer_kind IN ('SERVER_WORKSPACE','SOURCE_BUNDLE')), \n\tCONSTRAINT ck_harness_placement_bundle CHECK ((mode='LOCAL_CONNECTOR') = (source_bundle_transfer_id IS NOT NULL)), \n\tUNIQUE (test_run_id), \n\tFOREIGN KEY(test_run_id) REFERENCES test_runs (id) ON DELETE RESTRICT, \n\tUNIQUE (binding_id), \n\tFOREIGN KEY(binding_id) REFERENCES run_execution_bindings (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(node_id) REFERENCES harness_nodes (id) ON DELETE RESTRICT\n)\n\n"))
    op.execute(sa.text("\nCREATE TABLE harness_dispatch_grants (\n\tid UUID NOT NULL, \n\tnode_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tplacement_id UUID NOT NULL, \n\tbinding_id UUID NOT NULL, \n\tsession_id UUID NOT NULL, \n\tjob_id UUID NOT NULL, \n\tdevice_grant_id UUID NOT NULL, \n\tcapability_id UUID NOT NULL, \n\taudience VARCHAR(64) NOT NULL, \n\tworkspace_id VARCHAR(128) NOT NULL, \n\tclaim_identity VARCHAR(64) NOT NULL, \n\tbinding_epoch BIGINT NOT NULL, \n\tcall_id VARCHAR(128) NOT NULL, \n\toperation VARCHAR(32) NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tnot_before TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trow_version BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_dispatch_grant_status CHECK (status IN ('ACTIVE','EXPIRED','REVOKED')), \n\tCONSTRAINT ck_dispatch_grant_validity CHECK (binding_epoch > 0 AND expires_at > not_before), \n\tFOREIGN KEY(node_id) REFERENCES harness_nodes (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(placement_id) REFERENCES run_harness_placements (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(binding_id) REFERENCES run_execution_bindings (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(session_id) REFERENCES agent_sessions (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(job_id) REFERENCES durable_jobs (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(device_grant_id) REFERENCES harness_device_grants (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(capability_id) REFERENCES node_project_capabilities (id) ON DELETE RESTRICT\n)\n\n"))
    op.execute(sa.text("\nCREATE TABLE connector_requests (\n\tid UUID NOT NULL, \n\tnode_id UUID NOT NULL, \n\tdispatch_grant_id UUID, \n\toperation VARCHAR(32) NOT NULL, \n\tauthority VARCHAR(16) NOT NULL, \n\tpayload JSONB NOT NULL, \n\tinput_sha256 VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tresult JSONB, \n\terror_code VARCHAR(64), \n\tconnection_generation BIGINT, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tsent_at TIMESTAMP WITH TIME ZONE, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_connector_request_status CHECK (status IN ('QUEUED','SENT','SUCCEEDED','FAILED','UNKNOWN')), \n\tCONSTRAINT ck_connector_authority CHECK (authority IN ('execution','management','integration')), \n\tFOREIGN KEY(node_id) REFERENCES harness_nodes (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(dispatch_grant_id) REFERENCES harness_dispatch_grants (id) ON DELETE RESTRICT\n)\n\n"))
    op.execute(sa.text('CREATE INDEX ix_connector_mailbox ON connector_requests (node_id, status, created_at)'))
    for statement in re.split(r";\s*(?=CREATE (?:FUNCTION|TRIGGER))", GUARDS):
        op.execute(sa.text(statement))

def downgrade():
    for name in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {name})")):
            raise RuntimeError("retained Connector identity and operation history prevents destructive downgrade")
    for name in TABLES:
        op.drop_table(name)
    for name in ["node", "device_grant", "node_capability", "placement", "dispatch_grant", "request"]:
        op.execute(sa.text(f"DROP FUNCTION hypertest_guard_connector_{name}()"))

TABLES = ["connector_requests","harness_dispatch_grants","run_harness_placements","node_project_capabilities","harness_device_grants","harness_nodes"]
GUARDS = r"""
CREATE FUNCTION hypertest_guard_connector_node() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'node history cannot be deleted'; END IF;
 IF NEW.node_key !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$' OR length(btrim(NEW.owner_identity_id))=0
    OR jsonb_typeof(NEW.capabilities)<>'object' OR octet_length(NEW.capabilities::text)>32768 THEN
    RAISE EXCEPTION 'invalid node identity or capabilities';
 END IF;
 IF TG_OP='UPDATE' THEN
  IF (NEW.id,NEW.node_key,NEW.owner_identity_id,NEW.node_kind,NEW.created_at) IS DISTINCT FROM
     (OLD.id,OLD.node_key,OLD.owner_identity_id,OLD.node_kind,OLD.created_at) THEN RAISE EXCEPTION 'node identity is immutable'; END IF;
  IF OLD.registration_status='REVOKED' AND NEW.registration_status<>'REVOKED' THEN RAISE EXCEPTION 'revoked node cannot reactivate'; END IF;
  IF NEW.connection_generation<OLD.connection_generation OR NEW.connection_generation>OLD.connection_generation+1 THEN RAISE EXCEPTION 'invalid connection generation'; END IF;
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER connector_node_guard BEFORE INSERT OR UPDATE OR DELETE ON harness_nodes FOR EACH ROW EXECUTE FUNCTION hypertest_guard_connector_node();
CREATE FUNCTION hypertest_guard_connector_device_grant() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'device grant history cannot be deleted'; END IF;
 IF NEW.token_hash !~ '^[a-f0-9]{64}$' OR length(btrim(NEW.key_version))=0 THEN RAISE EXCEPTION 'invalid device credential identity'; END IF;
 IF TG_OP='INSERT' AND (NEW.status<>'ACTIVE' OR NOT EXISTS (SELECT 1 FROM harness_nodes WHERE id=NEW.node_id AND registration_status='ACTIVE')) THEN RAISE EXCEPTION 'device grant requires an active node'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['status','revoked_at','row_version']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','revoked_at','row_version']) THEN RAISE EXCEPTION 'device grant identity and scope are immutable'; END IF;
  IF OLD.status<>'ACTIVE' OR NEW.status NOT IN ('EXPIRED','REVOKED') THEN RAISE EXCEPTION 'terminal device grant cannot reactivate'; END IF;
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER connector_device_grant_guard BEFORE INSERT OR UPDATE OR DELETE ON harness_device_grants FOR EACH ROW EXECUTE FUNCTION hypertest_guard_connector_device_grant();
CREATE FUNCTION hypertest_guard_connector_node_capability() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'project capability history cannot be deleted'; END IF;
 IF jsonb_typeof(NEW.constraints)<>'object' OR octet_length(NEW.constraints::text)>32768 THEN RAISE EXCEPTION 'capability scope must be a bounded object'; END IF;
 IF TG_OP='INSERT' AND (NEW.status<>'ACTIVE' OR NOT EXISTS (SELECT 1 FROM harness_nodes WHERE id=NEW.node_id AND registration_status='ACTIVE')) THEN RAISE EXCEPTION 'capability requires an active node'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['status','revoked_at','row_version']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','revoked_at','row_version']) THEN RAISE EXCEPTION 'project capability identity and scope are immutable'; END IF;
  IF OLD.status<>'ACTIVE' OR NEW.status<>'REVOKED' THEN RAISE EXCEPTION 'terminal capability cannot reactivate'; END IF;
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER connector_node_capability_guard BEFORE INSERT OR UPDATE OR DELETE ON node_project_capabilities FOR EACH ROW EXECUTE FUNCTION hypertest_guard_connector_node_capability();
CREATE FUNCTION hypertest_guard_connector_placement() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bound run_execution_bindings%ROWTYPE; node harness_nodes%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'run harness placement is immutable'; END IF;
 SELECT * INTO bound FROM run_execution_bindings WHERE id=NEW.binding_id;
 SELECT * INTO node FROM harness_nodes WHERE id=NEW.node_id;
 IF bound.id IS NULL OR node.id IS NULL OR NEW.test_run_id<>bound.test_run_id OR NEW.mode<>node.node_kind
    OR bound.harness_host_id<>node.node_key OR node.registration_status<>'ACTIVE' THEN RAISE EXCEPTION 'placement scope does not match binding and node'; END IF;
 IF (NEW.mode='LOCAL_CONNECTOR')<>(NEW.source_transfer_kind='SOURCE_BUNDLE') THEN RAISE EXCEPTION 'placement source mode mismatch'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER connector_placement_guard BEFORE INSERT OR UPDATE OR DELETE ON run_harness_placements FOR EACH ROW EXECUTE FUNCTION hypertest_guard_connector_placement();
CREATE FUNCTION hypertest_guard_connector_dispatch_grant() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bound run_execution_bindings%ROWTYPE; task durable_jobs%ROWTYPE; placed run_harness_placements%ROWTYPE;
        device harness_device_grants%ROWTYPE; cap node_project_capabilities%ROWTYPE; projected uuid; expected_claim text;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'dispatch history cannot be deleted'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['status','row_version']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','row_version']) THEN RAISE EXCEPTION 'dispatch identity and scope are immutable'; END IF;
  IF OLD.status<>'ACTIVE' OR NEW.status NOT IN ('EXPIRED','REVOKED') THEN RAISE EXCEPTION 'terminal dispatch cannot reactivate'; END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO bound FROM run_execution_bindings WHERE id=NEW.binding_id;
 SELECT * INTO task FROM durable_jobs WHERE id=NEW.job_id;
 SELECT * INTO placed FROM run_harness_placements WHERE id=NEW.placement_id;
 SELECT * INTO device FROM harness_device_grants WHERE id=NEW.device_grant_id;
 SELECT * INTO cap FROM node_project_capabilities WHERE id=NEW.capability_id;
 SELECT project_id INTO projected FROM test_runs WHERE id=bound.test_run_id;
 expected_claim=encode(sha256(convert_to('hypertest.harness-connector/v1alpha1:'||NEW.node_id::text||':'||task.lease_token::text,'UTF8')),'hex');
 IF bound.id IS NULL OR task.id IS NULL OR placed.id IS NULL OR device.id IS NULL OR cap.id IS NULL
    OR placed.binding_id<>bound.id OR placed.node_id<>NEW.node_id OR placed.mode<>'LOCAL_CONNECTOR'
    OR NEW.project_id<>projected OR NEW.session_id<>bound.primary_agent_session_id
    OR NEW.workspace_id<>replace(bound.workspace_id,'-','') OR NEW.binding_epoch<>bound.binding_epoch
    OR task.test_run_id<>bound.test_run_id OR task.status<>'RUNNING' OR task.lease_token IS NULL
    OR task.lease_expires_at<=clock_timestamp() OR bound.status NOT IN ('RESERVED','ACTIVE')
    OR device.node_id<>NEW.node_id OR device.status<>'ACTIVE' OR device.not_before>clock_timestamp() OR device.expires_at<=clock_timestamp()
    OR cap.node_id<>NEW.node_id OR cap.project_id<>NEW.project_id OR cap.capability<>'harness' OR cap.status<>'ACTIVE'
    OR NOT EXISTS (SELECT 1 FROM harness_nodes WHERE id=NEW.node_id AND registration_status='ACTIVE')
    OR NEW.claim_identity IS DISTINCT FROM expected_claim OR NEW.status<>'ACTIVE'
    OR NEW.not_before>clock_timestamp()+interval '2 seconds' OR NEW.expires_at<=clock_timestamp()
    OR NEW.expires_at>least(task.lease_expires_at,device.expires_at,clock_timestamp()+interval '120 seconds')
    OR NEW.audience<>'hypertest.harness-connector/v1alpha1' OR length(btrim(NEW.call_id))=0
    OR NEW.operation NOT IN ('create_session','execute','resume','get_call','renew','respond_tool') THEN
    RAISE EXCEPTION 'dispatch requires current binding claim and explicit project device scope';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER connector_dispatch_grant_guard BEFORE INSERT OR UPDATE OR DELETE ON harness_dispatch_grants FOR EACH ROW EXECUTE FUNCTION hypertest_guard_connector_dispatch_grant();
CREATE FUNCTION hypertest_guard_connector_request() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE dispatched harness_dispatch_grants%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'connector request history cannot be deleted'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['status','result','error_code','connection_generation','sent_at','finished_at']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['status','result','error_code','connection_generation','sent_at','finished_at']) THEN RAISE EXCEPTION 'connector request identity and input are immutable'; END IF;
  IF OLD.status IN ('SUCCEEDED','FAILED','UNKNOWN') THEN RAISE EXCEPTION 'terminal connector request cannot replay'; END IF;
  IF NOT ((OLD.status='QUEUED' AND NEW.status IN ('SENT','UNKNOWN')) OR
          (OLD.status='SENT' AND NEW.status IN ('SUCCEEDED','FAILED','UNKNOWN'))) THEN RAISE EXCEPTION 'invalid connector dispatch transition'; END IF;
  IF OLD.status='SENT' AND (NEW.connection_generation,NEW.sent_at) IS DISTINCT FROM (OLD.connection_generation,OLD.sent_at) THEN RAISE EXCEPTION 'sent delivery identity cannot change'; END IF;
 ELSE
  IF NEW.status<>'QUEUED' THEN RAISE EXCEPTION 'connector request must start queued'; END IF;
 END IF;
 IF NEW.operation NOT IN ('capabilities','create_session','execute','resume','get_call','renew','respond_tool','restore_session','interrupt','recover','close','prepare_source','source_prepare','install_workspace','issue_create','issue_query')
    OR NEW.input_sha256 !~ '^[a-f0-9]{64}$' OR jsonb_typeof(NEW.payload)<>'object' OR octet_length(NEW.payload::text)>4000000
    OR NEW.expires_at>NEW.created_at+interval '121 seconds'
    OR (NEW.authority='management' AND NEW.operation NOT IN ('capabilities','get_call','restore_session','interrupt','recover','close','issue_query'))
    OR (NEW.authority='integration' AND NEW.operation NOT IN ('prepare_source','source_prepare','install_workspace','issue_create','issue_query'))
    OR (NEW.authority='execution' AND NEW.operation NOT IN ('create_session','execute','resume','get_call','renew','respond_tool')) THEN RAISE EXCEPTION 'invalid typed connector request'; END IF;
 IF NEW.authority='execution' THEN
  SELECT * INTO dispatched FROM harness_dispatch_grants WHERE id=NEW.dispatch_grant_id;
  IF dispatched.id IS NULL OR dispatched.node_id<>NEW.node_id OR dispatched.operation<>NEW.operation
     OR NEW.expires_at>dispatched.expires_at OR NEW.payload->'context'->>'binding_id'<>dispatched.binding_id::text
     OR (NEW.payload->'context'->>'binding_epoch')::bigint<>dispatched.binding_epoch
     OR NEW.payload->'context'->>'claim_token'<>dispatched.claim_identity THEN RAISE EXCEPTION 'connector execution scope mismatch'; END IF;
 END IF;
 IF NEW.status='SENT' AND (NEW.sent_at IS NULL OR NEW.connection_generation IS NULL) THEN RAISE EXCEPTION 'sent connector request requires consumed delivery'; END IF;
 IF NEW.status IN ('SUCCEEDED','FAILED','UNKNOWN') AND NEW.finished_at IS NULL THEN RAISE EXCEPTION 'terminal connector request requires finish time'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER connector_request_guard BEFORE INSERT OR UPDATE OR DELETE ON connector_requests FOR EACH ROW EXECUTE FUNCTION hypertest_guard_connector_request();
"""
