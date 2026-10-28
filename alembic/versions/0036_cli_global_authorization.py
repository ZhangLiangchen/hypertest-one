"""Allow non-expiring CLI grants and record whole-binding revocations."""
from alembic import op

revision = "0036_cli_global_authorization"
down_revision = "0035_retire_legacy_test_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE interactive_integration_grants ALTER COLUMN expires_at DROP NOT NULL")
    op.execute("ALTER TABLE interactive_integration_grants DROP CONSTRAINT ck_interactive_integration_validity")
    op.execute("""ALTER TABLE interactive_integration_grants ADD CONSTRAINT ck_interactive_integration_validity
        CHECK (token_hash ~ '^[a-f0-9]{64}$' AND row_version > 0 AND
          ((expires_at IS NOT NULL AND expires_at > not_before) OR
           (expires_at IS NULL AND policy_version IN ('cli-archive-v1','cli-archive-global-v1') AND scopes <@ '["archive:read","archive:write"]'::jsonb)))""")
    op.execute("""CREATE TABLE cli_authorization_revocations (
        request_id UUID PRIMARY KEY REFERENCES cli_authorization_requests(id) ON DELETE RESTRICT,
        revoked_at TIMESTAMP WITH TIME ZONE NOT NULL, revoked_by VARCHAR(128) NOT NULL)""")
    op.execute("""CREATE TRIGGER cli_revocation_immutable BEFORE UPDATE OR DELETE ON cli_authorization_revocations
        FOR EACH ROW EXECUTE FUNCTION reject_cli_receipt_mutation()""")
    op.execute("""CREATE TABLE cli_authorization_global_upgrades (
        request_id UUID PRIMARY KEY REFERENCES cli_authorization_requests(id) ON DELETE RESTRICT,
        actor_identity_id UUID NOT NULL REFERENCES interactive_actor_identities(id) ON DELETE RESTRICT,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL)""")
    op.execute("""CREATE TABLE cli_authorization_global_grants (
        request_id UUID NOT NULL REFERENCES cli_authorization_requests(id) ON DELETE RESTRICT,
        project_id UUID NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
        grant_id UUID NOT NULL UNIQUE REFERENCES interactive_integration_grants(id) ON DELETE RESTRICT,
        PRIMARY KEY (request_id, project_id))""")
    op.execute("""CREATE TRIGGER cli_global_upgrade_immutable BEFORE UPDATE OR DELETE ON cli_authorization_global_upgrades
        FOR EACH ROW EXECUTE FUNCTION reject_cli_receipt_mutation()""")
    op.execute("""CREATE TRIGGER cli_global_grant_immutable BEFORE UPDATE OR DELETE ON cli_authorization_global_grants
        FOR EACH ROW EXECUTE FUNCTION reject_cli_receipt_mutation()""")
    op.execute("""INSERT INTO cli_authorization_global_upgrades (request_id, actor_identity_id, created_at)
        SELECT DISTINCT r.id, g.actor_identity_id, clock_timestamp()
        FROM cli_authorization_requests r
        JOIN cli_authorization_grants m ON m.request_id = r.id
        JOIN interactive_integration_grants g ON g.id = m.grant_id
        JOIN interactive_actor_identities a ON a.id = g.actor_identity_id
        JOIN interactive_client_registrations c ON c.actor_identity_id = g.actor_identity_id
            AND c.client_instance_id = g.client_instance_id
        WHERE r.status = 'BOUND' AND g.status IN ('ACTIVE', 'EXPIRED')
          AND a.status = 'ACTIVE' AND c.status = 'ACTIVE'
          AND g.client_instance_id = r.client_instance_id
          AND g.actor_identity_id::text = r.approval->>'actor_identity_id'
        GROUP BY r.id, g.actor_identity_id""")


def downgrade():
    raise RuntimeError("CLI authorization history must be preserved")
