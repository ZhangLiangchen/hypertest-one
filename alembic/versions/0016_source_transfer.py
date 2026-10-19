"""ADR-015 immutable acquisition requests, bounded transfer and source receipts."""
import re

import sqlalchemy as sa

from alembic import op

revision = "0016_source_transfer"
down_revision = "0015_connector_nodes"
branch_labels = None
depends_on = None


def upgrade():
    for statement in TABLES:
        op.execute(sa.text(statement))
    op.create_foreign_key("fk_placement_source_transfer", "run_harness_placements", "source_bundle_transfers",
                          ["source_bundle_transfer_id"], ["id"], ondelete="RESTRICT")
    for statement in re.split(r";\s*(?=CREATE (?:FUNCTION|TRIGGER))", GUARDS):
        op.execute(sa.text(statement))


def downgrade():
    for name in ("source_transfer_snapshots", "source_upload_grants", "source_bundle_transfers", "source_acquisition_requests"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {name})")):
            raise RuntimeError("source acquisition history prevents destructive downgrade")
    op.drop_constraint("fk_placement_source_transfer", "run_harness_placements", type_="foreignkey")
    for name in ("source_transfer_snapshots", "source_upload_grants", "source_bundle_transfers", "source_acquisition_requests"):
        op.drop_table(name)
    for name in ("source_request", "source_transfer", "source_upload", "source_snapshot_receipt"):
        op.execute(sa.text(f"DROP FUNCTION hypertest_guard_{name}()"))


