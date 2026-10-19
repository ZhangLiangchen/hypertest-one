"""PostgreSQL + local journal integration; HTTP stays explicitly injected."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_gitlab_integration import arguments, bound_run, issue_context, tools  # noqa: F401
from test_local_issue_adapter import HTTP

from hypertest.application.gitlab import reconcile_managed_issue, request_issue
from hypertest.application.services import ConflictError
from hypertest.common.ids import uuid7
from hypertest.connector.issues import LocalGitLabProject, LocalIssueAdapter
from hypertest.connector.protocol import digest
from hypertest.connector.security import token_hash, validate_issue_request
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.bindings import RunExecutionBinding
from hypertest.domain.connector import (
    ConnectorRequest,
    HarnessDeviceGrant,
    HarnessNode,
    NodeProjectCapability,
)
from hypertest.domain.issue_executor import GitLabIssueOperationExecutor
from hypertest.domain.jobs import DurableJob, JobStatus
from hypertest.domain.models import AuditEvent, Finding, utcnow
from hypertest.harness_bridge.protocol import BridgeError


@pytest.fixture
async def local_issue_context(issue_context, tmp_path, monkeypatch):  # noqa: F811
    context = issue_context
    async with AsyncSessionLocal() as db:
        node = HarnessNode(node_key="local-issue-" + uuid7().hex, owner_identity_id="test-operator", display_name="Test Mac")
        db.add(node)
        await db.flush()
        now = await db.scalar(select(func.clock_timestamp()))
        grant = HarnessDeviceGrant(node_id=node.id, token_hash=token_hash(uuid7().hex), key_version="test-v1",
            operator_identity_id="test-operator", not_before=now, expires_at=now + timedelta(hours=1))
        scope = {"integration_id": "work", "base_url": "https://gitlab.example.test", "gitlab_project_id": 42, "assignee_ids": [7]}
        capability = NodeProjectCapability(node_id=node.id, project_id=context["project_id"], capability="issue_executor",
            constraints=scope, operator_identity_id="test-operator")
        db.add_all([grant, capability])
        await db.commit()
        context.update(node_id=node.id, capability_id=capability.id, device_grant_id=grant.id)
    project_policy = context["policy"]["projects"][str(context["project_id"])]
    project_policy.pop("token_file")
    project_policy.update(executor_mode="LOCAL_CONNECTOR", executor_node_id=str(context["node_id"]), integration_id="work")
    context["policy_path"].write_text(json.dumps(context["policy"]))
    monkeypatch.setenv("GITLAB_TOKEN", "LOCAL-SECRET-NEVER-RELAY")
    transport = HTTP()
    integration = LocalGitLabProject(base_url="https://gitlab.example.test", gitlab_project_id=42,
        assignee_ids=[7], credential_kind="environment")
    adapter = LocalIssueAdapter(tmp_path / "local-issue.sqlite", {"work": integration},
        node_id=str(context["node_id"]), transport=transport)
    context.update(adapter=adapter, http=transport)
    return context


class LocalBridge:
    """Typed dispatch in process, with the same authenticated receipt shape."""
    def __init__(self, context, db, *, lose_ack=False, forged=False):
        self.context, self.db, self.lose_ack, self.forged = context, db, lose_ack, forged
        self.calls = []

    async def request(self, operation, payload, *, management=False):
        assert not self.db.in_transaction(), "network I/O must not hold aggregate locks"
        assert "token_file" not in json.dumps(payload) and "LOCAL-SECRET" not in json.dumps(payload)
        self.calls.append(operation)
        if operation == "issue_create":
            assert not management
            result = await self.context["adapter"].create(payload, {"create_once": True})
            if self.lose_ack:
                raise TimeoutError("simulated ACK loss")
            if self.forged:
                result = {**result, "issue": {**result["issue"], "project_id": 999}}
            return result
        assert operation == "issue_query" and management
        return await self.context["adapter"].query(payload, {})


async def test_local_policy_needs_no_server_credential_and_fixes_executor(local_issue_context, monkeypatch):
    context = local_issue_context
    monkeypatch.setattr("hypertest.application.gitlab._token", lambda _: pytest.fail("server must never load local credential"))
    async with AsyncSessionLocal() as db:
        bridge = LocalBridge(context, db)
        result = await request_issue(tools(db, context), arguments(context), bridge=bridge)
        assert result["status"] == "SUCCEEDED" and result["issue_iid"] == 9
        executor = await db.scalar(select(GitLabIssueOperationExecutor).where(GitLabIssueOperationExecutor.operation_id == result["operation_id"]))
        assert executor.executor_mode == "LOCAL_CONNECTOR" and executor.executor_node_id == context["node_id"]
        assert "LOCAL-SECRET" not in json.dumps(executor.delegation)
        again = await request_issue(tools(db, context), arguments(context, idempotency_key="another-key"), bridge=bridge)
        assert again == result and bridge.calls == ["issue_create"]
        finding = await db.get(Finding, context["finding_id"])
        assert finding.external_issue_ref == result["issue_url"]


async def test_lost_ack_reconciles_on_same_local_executor_even_if_policy_changes(local_issue_context):
    context = local_issue_context
    async with AsyncSessionLocal() as db:
        bridge = LocalBridge(context, db, lose_ack=True)
        original = await request_issue(tools(db, context), arguments(context), bridge=bridge)
        assert original["status"] == "UNKNOWN"
        project_policy = context["policy"]["projects"][str(context["project_id"]) ]
        project_policy.update(executor_mode="SERVER_HOST", executor_node_id=None, token_file=str(context["token_path"]))
        context["policy_path"].write_text(json.dumps(context["policy"]))
        result = await request_issue(tools(db, context), arguments(context), bridge=bridge)
        assert result["status"] == "SUCCEEDED" and result["operation_id"] == original["operation_id"]
        assert bridge.calls == ["issue_create", "issue_query"] and len(context["http"].calls) == 1


async def test_platform_checks_authenticated_receipt_project_and_original_digest(local_issue_context):
    async with AsyncSessionLocal() as db:
        bridge = LocalBridge(local_issue_context, db, forged=True)
        result = await request_issue(tools(db, local_issue_context), arguments(local_issue_context), bridge=bridge)
        assert result["status"] == "UNKNOWN" and result["issue_url"] is None
        finding = await db.get(Finding, local_issue_context["finding_id"])
        assert finding.external_issue_ref is None


async def test_ungranted_project_scope_blocks_before_intent_or_post(local_issue_context):
    context = local_issue_context
    async with AsyncSessionLocal() as db:
        scope = await db.get(NodeProjectCapability, context["capability_id"])
        scope.constraints = {**scope.constraints, "assignee_ids": [8]}
        # Scope immutable by design; create a mismatching configured policy instead.
        await db.rollback()
        policy = context["policy"]["projects"][str(context["project_id"])]
        policy["assignees"] = {"responsible-developer": 8}
        context["policy_path"].write_text(json.dumps(context["policy"]))
        with pytest.raises(ConflictError, match="scope"):
            await request_issue(tools(db, context), arguments(context), bridge=LocalBridge(context, db))
        assert not context["http"].calls


async def test_executor_history_is_database_append_only(local_issue_context):
    async with AsyncSessionLocal() as db:
        result = await request_issue(tools(db, local_issue_context), arguments(local_issue_context), bridge=LocalBridge(local_issue_context, db))
        for sql in ("UPDATE gitlab_issue_operation_executors SET integration_id='replacement' WHERE operation_id=:id",
                    "DELETE FROM gitlab_issue_operation_executors WHERE operation_id=:id"):
            with pytest.raises(DBAPIError, match="append-only"):
                await db.execute(text(sql), {"id": result["operation_id"]})
            await db.rollback()


async def test_cancelled_run_can_only_reconcile_original_history(local_issue_context):
    context = local_issue_context
    async with AsyncSessionLocal() as db:
        bridge = LocalBridge(context, db, lose_ack=True)
        result = await request_issue(tools(db, context), arguments(context), bridge=bridge)
        assert result["status"] == "UNKNOWN"
        job = await db.get(DurableJob, context["job_id"])
        job.status, job.finished_at, job.lease_expires_at = JobStatus.CANCELLED, utcnow(), None
        await db.commit()
        before = await db.get(RunExecutionBinding, context["binding_id"])
        epoch, status = before.binding_epoch, before.status
        reconciled = await reconcile_managed_issue(db, result["operation_id"], actor="test-operator", bridge=bridge)
        assert reconciled["status"] == "SUCCEEDED"
        await db.refresh(job)
        await db.refresh(before)
        assert job.status is JobStatus.CANCELLED and before.binding_epoch == epoch and before.status == status
        finding = await db.get(Finding, context["finding_id"])
        assert finding.external_issue_ref is None
        event = await db.scalar(select(AuditEvent).where(AuditEvent.entity_id == result["operation_id"], AuditEvent.action == "gitlab.issue_reconciled"))
        assert event.after_state["history_only"] is True
        assert bridge.calls == ["issue_create", "issue_query"] and len(context["http"].calls) == 1


async def test_revocation_only_permits_exact_original_query_and_never_another_create(local_issue_context):
    context = local_issue_context
    async with AsyncSessionLocal() as db:
        result = await request_issue(tools(db, context), arguments(context), bridge=LocalBridge(context, db, lose_ack=True))
        executor = await db.scalar(select(GitLabIssueOperationExecutor).where(GitLabIssueOperationExecutor.operation_id == result["operation_id"]))
        payload = {**executor.delegation, "delegation_sha256": executor.delegation_sha256,
            "expires_at": (utcnow() + timedelta(seconds=20)).isoformat()}
        device = await db.get(HarnessDeviceGrant, context["device_grant_id"])
        capability = await db.get(NodeProjectCapability, context["capability_id"])
        device.status, device.revoked_at = "REVOKED", utcnow()
        capability.status, capability.revoked_at = "REVOKED", utcnow()
        await db.commit()
        await validate_issue_request(db, context["node_id"], payload, create=False, now=utcnow())
        with pytest.raises(BridgeError):
            await validate_issue_request(db, context["node_id"], payload, create=True, now=utcnow())
        for field, value in (("operation_id", str(uuid7())), ("assignee_id", 8), ("project_id", str(uuid7())), ("delegation_sha256", "0" * 64)):
            with pytest.raises(BridgeError, match="ISSUE_DELEGATION_REJECTED"):
                await validate_issue_request(db, context["node_id"], {**payload, field: value}, create=False, now=utcnow())


async def test_database_consumes_one_create_delivery_for_entire_operation_history(local_issue_context):
    context = local_issue_context
    async with AsyncSessionLocal() as db:
        result = await request_issue(tools(db, context), arguments(context), bridge=LocalBridge(context, db, lose_ack=True))
        executor = await db.scalar(select(GitLabIssueOperationExecutor).where(GitLabIssueOperationExecutor.operation_id == result["operation_id"]))
        payload = {**executor.delegation, "delegation_sha256": executor.delegation_sha256,
            "expires_at": (utcnow() + timedelta(seconds=20)).isoformat()}
        request = ConnectorRequest(node_id=context["node_id"], operation="issue_create", authority="integration",
            payload=payload, input_sha256=digest(payload), expires_at=utcnow() + timedelta(seconds=20))
        db.add(request)
        await db.commit()
        request.status, request.finished_at = "UNKNOWN", utcnow()
        await db.commit()
        db.add(ConnectorRequest(node_id=context["node_id"], operation="issue_create", authority="integration",
            payload=payload, input_sha256=digest(payload), expires_at=utcnow() + timedelta(seconds=20)))
        with pytest.raises(DBAPIError, match="uq_issue_create_delivery"):
            await db.commit()
        await db.rollback()
