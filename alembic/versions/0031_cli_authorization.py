"""CLI pairing, independent per-project archive grants and immutable receipts."""
from alembic import op

revision = "0031_cli_authorization"
down_revision = "0030_local_archive"
branch_labels = None
depends_on = None

def upgrade():
    op.drop_constraint("ck_interactive_integration_scopes", "interactive_integration_grants", type_="check")
    op.create_check_constraint("ck_interactive_integration_scopes", "interactive_integration_grants", 'jsonb_typeof(scopes)=\'array\' AND jsonb_array_length(scopes)>0 AND scopes <@ \'["archive:read", "archive:write", "cloud:configure", "cloud:control", "cloud:dispatch", "cloud:read", "credential:manage", "evidence:read", "memory:propose", "memory:publish", "memory:read", "report:read", "run:execute", "run:read", "task:submit", "task:sync"]\'::jsonb')
    op.execute("\nCREATE TABLE cli_authorization_requests (\n\tid UUID NOT NULL, \n\tclient_instance_id UUID NOT NULL, \n\tclient_name VARCHAR(80) NOT NULL, \n\tserver_url VARCHAR(512) NOT NULL, \n\tcreate_key VARCHAR(128) NOT NULL, \n\tcreate_digest VARCHAR(64) NOT NULL, \n\tcredential_hash VARCHAR(64) NOT NULL, \n\tverifier_challenge VARCHAR(64) NOT NULL, \n\trequested_project_id UUID, \n\tshort_code VARCHAR(12) NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tapproval JSONB, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tbound_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_cli_pairing_create_key UNIQUE (client_instance_id, create_key), \n\tCONSTRAINT ck_cli_pairing_status CHECK (status IN ('PENDING','APPROVED','BOUND','DENIED','EXPIRED')), \n\tCONSTRAINT ck_cli_pairing_hashes CHECK (credential_hash ~ '^[a-f0-9]{64}$' AND verifier_challenge ~ '^[a-f0-9]{64}$' AND create_digest ~ '^[a-f0-9]{64}$'), \n\tCONSTRAINT ck_cli_pairing_expiry CHECK (expires_at > created_at), \n\tUNIQUE (credential_hash), \n\tFOREIGN KEY(requested_project_id) REFERENCES projects (id) ON DELETE RESTRICT\n)\n\n")
    op.execute('\nCREATE TABLE cli_authorization_grants (\n\trequest_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tgrant_id UUID NOT NULL, \n\tPRIMARY KEY (request_id, project_id), \n\tFOREIGN KEY(request_id) REFERENCES cli_authorization_requests (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, \n\tUNIQUE (grant_id), \n\tFOREIGN KEY(grant_id) REFERENCES interactive_integration_grants (id) ON DELETE RESTRICT\n)\n\n')
    op.execute("\nCREATE TABLE cli_authorization_receipts (\n\tid UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\toperation VARCHAR(16) NOT NULL, \n\tidempotency_key VARCHAR(128) NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tresponse JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_cli_authorization_receipt UNIQUE (request_id, operation, idempotency_key), \n\tCONSTRAINT ck_cli_authorization_operation CHECK (operation IN ('CREATE','APPROVE','REDEEM','REVOKE')), \n\tFOREIGN KEY(request_id) REFERENCES cli_authorization_requests (id) ON DELETE RESTRICT\n)\n\n")
    op.execute("""
CREATE FUNCTION reject_cli_receipt_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'CLI authorization receipts are immutable'; END;
$$ LANGUAGE plpgsql;
""")
    op.execute("""
CREATE TRIGGER cli_receipt_immutable BEFORE UPDATE OR DELETE ON cli_authorization_receipts
FOR EACH ROW EXECUTE FUNCTION reject_cli_receipt_mutation();
""")

    op.execute("\nCREATE FUNCTION guard_cli_pairing_update() RETURNS trigger AS $$\nBEGIN\n IF TG_OP='DELETE' THEN RAISE EXCEPTION 'CLI pairing history is immutable'; END IF;\n IF (to_jsonb(NEW)-'status'-'approval'-'bound_at') IS DISTINCT FROM\n    (to_jsonb(OLD)-'status'-'approval'-'bound_at') THEN\n   RAISE EXCEPTION 'CLI pairing identity is immutable';\n END IF;\n IF OLD.approval IS NOT NULL AND NEW.approval IS DISTINCT FROM OLD.approval THEN\n   RAISE EXCEPTION 'CLI approval is immutable';\n END IF;\n IF OLD.status IN ('BOUND','DENIED','EXPIRED') AND NEW IS DISTINCT FROM OLD THEN\n   RAISE EXCEPTION 'CLI pairing is terminal';\n END IF;\n IF NEW.status<>OLD.status AND NOT\n   ((OLD.status='PENDING' AND NEW.status IN ('APPROVED','DENIED','EXPIRED')) OR\n    (OLD.status='APPROVED' AND NEW.status IN ('BOUND','DENIED','EXPIRED'))) THEN\n   RAISE EXCEPTION 'CLI pairing transition rejected';\n END IF;\n IF (NEW.status IN ('APPROVED','BOUND') AND NEW.approval IS NULL) OR\n    (NEW.status='BOUND' AND NEW.bound_at IS NULL) OR\n    (NEW.status<>'BOUND' AND NEW.bound_at IS NOT NULL) THEN\n   RAISE EXCEPTION 'CLI approval/binding state mismatch';\n END IF;\n RETURN NEW;\nEND;\n$$ LANGUAGE plpgsql\n")
    op.execute("CREATE TRIGGER cli_pairing_immutable BEFORE UPDATE OR DELETE ON cli_authorization_requests FOR EACH ROW EXECUTE FUNCTION guard_cli_pairing_update()")
    op.execute("CREATE TRIGGER cli_grant_mapping_immutable BEFORE UPDATE OR DELETE ON cli_authorization_grants FOR EACH ROW EXECUTE FUNCTION reject_cli_receipt_mutation()")


def downgrade():
    raise RuntimeError("CLI authorization history must be preserved; destructive downgrade is unsupported")