GUARDS = r"""
CREATE FUNCTION hypertest_guard_source_request() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'source acquisition request is immutable'; END IF;
 IF NEW.commit_sha !~ '^([a-f0-9]{40}|[a-f0-9]{64})$' OR length(btrim(NEW.origin))=0 OR length(btrim(NEW.policy_version))=0
 THEN RAISE EXCEPTION 'source acquisition requires complete fixed input'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER source_request_guard BEFORE INSERT OR UPDATE OR DELETE ON source_acquisition_requests
 FOR EACH ROW EXECUTE FUNCTION hypertest_guard_source_request();
CREATE FUNCTION hypertest_guard_source_transfer() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE req source_acquisition_requests%ROWTYPE; scope node_project_capabilities%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'source transfer history cannot be deleted'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['status','root_tree','object_format','bundle_sha256','bundle_size','manifest','acquisition_receipt','bundle_path','server_workspace','error_code','accepted_at'])
      IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','root_tree','object_format','bundle_sha256','bundle_size','manifest','acquisition_receipt','bundle_path','server_workspace','error_code','accepted_at'])
  THEN RAISE EXCEPTION 'source transfer identity is immutable'; END IF;
  IF OLD.status IN ('ACCEPTED','REJECTED','EXPIRED') THEN RAISE EXCEPTION 'terminal source transfer is immutable'; END IF;
  IF NOT ((OLD.status='UPLOADING' AND NEW.status IN ('VERIFYING','REJECTED','EXPIRED')) OR
          (OLD.status='VERIFYING' AND NEW.status IN ('ACCEPTED','REJECTED','EXPIRED')))
  THEN RAISE EXCEPTION 'invalid source transfer transition'; END IF;
 ELSIF NEW.status<>'UPLOADING' THEN RAISE EXCEPTION 'source transfer must start uploading'; END IF;
 SELECT * INTO req FROM source_acquisition_requests WHERE id=NEW.request_id;
 IF NOT FOUND OR (req.project_id,req.node_id,req.origin,req.commit_sha,req.ref,req.policy_version) IS DISTINCT FROM
  (NEW.project_id,NEW.node_id,NEW.origin,NEW.commit_sha,NEW.ref,NEW.policy_version)
 THEN RAISE EXCEPTION 'source transfer request ownership mismatch'; END IF;
 SELECT * INTO scope FROM node_project_capabilities WHERE id=NEW.source_capability_id;
 IF NOT FOUND OR scope.node_id<>NEW.node_id OR scope.project_id<>NEW.project_id OR scope.capability<>'source_acquisition'
   OR scope.policy_version<>NEW.policy_version
 THEN RAISE EXCEPTION 'source transfer requires project source-acquisition role'; END IF;
 IF NEW.status='ACCEPTED' AND (NEW.bundle_sha256 !~ '^[a-f0-9]{64}$' OR NEW.bundle_sha256 IS NULL
   OR NEW.root_tree IS NULL OR NEW.root_tree !~ '^([a-f0-9]{40}|[a-f0-9]{64})$'
   OR NEW.object_format NOT IN ('sha1','sha256') OR NEW.object_format IS NULL OR NEW.bundle_size IS NULL
   OR NEW.manifest IS NULL OR NEW.acquisition_receipt IS NULL OR NEW.bundle_path IS NULL
   OR scope.status<>'ACTIVE' OR NOT EXISTS (SELECT 1 FROM harness_nodes WHERE id=NEW.node_id AND registration_status='ACTIVE'))
 THEN RAISE EXCEPTION 'source acceptance requires verified object and active authorization'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER source_transfer_guard BEFORE INSERT OR UPDATE OR DELETE ON source_bundle_transfers
 FOR EACH ROW EXECUTE FUNCTION hypertest_guard_source_transfer();
CREATE FUNCTION hypertest_guard_source_upload() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE transfer source_bundle_transfers%ROWTYPE; device harness_device_grants%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'source upload grant history cannot be deleted'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-'status') IS DISTINCT FROM (to_jsonb(OLD)-'status') OR OLD.status<>'ACTIVE'
    OR NEW.status NOT IN ('CONSUMED','REVOKED','EXPIRED') THEN RAISE EXCEPTION 'source upload grant is immutable'; END IF;
 ELSIF NEW.status<>'ACTIVE' THEN RAISE EXCEPTION 'source upload grant must start active'; END IF;
 SELECT * INTO transfer FROM source_bundle_transfers WHERE id=NEW.transfer_id;
 SELECT * INTO device FROM harness_device_grants WHERE id=NEW.device_grant_id;
 IF device.node_id IS DISTINCT FROM transfer.node_id OR NEW.bundle_sha256 !~ '^[a-f0-9]{64}$'
  OR NEW.receipt->>'transfer_id' IS DISTINCT FROM transfer.id::text
  OR NEW.receipt->>'request_id' IS DISTINCT FROM transfer.request_id::text
  OR NEW.receipt->>'project_id' IS DISTINCT FROM transfer.project_id::text
  OR NEW.receipt->>'node_id' IS DISTINCT FROM transfer.node_id::text
  OR NEW.receipt->>'origin' IS DISTINCT FROM transfer.origin
  OR NEW.receipt->>'commit_sha' IS DISTINCT FROM transfer.commit_sha
  OR NEW.receipt->>'policy_version' IS DISTINCT FROM transfer.policy_version
  OR NEW.receipt->>'bundle_sha256' IS DISTINCT FROM NEW.bundle_sha256
  OR NEW.receipt->>'bundle_size' IS DISTINCT FROM NEW.bundle_size::text
 THEN RAISE EXCEPTION 'source receipt ownership mismatch'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER source_upload_guard BEFORE INSERT OR UPDATE OR DELETE ON source_upload_grants
 FOR EACH ROW EXECUTE FUNCTION hypertest_guard_source_upload();
CREATE FUNCTION hypertest_guard_source_snapshot_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE transfer source_bundle_transfers%ROWTYPE; snap source_snapshots%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'accepted source snapshot link is append-only'; END IF;
 SELECT * INTO transfer FROM source_bundle_transfers WHERE id=NEW.transfer_id;
 SELECT * INTO snap FROM source_snapshots WHERE id=NEW.source_snapshot_id FOR UPDATE;
 IF transfer.status IS DISTINCT FROM 'ACCEPTED' OR (transfer.project_id,transfer.origin,transfer.commit_sha)
   IS DISTINCT FROM (snap.project_id,snap.repository_url,snap.commit_sha)
 THEN RAISE EXCEPTION 'snapshot source transfer mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM source_transfer_snapshots r JOIN source_bundle_transfers t ON t.id=r.transfer_id
   WHERE r.source_snapshot_id=NEW.source_snapshot_id AND t.bundle_sha256<>transfer.bundle_sha256)
 THEN RAISE EXCEPTION 'snapshot accepted source content cannot change'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER source_snapshot_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON source_transfer_snapshots
 FOR EACH ROW EXECUTE FUNCTION hypertest_guard_source_snapshot_receipt();
"""


