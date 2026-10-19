"""Freeze local admission before establishing the one persistent Run binding."""
import re

import sqlalchemy as sa

from alembic import op

revision = "0018_harness_selection"
down_revision = "0017_issue_executor"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("run_harness_selections",
        sa.Column("test_run_id", sa.Uuid(), sa.ForeignKey("test_runs.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("node_id", sa.Uuid(), sa.ForeignKey("harness_nodes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_bundle_transfer_id", sa.Uuid(), sa.ForeignKey("source_bundle_transfers.id", ondelete="RESTRICT"), nullable=False),
        sa.CheckConstraint("mode = 'LOCAL_CONNECTOR'", name="ck_harness_selection_mode"))
    op.execute("""CREATE FUNCTION protect_harness_selection() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Harness admission selection is immutable'; END $$;""")
    op.execute("""CREATE TRIGGER protect_harness_selection BEFORE UPDATE OR DELETE ON run_harness_selections
    FOR EACH ROW EXECUTE FUNCTION protect_harness_selection();""")
    for statement in re.split(r";\s*(?=CREATE (?:OR REPLACE )?(?:FUNCTION|TRIGGER))", GUARDS):
        op.execute(sa.text(statement))


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM run_harness_selections)")):
        raise RuntimeError("retained Harness admission history prevents destructive downgrade")
    op.execute(sa.text(ORIGINAL_PLACEMENT))
    op.drop_table("run_harness_selections")
    op.execute("DROP FUNCTION protect_harness_selection()")

    op.execute("DROP FUNCTION admit_harness_selection()")


GUARDS = r"""
CREATE FUNCTION admit_harness_selection() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE task test_runs%ROWTYPE; snap source_snapshots%ROWTYPE; transfer source_bundle_transfers%ROWTYPE; device harness_nodes%ROWTYPE;
BEGIN
 SELECT * INTO task FROM test_runs WHERE id=NEW.test_run_id;
 SELECT * INTO snap FROM source_snapshots WHERE id=task.source_snapshot_id;
 SELECT * INTO transfer FROM source_bundle_transfers WHERE id=NEW.source_bundle_transfer_id;
 SELECT * INTO device FROM harness_nodes WHERE id=NEW.node_id;
 IF task.id IS NULL OR snap.id IS NULL OR transfer.id IS NULL OR device.id IS NULL
    OR NEW.mode<>'LOCAL_CONNECTOR' OR device.node_kind<>'LOCAL_CONNECTOR' OR device.registration_status<>'ACTIVE'
    OR transfer.status<>'ACCEPTED' OR transfer.project_id<>task.project_id OR transfer.node_id<>NEW.node_id
    OR transfer.origin<>snap.repository_url OR transfer.commit_sha<>snap.commit_sha
    OR NOT EXISTS (SELECT 1 FROM node_project_capabilities WHERE node_id=NEW.node_id AND project_id=task.project_id
                   AND capability='harness' AND status='ACTIVE')
    OR NOT EXISTS (SELECT 1 FROM node_project_capabilities WHERE id=transfer.source_capability_id
                   AND node_id=NEW.node_id AND project_id=task.project_id AND capability='source_acquisition'
                   AND status='ACTIVE' AND policy_version=transfer.policy_version
                   AND constraints->'allowed_origins' ? transfer.origin) THEN
   RAISE EXCEPTION 'Harness selection requires accepted same-project source and explicit device scope';
 END IF;
 IF EXISTS (SELECT 1 FROM run_execution_bindings WHERE test_run_id=NEW.test_run_id) THEN
   RAISE EXCEPTION 'Harness selection must precede the Run binding';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER admit_harness_selection BEFORE INSERT ON run_harness_selections
 FOR EACH ROW EXECUTE FUNCTION admit_harness_selection();
CREATE OR REPLACE FUNCTION hypertest_guard_connector_placement() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bound run_execution_bindings%ROWTYPE; node harness_nodes%ROWTYPE; selected run_harness_selections%ROWTYPE;
        task test_runs%ROWTYPE; snap source_snapshots%ROWTYPE; transfer source_bundle_transfers%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'run harness placement is immutable'; END IF;
 SELECT * INTO bound FROM run_execution_bindings WHERE id=NEW.binding_id;
 SELECT * INTO node FROM harness_nodes WHERE id=NEW.node_id;
 IF bound.id IS NULL OR node.id IS NULL OR NEW.test_run_id<>bound.test_run_id OR NEW.mode<>node.node_kind
    OR bound.harness_host_id<>node.node_key OR node.registration_status<>'ACTIVE' THEN RAISE EXCEPTION 'placement scope does not match binding and node'; END IF;
 IF (NEW.mode='LOCAL_CONNECTOR')<>(NEW.source_transfer_kind='SOURCE_BUNDLE') THEN RAISE EXCEPTION 'placement source mode mismatch'; END IF;
 IF NEW.mode='LOCAL_CONNECTOR' THEN
   SELECT * INTO selected FROM run_harness_selections WHERE test_run_id=NEW.test_run_id;
   SELECT * INTO task FROM test_runs WHERE id=NEW.test_run_id;
   SELECT * INTO snap FROM source_snapshots WHERE id=task.source_snapshot_id;
   SELECT * INTO transfer FROM source_bundle_transfers WHERE id=NEW.source_bundle_transfer_id;
   IF selected.test_run_id IS NULL OR transfer.id IS NULL OR snap.id IS NULL
      OR selected.node_id<>NEW.node_id OR selected.mode<>NEW.mode
      OR selected.source_bundle_transfer_id<>NEW.source_bundle_transfer_id
      OR transfer.status<>'ACCEPTED' OR transfer.node_id<>NEW.node_id OR transfer.project_id<>task.project_id
      OR transfer.origin<>snap.repository_url OR transfer.commit_sha<>snap.commit_sha
      OR NOT EXISTS (SELECT 1 FROM node_project_capabilities WHERE id=transfer.source_capability_id
                     AND node_id=NEW.node_id AND project_id=task.project_id AND capability='source_acquisition'
                     AND status='ACTIVE' AND policy_version=transfer.policy_version
                     AND constraints->'allowed_origins' ? transfer.origin) THEN
      RAISE EXCEPTION 'placement must preserve the original accepted source and Harness selection';
   END IF;
 END IF;
 RETURN NEW;
END; $$;
"""


ORIGINAL_PLACEMENT = "CREATE OR REPLACE FUNCTION hypertest_guard_connector_placement() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE bound run_execution_bindings%ROWTYPE; node harness_nodes%ROWTYPE;\nBEGIN\n IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'run harness placement is immutable'; END IF;\n SELECT * INTO bound FROM run_execution_bindings WHERE id=NEW.binding_id;\n SELECT * INTO node FROM harness_nodes WHERE id=NEW.node_id;\n IF bound.id IS NULL OR node.id IS NULL OR NEW.test_run_id<>bound.test_run_id OR NEW.mode<>node.node_kind\n    OR bound.harness_host_id<>node.node_key OR node.registration_status<>'ACTIVE' THEN RAISE EXCEPTION 'placement scope does not match binding and node'; END IF;\n IF (NEW.mode='LOCAL_CONNECTOR')<>(NEW.source_transfer_kind='SOURCE_BUNDLE') THEN RAISE EXCEPTION 'placement source mode mismatch'; END IF;\n RETURN NEW;\nEND; $$;"


GUARDS += "\nCREATE OR REPLACE FUNCTION hypertest_guard_connector_dispatch_grant() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE bound run_execution_bindings%ROWTYPE; task durable_jobs%ROWTYPE; placed run_harness_placements%ROWTYPE;\n        device harness_device_grants%ROWTYPE; cap node_project_capabilities%ROWTYPE; projected uuid; expected_claim text;\nBEGIN\n IF TG_OP='DELETE' THEN RAISE EXCEPTION 'dispatch history cannot be deleted'; END IF;\n IF TG_OP='UPDATE' THEN\n  IF (to_jsonb(NEW)-ARRAY['status','row_version']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','row_version']) THEN RAISE EXCEPTION 'dispatch identity and scope are immutable'; END IF;\n  IF OLD.status<>'ACTIVE' OR NEW.status NOT IN ('EXPIRED','REVOKED') THEN RAISE EXCEPTION 'terminal dispatch cannot reactivate'; END IF;\n  RETURN NEW;\n END IF;\n SELECT * INTO bound FROM run_execution_bindings WHERE id=NEW.binding_id;\n SELECT * INTO task FROM durable_jobs WHERE id=NEW.job_id;\n SELECT * INTO placed FROM run_harness_placements WHERE id=NEW.placement_id;\n SELECT * INTO device FROM harness_device_grants WHERE id=NEW.device_grant_id;\n SELECT * INTO cap FROM node_project_capabilities WHERE id=NEW.capability_id;\n SELECT project_id INTO projected FROM test_runs WHERE id=bound.test_run_id;\n expected_claim=encode(sha256(convert_to('hypertest.harness-connector/v1alpha1:'||NEW.node_id::text||':'||task.lease_token::text,'UTF8')),'hex');\n IF bound.id IS NULL OR task.id IS NULL OR placed.id IS NULL OR device.id IS NULL OR cap.id IS NULL\n    OR placed.binding_id<>bound.id OR placed.node_id<>NEW.node_id OR placed.mode<>'LOCAL_CONNECTOR'\n    OR NEW.project_id<>projected OR NEW.session_id<>bound.primary_agent_session_id\n    OR NEW.workspace_id<>replace(bound.workspace_id,'-','') OR NEW.binding_epoch<>bound.binding_epoch\n    OR task.test_run_id<>bound.test_run_id OR task.status<>'RUNNING' OR task.lease_token IS NULL\n    OR task.lease_expires_at<=clock_timestamp() OR bound.status NOT IN ('RESERVED','ACTIVE')\n    OR device.node_id<>NEW.node_id OR device.status<>'ACTIVE' OR device.not_before>clock_timestamp() OR device.expires_at<=clock_timestamp()\n    OR cap.node_id<>NEW.node_id OR cap.project_id<>NEW.project_id OR cap.capability<>'harness' OR cap.status<>'ACTIVE'\n    OR NOT EXISTS (SELECT 1 FROM harness_nodes WHERE id=NEW.node_id AND registration_status='ACTIVE')\n    OR NEW.claim_identity IS DISTINCT FROM expected_claim OR NEW.status<>'ACTIVE'\n    OR NEW.not_before>clock_timestamp()+interval '2 seconds' OR NEW.expires_at<=clock_timestamp()\n    OR NEW.expires_at>least(task.lease_expires_at,device.expires_at,clock_timestamp()+interval '120 seconds')\n    OR NEW.audience<>'hypertest.harness-connector/v1alpha1' OR length(btrim(NEW.call_id))=0\n    OR NEW.operation NOT IN ('create_session','execute','resume','get_call','renew','respond_tool','install_workspace') THEN\n    RAISE EXCEPTION 'dispatch requires current binding claim and explicit project device scope';\n END IF;\n RETURN NEW;\nEND; $$;\nCREATE OR REPLACE FUNCTION hypertest_guard_connector_request() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE dispatched harness_dispatch_grants%ROWTYPE;\nBEGIN\n IF TG_OP='DELETE' THEN RAISE EXCEPTION 'connector request history cannot be deleted'; END IF;\n IF TG_OP='UPDATE' THEN\n  IF (to_jsonb(NEW)-ARRAY['status','result','error_code','connection_generation','sent_at','finished_at']) IS DISTINCT FROM\n     (to_jsonb(OLD)-ARRAY['status','result','error_code','connection_generation','sent_at','finished_at']) THEN RAISE EXCEPTION 'connector request identity and input are immutable'; END IF;\n  IF OLD.status IN ('SUCCEEDED','FAILED','UNKNOWN') THEN RAISE EXCEPTION 'terminal connector request cannot replay'; END IF;\n  IF NOT ((OLD.status='QUEUED' AND NEW.status IN ('SENT','UNKNOWN')) OR\n          (OLD.status='SENT' AND NEW.status IN ('SUCCEEDED','FAILED','UNKNOWN'))) THEN RAISE EXCEPTION 'invalid connector dispatch transition'; END IF;\n  IF OLD.status='SENT' AND (NEW.connection_generation,NEW.sent_at) IS DISTINCT FROM (OLD.connection_generation,OLD.sent_at) THEN RAISE EXCEPTION 'sent delivery identity cannot change'; END IF;\n ELSE\n  IF NEW.status<>'QUEUED' THEN RAISE EXCEPTION 'connector request must start queued'; END IF;\n END IF;\n IF NEW.operation NOT IN ('capabilities','create_session','execute','resume','get_call','renew','respond_tool','restore_session','interrupt','recover','close','prepare_source','source_prepare','install_workspace','issue_create','issue_query')\n    OR NEW.input_sha256 !~ '^[a-f0-9]{64}$' OR jsonb_typeof(NEW.payload)<>'object' OR octet_length(NEW.payload::text)>4000000\n    OR NEW.expires_at>NEW.created_at+interval '121 seconds'\n    OR (NEW.authority='management' AND NEW.operation NOT IN ('capabilities','get_call','restore_session','interrupt','recover','close','issue_query','install_workspace'))\n    OR (NEW.authority='integration' AND NEW.operation NOT IN ('prepare_source','source_prepare','install_workspace','issue_create','issue_query'))\n    OR (NEW.authority='execution' AND NEW.operation NOT IN ('create_session','execute','resume','get_call','renew','respond_tool','install_workspace')) THEN RAISE EXCEPTION 'invalid typed connector request'; END IF;\n IF NEW.authority='execution' THEN\n  SELECT * INTO dispatched FROM harness_dispatch_grants WHERE id=NEW.dispatch_grant_id;\n  IF dispatched.id IS NULL OR dispatched.node_id<>NEW.node_id OR dispatched.operation<>NEW.operation\n     OR NEW.expires_at>dispatched.expires_at OR NEW.payload->'context'->>'binding_id'<>dispatched.binding_id::text\n     OR (NEW.payload->'context'->>'binding_epoch')::bigint<>dispatched.binding_epoch\n     OR NEW.payload->'context'->>'claim_token'<>dispatched.claim_identity THEN RAISE EXCEPTION 'connector execution scope mismatch'; END IF;\n END IF;\n IF NEW.status='SENT' AND (NEW.sent_at IS NULL OR NEW.connection_generation IS NULL) THEN RAISE EXCEPTION 'sent connector request requires consumed delivery'; END IF;\n IF NEW.status IN ('SUCCEEDED','FAILED','UNKNOWN') AND NEW.finished_at IS NULL THEN RAISE EXCEPTION 'terminal connector request requires finish time'; END IF;\n RETURN NEW;\nEND; $$;"
