"""Real PostgreSQL guarantees for ADR-016 identity, acceptance and attachment."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from test_connector_constraints import paired_device  # noqa: F401
from test_connector_constraints import scoped_binding as _scoped_binding

from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.api.schemas import ProjectCreate
from hypertest.api.schemas import TestRunCreate as RunCreate
from hypertest.application.bootstrap import bootstrap_run, prepare_bootstrap_inputs
from hypertest.application.jobs import cancel_job, claim_job, submit_job
from hypertest.application.services import create_project, create_test_run
from hypertest.common.ids import public_key, uuid7
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.bindings import BindingStatus, RunExecutionBinding
from hypertest.domain.connector import RunHarnessPlacement
from hypertest.domain.enums import AgentSessionStatus
from hypertest.domain.harness_selection import RunHarnessSelection, create_execution_selection
from hypertest.domain.interactive import (
    InteractiveActorIdentity,
    InteractiveClientRegistration,
    InteractiveExecutionBinding,
    InteractiveExecutionGrant,
    InteractiveIntegrationGrant,
    InteractiveSubmissionReceipt,
    interactive_claim_identity,
)
from hypertest.domain.jobs import DurableJob, JobStatus, JobType
from hypertest.domain.models import AgentSessionRecord, AuditEvent
from hypertest.domain.models import TestRun as CanonicalRun

interactive_source = _scoped_binding


async def registration(db, project_id, *, scopes=None):
    actor = InteractiveActorIdentity(actor_ref="actor-" + uuid4().hex, registered_by="test-operator")
    db.add(actor)
    await db.flush()
    client_id = uuid7()
    db.add(InteractiveClientRegistration(actor_identity_id=actor.id, client_instance_id=client_id, registered_by="test-operator"))
    await db.flush()
    grant = InteractiveIntegrationGrant(actor_identity_id=actor.id, client_instance_id=client_id,
        project_id=project_id, scopes=scopes or ["task:submit", "run:execute"],
        token_hash=uuid4().hex + uuid4().hex, registered_by="test-operator",
        not_before=await db.scalar(select(func.clock_timestamp())),
        expires_at=datetime.now(UTC) + timedelta(hours=1))
    db.add(grant)
    await db.flush()
    return actor, client_id, grant


async def project(db):
    return await create_project(db, ProjectCreate(key=public_key("I16"), name="Interactive guarantees"))


def bootstrap_payload():
    return RunBootstrap(repository_url="https://github.com/example/interactive",
        commit_sha="a" * 40, prd_text="Preserve quantity and reject negative quantities.",
        idempotency_key=uuid4().hex)


async def test_atomic_bootstrap_and_first_job_do_not_commit_callers_transaction():
    async with AsyncSessionLocal() as db:
        p = await project(db)
        payload = bootstrap_payload()
        prepared = await prepare_bootstrap_inputs(db, p.id, payload)
        run = await bootstrap_run(db, p.id, payload, commit=False, prepared=prepared)
        run_id = run.id
        await create_execution_selection(db, run.id, execution_mode="CLOUD", execution_driver="PLATFORM_MANAGED")
        job = await submit_job(db, run.id, JobType.ADVANCE_RUN,
            payload={"prepare_workspace": True, "execution_profile": "run-persistent-harness/v1"},
            idempotency_key="initial", commit=False)
        job_id = job.id
        async with AsyncSessionLocal() as other:
            assert await other.get(CanonicalRun, run_id) is None
            assert await other.get(DurableJob, job_id) is None
        await db.rollback()
        assert await db.get(CanonicalRun, run_id) is None
        assert await db.get(DurableJob, job_id) is None
        assert await db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.test_run_id == run_id)) == 0


async def test_registered_identity_scopes_and_grant_rotation_cannot_rewrite_authority():
    async with AsyncSessionLocal() as db:
        p = await project(db)
        actor, client, grant = await registration(db, p.id)
        await db.commit()
        grant_id, actor_id, project_id = grant.id, actor.id, p.id
        grant.scopes = ["operator:all"]
        with pytest.raises(DBAPIError, match="authorization are immutable"):
            await db.commit()
        await db.rollback()
        grant = await db.get(InteractiveIntegrationGrant, grant_id)
        grant.status, grant.revoked_at, grant.row_version = "REVOKED", datetime.now(UTC), 2
        await db.commit()
        grant.status, grant.row_version = "ACTIVE", 3
        with pytest.raises(DBAPIError, match="cannot reactivate"):
            await db.commit()
        await db.rollback()
        grant = await db.get(InteractiveIntegrationGrant, grant_id)
        await db.delete(grant)
        with pytest.raises(DBAPIError, match="history cannot be deleted"):
            await db.commit()
        await db.rollback()
        db.add(InteractiveIntegrationGrant(actor_identity_id=actor_id, client_instance_id=client,
            project_id=project_id, scopes=["operator:all"], token_hash=uuid4().hex + uuid4().hex,
            registered_by="test-operator", expires_at=datetime.now(UTC) + timedelta(hours=1)))
        with pytest.raises(DBAPIError, match="integration_scopes"):
            await db.commit()
        await db.rollback()


async def test_accepted_receipt_requires_its_run_initial_job_and_retains_idempotency():
    async with AsyncSessionLocal() as db:
        p = await project(db)
        actor, client_id, grant = await registration(db, p.id)
        await db.commit()
        actor_id, grant_id, project_id = actor.id, grant.id, p.id
        payload = bootstrap_payload()
        prepared = await prepare_bootstrap_inputs(db, p.id, payload)
        run = await bootstrap_run(db, p.id, payload, commit=False, prepared=prepared)
        await create_execution_selection(db, run.id, execution_mode="CLOUD", execution_driver="PLATFORM_MANAGED")
        job = await submit_job(db, run.id, JobType.ADVANCE_RUN, payload={"prepare_workspace": True},
            idempotency_key="initial", commit=False)
        receipt = InteractiveSubmissionReceipt(grant_id=grant.id, actor_identity_id=actor.id,
            client_instance_id=client_id, project_id=p.id, submission_key="durable-intent",
            input_digest="a" * 64, status="ACCEPTED", test_run_id=run.id, initial_durable_job_id=job.id)
        db.add(receipt)
        await db.commit()
        receipt_id, job_id = receipt.id, job.id
        # The receipt retains the initial Job identity even after cancellation;
        # leave no globally claimable work if a later constraint assertion fails.
        await cancel_job(db, job_id)
        receipt.input_digest = "b" * 64
        with pytest.raises(DBAPIError, match="append-only"):
            await db.commit()
        await db.rollback()
        # A rotated credential keeps the same actor/client/key namespace.
        original = await db.get(InteractiveIntegrationGrant, grant_id)
        rotated = InteractiveIntegrationGrant(actor_identity_id=actor_id, client_instance_id=client_id,
            project_id=project_id, scopes=original.scopes, token_hash=uuid4().hex + uuid4().hex,
            registered_by="test-operator", not_before=await db.scalar(select(func.clock_timestamp())),
            expires_at=datetime.now(UTC) + timedelta(hours=1))
        db.add(rotated)
        await db.commit()
        db.add(InteractiveSubmissionReceipt(grant_id=rotated.id, actor_identity_id=actor_id,
            client_instance_id=client_id, project_id=project_id, submission_key="durable-intent",
            input_digest="b" * 64, status="REJECTED", error_code="REJECTED"))
        with pytest.raises(DBAPIError, match="uq_interactive_submission_key"):
            await db.commit()
        await db.rollback()
        assert (await db.get(InteractiveSubmissionReceipt, receipt_id)).input_digest == "a" * 64


@pytest.fixture
async def interactive_owner(interactive_source):
    """Source fixture tests relational scope, not a new source-content attestation."""
    fixture = interactive_source
    async with AsyncSessionLocal() as db:
        original = await db.get(CanonicalRun, fixture["run_id"])
        run = await create_test_run(db, RunCreate(project_id=original.project_id,
            source_snapshot_id=original.source_snapshot_id, policy_snapshot_id=original.policy_snapshot_id))
        actor, client, grant = await registration(db, run.project_id)
        db.add(RunHarnessSelection(test_run_id=run.id, mode="LOCAL_CONNECTOR",
            node_id=fixture["node_id"], source_bundle_transfer_id=fixture["transfer_id"]))
        await db.flush()
        await create_execution_selection(db, run.id, execution_mode="LOCAL", execution_driver="INTERACTIVE_MCP",
            node_id=fixture["node_id"], source_bundle_transfer_id=fixture["transfer_id"])
        job = await submit_job(db, run.id, JobType.ADVANCE_RUN,
            payload={"workspace": ".", "execution_profile": "run-persistent-harness/v1"}, idempotency_key="initial")
        run_id, job_id, actor_id, grant_id = run.id, job.id, actor.id, grant.id
        assert await claim_job(db, "not-an-interactive-owner", run_id=run_id) is None
        await db.refresh(run)
        native, workspace = "current-native-" + uuid4().hex, uuid4().hex
        agent = AgentSessionRecord(test_run_id=run.id, provider="fixture", harness="interactive",
            provider_session_id=native, workspace_id=workspace, status=AgentSessionStatus.CREATED)
        db.add(agent)
        await db.flush()
        bound = RunExecutionBinding(test_run_id=run.id, logical_worker_id=uuid7(),
            primary_agent_session_id=agent.id, harness_host_id=fixture["context"].harness_host_id,
            workspace_id=workspace, status=BindingStatus.RESERVED)
        db.add(bound)
        await db.flush()
        db.add(RunHarnessPlacement(test_run_id=run.id, binding_id=bound.id, node_id=fixture["node_id"],
            mode="LOCAL_CONNECTOR", source_transfer_kind="SOURCE_BUNDLE", source_bundle_transfer_id=fixture["transfer_id"]))
        await db.flush()
        attachment = InteractiveExecutionBinding(binding_id=bound.id, agent_session_id=agent.id, test_run_id=run.id,
            grant_id=grant_id, actor_identity_id=actor_id, client_instance_id=client, node_id=fixture["node_id"],
            provider="fixture", native_session_id=native, workspace_id=workspace, attach_key="attach-original",
            input_digest="a" * 64, attached_epoch=1, host_attachment_id="host-" + uuid4().hex, host_proof_sha256="b" * 64)
        db.add(attachment)
        await db.commit()
        claimed = await claim_job(db, "platform-coordinator", run_id=run_id)
        assert claimed is not None and claimed.id == job_id
        assert claimed.status is JobStatus.RUNNING
        value = {"run_id": run_id, "job_id": job_id, "actor_id": actor_id, "client_id": client, "grant_id": grant_id,
            "attachment_id": attachment.id, "agent_id": agent.id, "binding_id": bound.id,
            "workspace": workspace, "native": native, "claim": claimed.lease_token,
            "device_grant_id": fixture["device_grant_id"],
            "host_attachment_id": attachment.host_attachment_id}
    try:
        yield value
    finally:
        async with AsyncSessionLocal() as db:
            job = await db.get(DurableJob, value["job_id"])
            if job.status in {JobStatus.RUNNING, JobStatus.QUEUED, JobStatus.WAITING_INPUT, JobStatus.CANCEL_REQUESTED}:
                job.status, job.finished_at, job.lease_expires_at = JobStatus.FAILED, datetime.now(UTC), None
                await db.commit()


async def test_interactive_job_waits_for_real_structural_attach_without_claim_cycle(interactive_owner):
    value = interactive_owner
    async with AsyncSessionLocal() as db:
        attachment_id, job_id, grant_id = value["attachment_id"], value["job_id"], value["grant_id"]
        attachment = await db.get(InteractiveExecutionBinding, attachment_id)
        claimed = await db.get(DurableJob, job_id)
        attachment_id = attachment.id
        grant_values = dict(interactive_binding_id=attachment.id, job_id=claimed.id,
            integration_grant_id=grant_id, binding_epoch=1,
            device_grant_id=value["device_grant_id"],
            call_id="current-attachment-call", host_attachment_id=attachment.host_attachment_id,
            host_proof_sha256="b" * 64, expires_at=datetime.now(UTC) + timedelta(seconds=10))
        expected_claim = interactive_claim_identity(attachment.id, claimed.lease_token)
        db.add(InteractiveExecutionGrant(**grant_values, token_hash=uuid4().hex + uuid4().hex,
            claim_identity="forged-claim"))
        with pytest.raises(DBAPIError, match="current run claim"):
            await db.commit()
        await db.rollback()
        short = InteractiveExecutionGrant(**grant_values, token_hash=uuid4().hex + uuid4().hex,
            claim_identity=expected_claim)
        db.add(short)
        await db.commit()
        short_id = short.id
        short.token_hash = uuid4().hex + uuid4().hex
        with pytest.raises(DBAPIError, match="authorization are immutable"):
            await db.commit()
        await db.rollback()
        assert (await db.get(InteractiveExecutionGrant, short_id)).claim_identity == expected_claim
        claimed = await db.get(DurableJob, job_id)
        claimed.status, claimed.finished_at, claimed.lease_expires_at = JobStatus.FAILED, datetime.now(UTC), None
        await db.commit()
        attachment = await db.get(InteractiveExecutionBinding, attachment_id)
        attachment.native_session_id = "fake-replacement"
        with pytest.raises(DBAPIError, match="append-only"):
            await db.commit()
        await db.rollback()


@pytest.mark.parametrize("live_runner", [False, True])
async def test_interactive_cleanup_revokes_only_platform_authority_and_preserves_native_workspace(
    interactive_owner, monkeypatch, tmp_path, live_runner,
):
    from unittest.mock import AsyncMock

    from hypertest.application.jobs import cleanup_job_resources
    from hypertest.domain.enums import ExecutionOutcome, ExecutionStatus
    from hypertest.domain.models import TestExecution

    value = interactive_owner
    user_workspace = tmp_path / "personal-checkout"
    user_workspace.mkdir()
    marker = user_workspace / "unrelated-personal-file"
    marker.write_text("keep this work")
    bridge_cleanup = AsyncMock(side_effect=AssertionError("interactive cleanup must never send Bridge commands"))
    monkeypatch.setattr("hypertest.application.persistent.cleanup_bound_call", bridge_cleanup)
    workspace_cleanup = AsyncMock(side_effect=AssertionError("interactive cleanup must never delete the native workspace"))
    monkeypatch.setattr("hypertest.agent.snapshot.cleanup_managed_agent_workspace", workspace_cleanup)
    docker_cleanup = AsyncMock(return_value={"docker_available": True, "containers_removed": 1})
    monkeypatch.setattr("hypertest.runner.backends.cleanup_docker_job_resources", docker_cleanup)
    async with AsyncSessionLocal() as db:
        short = InteractiveExecutionGrant(interactive_binding_id=value["attachment_id"], job_id=value["job_id"],
            integration_grant_id=value["grant_id"], token_hash=uuid4().hex + uuid4().hex,
            device_grant_id=value["device_grant_id"],
            binding_epoch=1, call_id="cleanup-test", host_attachment_id=value["host_attachment_id"],
            host_proof_sha256="b" * 64, claim_identity=interactive_claim_identity(value["attachment_id"], value["claim"]),
            expires_at=datetime.now(UTC) + timedelta(seconds=10))
        db.add(short)
        await db.commit()
        short_id = short.id
        job = await db.get(DurableJob, value["job_id"])
        execution = None
        if live_runner:
            # Relational pending-execution fixture: no Runner facts or Evidence
            # are fabricated. Cleanup must leave this accepted ownership intact.
            execution = TestExecution(key=public_key("EX"), test_run_id=value["run_id"],
                durable_job_id=job.id, idempotency_key=uuid4().hex, runner_backend="scope-fixture",
                environment_id="scope-fixture", environment_fingerprint="a" * 64,
                source_commit="b" * 40, execution_spec_sha256="c" * 64, spec={})
            db.add(execution)
        else:
            job.status, job.finished_at, job.lease_expires_at = JobStatus.FAILED, datetime.now(UTC), None
        await db.commit()
        result = await cleanup_job_resources(db, job, on_worker=True)
        assert result["interactive_grants_revoked"] == 1
        assert result["bridge"] == "not_applicable"
        assert result["agent_workspaces_removed"] == 0
        assert result["runner_resources"] == ("deferred_active_execution" if live_runner else "cleanup_attempted")
        await db.refresh(short)
        assert short.status == "REVOKED"
        agent = await db.get(AgentSessionRecord, value["agent_id"])
        binding = await db.get(RunExecutionBinding, value["binding_id"])
        assert agent.provider_session_id == value["native"]
        assert agent.status is AgentSessionStatus.CREATED
        assert binding.workspace_id == value["workspace"] and binding.binding_epoch == 1
        assert await db.get(InteractiveExecutionBinding, value["attachment_id"]) is not None
        assert (await db.get(InteractiveExecutionGrant, short_id)).status == "REVOKED"
        assert await db.scalar(select(AuditEvent.id).where(
            AuditEvent.entity_id == value["job_id"], AuditEvent.action == "job.interactive_authority_revoked"))
        if execution is not None:
            await db.refresh(execution)
            assert execution.status is ExecutionStatus.QUEUED
            assert job.status is JobStatus.RUNNING and job.lease_token == value["claim"]
            execution.status, execution.outcome, execution.finished_at = ExecutionStatus.ERROR, ExecutionOutcome.INCONCLUSIVE, datetime.now(UTC)
            await db.commit()
    assert marker.read_text() == "keep this work"
    bridge_cleanup.assert_not_called()
    workspace_cleanup.assert_not_called()
    if live_runner:
        docker_cleanup.assert_not_called()
    else:
        docker_cleanup.assert_awaited_once_with(value["job_id"])