# Frozen migration DDL: future ORM changes must not rewrite this schema history.
TABLES = (
    'CREATE TABLE source_acquisition_requests (\n\tid UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tnode_id UUID NOT NULL, \n\torigin TEXT NOT NULL, \n\tcommit_sha VARCHAR(64) NOT NULL, \n\tref VARCHAR(255), \n\tpolicy_version VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(node_id) REFERENCES harness_nodes (id) ON DELETE RESTRICT\n)',
    "CREATE TABLE source_bundle_transfers (\n\tid UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\tnode_id UUID NOT NULL, \n\tsource_capability_id UUID NOT NULL, \n\tidempotency_key VARCHAR(255) NOT NULL, \n\torigin TEXT NOT NULL, \n\tcommit_sha VARCHAR(64) NOT NULL, \n\tref VARCHAR(255), \n\tpolicy_version VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\troot_tree VARCHAR(64), \n\tobject_format VARCHAR(8), \n\tbundle_sha256 VARCHAR(64), \n\tbundle_size BIGINT, \n\tmanifest JSONB, \n\tacquisition_receipt JSONB, \n\tbundle_path TEXT, \n\tserver_workspace TEXT, \n\terror_code VARCHAR(64), \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\taccepted_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_source_transfer_idempotency UNIQUE (project_id, idempotency_key), \n\tCONSTRAINT ck_source_transfer_status CHECK (status IN ('UPLOADING','VERIFYING','ACCEPTED','REJECTED','EXPIRED')), \n\tCONSTRAINT ck_source_transfer_size CHECK (bundle_size IS NULL OR bundle_size BETWEEN 1 AND 50331648), \n\tCONSTRAINT ck_source_transfer_acceptance CHECK ((status='ACCEPTED') = (server_workspace IS NOT NULL AND accepted_at IS NOT NULL)), \n\tFOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(request_id) REFERENCES source_acquisition_requests (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(node_id) REFERENCES harness_nodes (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(source_capability_id) REFERENCES node_project_capabilities (id) ON DELETE RESTRICT\n)",
    "CREATE TABLE source_upload_grants (\n\tid UUID NOT NULL, \n\ttransfer_id UUID NOT NULL, \n\tdevice_grant_id UUID NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\tbundle_sha256 VARCHAR(64) NOT NULL, \n\tbundle_size BIGINT NOT NULL, \n\treceipt JSONB NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_source_upload_status CHECK (status IN ('ACTIVE','CONSUMED','REVOKED','EXPIRED')), \n\tCONSTRAINT ck_source_upload_bounds CHECK (bundle_size BETWEEN 1 AND 50331648 AND expires_at>created_at), \n\tUNIQUE (transfer_id), \n\tFOREIGN KEY(transfer_id) REFERENCES source_bundle_transfers (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(device_grant_id) REFERENCES harness_device_grants (id) ON DELETE RESTRICT, \n\tUNIQUE (token_hash)\n)",
    'CREATE TABLE source_transfer_snapshots (\n\ttransfer_id UUID NOT NULL, \n\tsource_snapshot_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (transfer_id, source_snapshot_id), \n\tFOREIGN KEY(transfer_id) REFERENCES source_bundle_transfers (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(source_snapshot_id) REFERENCES source_snapshots (id) ON DELETE RESTRICT\n)',
)
