"""Authenticated ADR-016 application boundary, independent of device/Worker grants."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.interactive_schemas import BindExecution, HostProof, SubmitTask
from hypertest.application.bindings import get_run_binding, record_binding_event
from hypertest.application.bootstrap import bootstrap_run, prepare_bootstrap_inputs
from hypertest.application.jobs import submit_job
from hypertest.application.persistent_workspace import verify_workspace
from hypertest.application.services import ConflictError, NotFoundError, canonical_json_sha256
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.connector.security import authenticate_device, require_capability, token_hash
from hypertest.domain.bindings import BindingStatus, RunExecutionBinding
from hypertest.domain.connector import RunHarnessPlacement
from hypertest.domain.enums import AgentSessionStatus, TestRunStatus
from hypertest.domain.harness import RunHarnessState, RunReport
from hypertest.domain.interactive import (
    InteractiveActorIdentity,
    InteractiveClientRegistration,
    InteractiveExecutionBinding,
    InteractiveExecutionGrant,
    InteractiveIntegrationGrant,
    InteractiveSubmissionReceipt,
    RunExecutionSelection,
)
from hypertest.domain.jobs import DurableJob, JobStatus, JobType
from hypertest.domain.models import (
    AgentSessionRecord,
    AuditEvent,
    Evidence,
    OutboxEvent,
    Project,
    SourceSnapshot,
    TestRun,
    Verdict,
)
from hypertest.runner.artifacts import ArtifactIntegrityError, _path, read_evidence_content

MAX_CONTENT = 8 * 1024 * 1024


async def now(db):
    return await db.scalar(select(func.clock_timestamp()))


async def authenticate(db, token: str, scope: str | None = None, *, project_id=None, run_id=None):
    if not token or len(token) > 512:
        raise HTTPException(401, "Interactive authorization required")
    grant = await db.scalar(
        select(InteractiveIntegrationGrant)
        .where(InteractiveIntegrationGrant.token_hash == token_hash(token))
        .execution_options(populate_existing=True)
    )
    return await authenticate_integration_record(
        db, grant, scope, project_id=project_id, run_id=run_id
    )


async def authenticate_integration_record(db, grant, scope=None, *, project_id=None, run_id=None):
    """Authenticate a current registered reference without persisting raw credentials."""
    clock = await now(db)
    if grant is None:
        raise HTTPException(401, "Interactive authorization rejected")
    actor = await db.get(InteractiveActorIdentity, grant.actor_identity_id, populate_existing=True)
    client = await db.get(
        InteractiveClientRegistration,
        (grant.actor_identity_id, grant.client_instance_id),
        populate_existing=True,
    )
    if (
        not actor
        or not client
        or actor.status != "ACTIVE"
        or client.status != "ACTIVE"
        or grant.status != "ACTIVE"
        or not grant.not_before <= clock < grant.expires_at
    ):
        raise HTTPException(403, "Interactive authorization revoked or expired")
    if scope and scope not in grant.scopes:
        raise HTTPException(403, "Interactive scope rejected")
    if run_id:
        run = await db.get(TestRun, run_id)
        if not run or run.project_id != grant.project_id:
            raise HTTPException(404, "Run not found in authorized Project")
        project_id = run.project_id
    if project_id and project_id != grant.project_id:
        raise HTTPException(403, "Interactive Project scope rejected")
    return grant


def event(db, grant, action, entity_type, entity_id, *, run_id=None, extra=None):
    payload = {
        "actor_identity_id": str(grant.actor_identity_id),
        "client_instance_id": str(grant.client_instance_id),
        **(extra or {}),
    }
    db.add_all(
        [
            AuditEvent(
                project_id=grant.project_id,
                test_run_id=run_id,
                actor_type="USER",
                actor_ref=str(grant.actor_identity_id),
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                event_metadata=payload,
            ),
            OutboxEvent(
                aggregate_type=entity_type,
                aggregate_id=entity_id,
                event_type=action,
                payload=payload,
            ),
        ]
    )


def receipt_read(row):
    return {
        "id": str(row.id),
        "receipt_id": str(row.id),
        "status": row.status,
        "project_id": str(row.project_id),
        "submission_key": row.submission_key,
        "test_run_id": str(row.test_run_id) if row.test_run_id else None,
        "initial_job_id": str(row.initial_durable_job_id) if row.initial_durable_job_id else None,
        "input_digest": row.input_digest,
        "normalization_version": row.normalization_version,
        "error_code": row.error_code,
    }


async def find_submission(db, grant, key):
    return await db.scalar(
        select(InteractiveSubmissionReceipt).where(
            InteractiveSubmissionReceipt.actor_identity_id == grant.actor_identity_id,
            InteractiveSubmissionReceipt.client_instance_id == grant.client_instance_id,
            InteractiveSubmissionReceipt.project_id == grant.project_id,
            InteractiveSubmissionReceipt.submission_key == key,
        )
    )


async def submit_task(db: AsyncSession, token: str, payload: SubmitTask):
    grant = await authenticate(db, token, "task:submit", project_id=payload.project_id)
    data = payload.model_dump(mode="json")
    data["bootstrap"]["repository_url"] = payload.bootstrap.repository_url.strip()
    data["bootstrap"]["commit_sha"] = payload.bootstrap.commit_sha.lower()
    from hypertest.application.policy import compile_policy

    data["bootstrap"]["policy"] = {
        "effective_policy_hash": compile_policy(
            {"gate_version": "mvp/v1", **payload.bootstrap.policy}
        ).effective_policy_hash
    }
    # branch is a display reference, not the immutable input identity.
    data["bootstrap"].pop("branch", None)
    data.pop("submission_key")
    digest = canonical_json_sha256(data)
    existing = await find_submission(db, grant, payload.submission_key)
    if existing:
        if existing.input_digest != digest:
            raise ConflictError("submission key is bound to different input")
        return receipt_read(existing)
    identity = canonical_json_sha256(
        {
            "actor": str(grant.actor_identity_id),
            "client": str(grant.client_instance_id),
            "project": str(grant.project_id),
            "key": payload.submission_key,
        }
    )
    bootstrap = payload.bootstrap.model_copy(update={"idempotency_key": f"interactive:{identity}"})
    # Environment I/O and immutable input files precede the atomic DB phase.
    prepared = await prepare_bootstrap_inputs(db, payload.project_id, bootstrap)
    await db.commit()
    # The Project lock serializes both receipt identity and bootstrap dedup.
    if not await db.scalar(
        select(Project).where(Project.id == payload.project_id).with_for_update()
    ):
        raise NotFoundError("Project not found")
    grant = await authenticate(db, token, "task:submit", project_id=payload.project_id)
    existing = await find_submission(db, grant, payload.submission_key)
    if existing:
        if existing.input_digest != digest:
            raise ConflictError("submission key is bound to different input")
        return receipt_read(existing)
    run = await bootstrap_run(db, payload.project_id, bootstrap, commit=False, prepared=prepared)
    from hypertest.domain.harness_selection import create_execution_selection

    selected = await create_execution_selection(
        db,
        run.id,
        execution_mode=payload.execution_mode,
        execution_driver=payload.execution_driver,
        node_id=bootstrap.harness_node_id,
        source_bundle_transfer_id=bootstrap.source_bundle_transfer_id,
    )
    job = await submit_job(
        db,
        run.id,
        JobType.ADVANCE_RUN,
        payload={
            "execution_profile": "run-persistent-harness/v1",
            "prepare_workspace": True,
            "backend": "docker",
            "timeout_seconds": payload.budget.timeout_seconds,
            "max_steps": payload.budget.max_steps,
        },
        idempotency_key=f"interactive:{identity}",
        commit=False,
    )
    snapshot = await db.get(SourceSnapshot, run.source_snapshot_id)
    manifest = json.loads(json.dumps(data))
    manifest["bootstrap"]["prd_sha256"] = hashlib.sha256(
        payload.bootstrap.prd_text.encode()
    ).hexdigest()
    manifest["bootstrap"]["configuration_sha256"] = hashlib.sha256(
        payload.bootstrap.configuration_text.encode()
    ).hexdigest()
    manifest["bootstrap"].pop("prd_text")
    manifest["bootstrap"].pop("configuration_text")
    manifest["frozen_input"] = {
        "source_snapshot_id": str(run.source_snapshot_id),
        "policy_snapshot_id": str(run.policy_snapshot_id),
        "source_fingerprint": snapshot.source_fingerprint,
        "environment_definition": snapshot.environment_definition,
        "harness_host_id": selected.harness_host_id,
    }
    manifest["frozen_input_digest"] = canonical_json_sha256(manifest["frozen_input"])
    row = InteractiveSubmissionReceipt(
        grant_id=grant.id,
        actor_identity_id=grant.actor_identity_id,
        client_instance_id=grant.client_instance_id,
        project_id=grant.project_id,
        submission_key=payload.submission_key,
        input_digest=digest,
        input_manifest=manifest,
        status="ACCEPTED",
        test_run_id=run.id,
        initial_durable_job_id=job.id,
    )
    db.add(row)
    await db.flush()
    event(
        db,
        grant,
        "interactive.submission.accepted",
        "InteractiveSubmissionReceipt",
        row.id,
        run_id=run.id,
        extra={"job_id": str(job.id)},
    )
    await authenticate(db, token, "task:submit", project_id=payload.project_id)
    await db.commit()
    return receipt_read(row)


async def verify_host(db, token, device_token, grant, run, proof: HostProof):
    node, _device = await authenticate_device(db, device_token, proof.node_id)
    result = await verify_host_context(db, node, grant, run, proof)
    await authenticate(db, token, "run:execute", run_id=run.id)
    return result


async def verify_host_context(db, node, grant, run, proof):
    scope = await require_capability(db, node.id, run.project_id, "harness")
    if proof.adapter_id not in scope.constraints.get("interactive_host_adapters", []):
        raise HTTPException(403, "Trusted host adapter is not authorized for this Project")
    clock = await now(db)
    if abs((clock - proof.observed_at).total_seconds()) > 30:
        raise HTTPException(403, "Host observation is not current")
    selected = await db.get(RunExecutionSelection, run.id)
    if (
        not selected
        or selected.execution_mode != "LOCAL"
        or selected.execution_driver != "INTERACTIVE_MCP"
        or selected.node_id != node.id
        or selected.source_bundle_transfer_id != proof.source_bundle_transfer_id
    ):
        raise ConflictError("host proof does not match frozen interactive execution selection")
    source = await db.get(SourceSnapshot, run.source_snapshot_id)
    from hypertest.application.source_transfer import accepted_transfer

    transfer = await accepted_transfer(
        db,
        proof.source_bundle_transfer_id,
        project_id=run.project_id,
        node_id=node.id,
        origin=source.repository_url,
        commit_sha=source.commit_sha,
    )
    await authenticate_integration_record(db, grant, "run:execute", run_id=run.id)
    return node, transfer, source


def attachment_digest(proof):
    data = proof.model_dump(mode="json")
    data.pop("observed_at")
    data.pop("lifecycle")
    return canonical_json_sha256(data)


async def owned_attachment(db, grant, *, execution_id=None, run_id=None, attach_key=None):
    query = select(InteractiveExecutionBinding).where(
        InteractiveExecutionBinding.actor_identity_id == grant.actor_identity_id,
        InteractiveExecutionBinding.client_instance_id == grant.client_instance_id,
    )
    if execution_id:
        query = query.where(InteractiveExecutionBinding.id == execution_id)
    if run_id:
        query = query.where(InteractiveExecutionBinding.test_run_id == run_id)
    if attach_key:
        query = query.where(InteractiveExecutionBinding.attach_key == attach_key)
    row = await db.scalar(query)
    if not row or (await db.get(TestRun, row.test_run_id)).project_id != grant.project_id:
        raise NotFoundError("interactive execution not found")
    return row


async def execution_read(db, row):
    binding = await db.get(RunExecutionBinding, row.binding_id, populate_existing=True)
    job = await db.scalar(
        select(DurableJob)
        .where(DurableJob.test_run_id == row.test_run_id)
        .order_by(DurableJob.created_at.desc())
        .limit(1)
    )
    current = await db.scalar(
        select(InteractiveExecutionGrant)
        .where(
            InteractiveExecutionGrant.interactive_binding_id == row.id,
            InteractiveExecutionGrant.status == "ACTIVE",
        )
        .order_by(InteractiveExecutionGrant.created_at.desc())
        .limit(1)
    )
    clock = await now(db)
    return {
        "id": str(row.id),
        "execution_id": str(row.id),
        "run_id": str(row.test_run_id),
        "binding_id": str(binding.id),
        "agent_session_id": str(row.agent_session_id),
        "binding_epoch": binding.binding_epoch,
        "binding_row_version": binding.row_version,
        "status": binding.status.value,
        "job_status": job.status.value if job else None,
        "execute_ready": bool(
            job and job.status == JobStatus.RUNNING and binding.status == BindingStatus.ACTIVE
        ),
        "grant_expires_at": current.expires_at.isoformat()
        if current and current.expires_at > clock
        else None,
        "attach_key": row.attach_key,
    }


async def bind_execution(db, token: str, device_token: str, payload: BindExecution):
    grant = await authenticate(db, token, "run:execute", run_id=payload.run_id)
    run = await db.get(TestRun, payload.run_id)
    node, transfer, source = await verify_host(
        db, token, device_token, grant, run, payload.host_proof
    )
    existing = await db.scalar(
        select(InteractiveExecutionBinding).where(InteractiveExecutionBinding.test_run_id == run.id)
    )
    digest = attachment_digest(payload.host_proof)
    if existing:
        existing = await owned_attachment(db, grant, execution_id=existing.id)
        if existing.attach_key != payload.attach_key or existing.input_digest != digest:
            raise ConflictError("interactive binding identity is immutable")
        return await execution_read(db, existing)
    source_workspace, workspace_id = transfer.server_workspace, payload.host_proof.workspace_id
    # Structural registration is metadata only. The original Worker verifies
    # and materializes its separate pinned mirror before activating the Session.
    await db.commit()
    run = await db.scalar(
        select(TestRun)
        .where(TestRun.id == payload.run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    grant = await authenticate(db, token, "run:execute", run_id=payload.run_id)
    node, transfer, source = await verify_host(
        db, token, device_token, grant, run, payload.host_proof
    )
    if run.status in {TestRunStatus.CANCELLED, TestRunStatus.COMPLETED} or await get_run_binding(
        db, run.id, lock=True
    ):
        raise ConflictError("Run is already bound or terminal; query the original attachment")
    receipt = await db.scalar(
        select(InteractiveSubmissionReceipt).where(
            InteractiveSubmissionReceipt.test_run_id == run.id,
            InteractiveSubmissionReceipt.actor_identity_id == grant.actor_identity_id,
            InteractiveSubmissionReceipt.client_instance_id == grant.client_instance_id,
        )
    )
    if not receipt:
        raise ConflictError("only the submitting client may bind this interactive Run")
    if await db.scalar(
        select(AgentSessionRecord.id).where(
            AgentSessionRecord.provider == payload.host_proof.provider,
            AgentSessionRecord.provider_session_id == payload.host_proof.native_session_id,
        )
    ):
        raise ConflictError("this native execution Session already belongs to a Run")
    agent = AgentSessionRecord(
        test_run_id=run.id,
        provider=payload.host_proof.provider,
        harness=payload.host_proof.harness,
        provider_session_id=payload.host_proof.native_session_id,
        workspace_id=workspace_id,
        status=AgentSessionStatus.CREATED,
    )
    db.add(agent)
    await db.flush()
    binding = RunExecutionBinding(
        test_run_id=run.id,
        logical_worker_id=uuid7(),
        primary_agent_session_id=agent.id,
        harness_host_id=node.node_key,
        workspace_id=workspace_id,
        binding_epoch=1,
        status=BindingStatus.RESERVED,
    )
    db.add(binding)
    await db.flush()
    db.add(
        RunHarnessPlacement(
            test_run_id=run.id,
            binding_id=binding.id,
            node_id=node.id,
            mode="LOCAL_CONNECTOR",
            source_transfer_kind="SOURCE_BUNDLE",
            source_bundle_transfer_id=transfer.id,
        )
    )
    await db.flush()
    budget = receipt.input_manifest.get("budget", {})
    db.add(
        RunHarnessState(
            binding_id=binding.id,
            first_job_id=receipt.initial_durable_job_id,
            source_workspace=source_workspace,
            max_steps=budget.get("max_steps", 12),
            timeout_seconds=budget.get("timeout_seconds", 300),
            harness_budget_seconds=budget.get("harness_budget_seconds", 3600),
        )
    )
    proof_data = payload.host_proof.model_dump(mode="json")
    row = InteractiveExecutionBinding(
        binding_id=binding.id,
        agent_session_id=agent.id,
        test_run_id=run.id,
        grant_id=grant.id,
        actor_identity_id=grant.actor_identity_id,
        client_instance_id=grant.client_instance_id,
        node_id=node.id,
        provider=agent.provider,
        native_session_id=agent.provider_session_id,
        workspace_id=workspace_id,
        attach_key=payload.attach_key,
        input_digest=digest,
        attached_epoch=1,
        host_attachment_id=payload.host_proof.attachment_id,
        host_proof_sha256=canonical_json_sha256(proof_data),
        host_proof=proof_data,
    )
    db.add(row)
    await db.flush()
    await record_binding_event(db, binding, "binding.reserved")
    event(
        db,
        grant,
        "interactive.execution.bound",
        "InteractiveExecutionBinding",
        row.id,
        run_id=run.id,
    )
    await db.commit()
    return await execution_read(db, row)


async def progress(db, grant, run_id):
    run = await db.get(TestRun, run_id)
    source = await db.get(SourceSnapshot, run.source_snapshot_id)
    selection = await db.get(RunExecutionSelection, run_id)
    if selection is None:
        from hypertest.domain.harness_selection import RunHarnessSelection

        legacy = await db.get(RunHarnessSelection, run_id)
        if legacy:
            selection = SimpleNamespace(
                execution_mode="LOCAL",
                execution_driver="PLATFORM_MANAGED",
                harness_mode=legacy.mode,
                node_id=legacy.node_id,
                source_bundle_transfer_id=legacy.source_bundle_transfer_id,
            )
    binding = await get_run_binding(db, run_id)
    job = await db.scalar(
        select(DurableJob)
        .where(DurableJob.test_run_id == run_id)
        .order_by(DurableJob.created_at.desc())
        .limit(1)
    )
    verdict = await db.scalar(
        select(Verdict)
        .where(Verdict.test_run_id == run_id)
        .order_by(Verdict.sequence_no.desc())
        .limit(1)
    )
    return {
        "run_id": str(run.id),
        "project_id": str(run.project_id),
        "status": run.status.value,
        "repository_url": source.repository_url,
        "commit_sha": source.commit_sha,
        "source_snapshot_id": str(source.id),
        "job": {"id": str(job.id), "status": job.status.value, "error_code": job.error_code}
        if job
        else None,
        "binding_status": binding.status.value if binding else None,
        "workspace_id": binding.workspace_id if binding else None,
        "execution_mode": selection.execution_mode if selection else "CLOUD",
        "execution_driver": selection.execution_driver if selection else "PLATFORM_MANAGED",
        "harness_mode": selection.harness_mode if selection else "SERVER_HOST",
        "harness_node_id": str(selection.node_id) if selection and selection.node_id else None,
        "source_bundle_transfer_id": str(selection.source_bundle_transfer_id)
        if selection and selection.source_bundle_transfer_id
        else None,
        "verdict": {
            "id": str(verdict.id),
            "decision": verdict.decision.value,
            "status": verdict.status.value,
        }
        if verdict
        else None,
        "quality_decided": verdict is not None,
    }


def _cursor_key():
    key = get_settings().connector_operator_key
    if not key:
        raise HTTPException(503, "Interactive cursor signing key is not configured")
    return key.encode()


def cursor_encode(data):
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(_cursor_key(), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature + raw).decode()


def cursor_decode(value, scope):
    try:
        raw = base64.b64decode(value.encode(), altchars=b"-_", validate=True)
        if len(raw) > 4096 or not hmac.compare_digest(
            raw[:32], hmac.new(_cursor_key(), raw[32:], hashlib.sha256).digest()
        ):
            raise ValueError()
        data = json.loads(raw[32:])
        if data["scope"] != scope or type(data["offset"]) is not int or data["offset"] < 0:
            raise ValueError()
        return data
    except (ValueError, KeyError, TypeError):
        raise ConflictError("cursor is invalid or outside the authorized object scope") from None


def cursor_scope(grant, run_id, kind, object_id=None):
    return {
        "actor": str(grant.actor_identity_id),
        "client": str(grant.client_instance_id),
        "project": str(grant.project_id),
        "run": str(run_id),
        "kind": kind,
        "object": str(object_id) if object_id else None,
    }


def evidence_metadata(row):
    return {
        "id": str(row.id),
        "run_id": str(row.test_run_id),
        "execution_id": str(row.execution_id) if row.execution_id else None,
        "key": row.key,
        "sha256": row.sha256,
        "size_bytes": row.size_bytes,
        "media_type": row.content_type,
        "evidence_type": row.evidence_type.value,
        "trust_level": row.trust_level.value,
        "status": row.status.value,
        "source": row.source,
        "collector": row.collector,
        "created_at": row.created_at.isoformat(),
    }


def report_metadata(row):
    return {
        "id": str(row.id),
        "run_id": str(row.test_run_id),
        "sha256": row.content_sha256,
        "schema_version": row.envelope.get("schema_version"),
        "verdict_key": row.envelope.get("verdict_key"),
        "created_at": row.created_at.isoformat(),
    }


async def list_objects(db, grant, run_id, kind, cursor, limit):
    model = Evidence if kind == "evidence" else RunReport
    rows = list(
        await db.scalars(
            select(model).where(model.test_run_id == run_id).order_by(model.id).limit(5001)
        )
    )
    if len(rows) > 5000:
        raise ConflictError("collection exceeds the bounded interactive read limit")
    items = [(evidence_metadata(r) if kind == "evidence" else report_metadata(r)) for r in rows]
    version = canonical_json_sha256(items)
    scope = cursor_scope(grant, run_id, kind)
    offset = 0
    if cursor:
        page = cursor_decode(cursor, scope)
        if page["version"] != version:
            raise ConflictError("collection changed; restart pagination")
        offset = page["offset"]
    next_offset = min(len(items), offset + limit)
    return {
        "items": items[offset:next_offset],
        "object_version": version,
        "untrusted": True,
        "next_cursor": cursor_encode({"scope": scope, "version": version, "offset": next_offset})
        if next_offset < len(items)
        else None,
    }


async def read_object(db, grant, run_id, object_id, kind, cursor, limit):
    row = await db.get(Evidence if kind == "evidence" else RunReport, object_id)
    if not row or row.test_run_id != run_id:
        raise NotFoundError("object not found in the authorized Run")
    digest = row.sha256 if kind == "evidence" else row.content_sha256
    path = _path(digest)
    try:
        if path.is_symlink() or path.stat().st_size > MAX_CONTENT:
            raise ArtifactIntegrityError("interactive content is unsafe or exceeds 8 MiB")
        content = read_evidence_content(
            row
            if kind == "evidence"
            else SimpleNamespace(sha256=digest, artifact_uri=row.artifact_uri, size_bytes=None)
        )
    except OSError:
        raise ArtifactIntegrityError("interactive content unavailable") from None
    metadata = evidence_metadata(row) if kind == "evidence" else report_metadata(row)
    version = canonical_json_sha256(metadata)
    scope = cursor_scope(grant, run_id, kind, object_id)
    offset = 0
    if cursor:
        page = cursor_decode(cursor, scope)
        if page["version"] != version:
            raise ConflictError("object version changed; restart reading")
        offset = page["offset"]
    media = (
        row.content_type or "application/octet-stream" if kind == "evidence" else "text/markdown"
    )
    try:
        text = (
            content.decode("utf-8")
            if media.startswith("text/") or media in {"application/json", "application/xml"}
            else None
        )
    except UnicodeDecodeError:
        raise ArtifactIntegrityError("declared text content is not UTF-8") from None
    source = text if text is not None else content
    piece = source[offset : offset + limit]
    end = min(len(source), offset + limit)
    return {
        "schema_version": "hypertest.interactive-content/v1alpha1",
        "object_type": kind,
        "object_id": str(row.id),
        "run_id": str(run_id),
        "object_version": version,
        "sha256": digest,
        "media_type": media,
        "encoding": "utf-8" if text is not None else "base64",
        "total_bytes": len(content),
        "offset": offset,
        "offset_unit": "characters" if text is not None else "bytes",
        "content": piece if text is not None else base64.b64encode(piece).decode(),
        "complete": end == len(source),
        "next_cursor": cursor_encode({"scope": scope, "version": version, "offset": end})
        if end < len(source)
        else None,
        "untrusted": True,
    }


async def continue_execution(db, token, device_token, execution_id, payload):
    from hypertest.application.bindings import assert_binding_claim
    from hypertest.domain.interactive import interactive_claim_identity

    grant = await authenticate(db, token, "run:execute")
    row = await owned_attachment(db, grant, execution_id=execution_id)
    run = await db.get(TestRun, row.test_run_id)
    _node, transfer, source = await verify_host(
        db, token, device_token, grant, run, payload.host_proof
    )
    if attachment_digest(payload.host_proof) != row.input_digest:
        raise ConflictError("continuation must use the original verified native attachment")
    await db.commit()
    # Lock Run -> Binding -> Job before grant issuance, just like domain writes.
    binding = await get_run_binding(db, run.id, lock=True)
    job = await db.scalar(
        select(DurableJob)
        .where(DurableJob.test_run_id == run.id, DurableJob.status == JobStatus.RUNNING)
        .with_for_update()
    )
    if not job or not job.lease_token or binding.status != BindingStatus.ACTIVE:
        raise ConflictError(
            "coordinator has not admitted this Run, or explicit recovery is required"
        )
    await assert_binding_claim(
        db, binding.id, binding.binding_epoch, job_id=job.id, lease_token=job.lease_token
    )
    # Continue must acquire authority before any short-grant lock. Integration
    # revocation locks integration -> short, while device rotation locks node ->
    # device. Reversing either order can deadlock and abort revocation itself.
    from hypertest.domain.connector import HarnessDeviceGrant, HarnessNode, NodeProjectCapability

    device = await db.scalar(
        select(HarnessDeviceGrant).where(HarnessDeviceGrant.token_hash == token_hash(device_token))
    )
    if not device or device.node_id != row.node_id:
        raise HTTPException(403, "Current original-node device authorization required")
    for model, predicates in [
        (InteractiveActorIdentity, [InteractiveActorIdentity.id == row.actor_identity_id]),
        (
            InteractiveClientRegistration,
            [
                InteractiveClientRegistration.actor_identity_id == row.actor_identity_id,
                InteractiveClientRegistration.client_instance_id == row.client_instance_id,
            ],
        ),
        (InteractiveIntegrationGrant, [InteractiveIntegrationGrant.id == grant.id]),
        (HarnessNode, [HarnessNode.id == row.node_id]),
        (HarnessDeviceGrant, [HarnessDeviceGrant.id == device.id]),
        (
            NodeProjectCapability,
            [
                NodeProjectCapability.node_id == row.node_id,
                NodeProjectCapability.project_id == run.project_id,
                NodeProjectCapability.capability == "harness",
            ],
        ),
        (
            NodeProjectCapability,
            [
                NodeProjectCapability.node_id == row.node_id,
                NodeProjectCapability.project_id == run.project_id,
                NodeProjectCapability.capability == "source_acquisition",
            ],
        ),
    ]:
        await db.scalar(
            select(model)
            .where(*predicates)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    # Fresh DB clock / records after waiting for locks: an earlier observation
    # cannot mint work after revoke/rotation won this serialization point.
    grant = await authenticate(db, token, "run:execute", run_id=run.id)
    await verify_host(db, token, device_token, grant, run, payload.host_proof)
    if await db.scalar(
        select(InteractiveExecutionGrant.id).where(
            InteractiveExecutionGrant.interactive_binding_id == row.id,
            InteractiveExecutionGrant.call_id == payload.continuation_key,
        )
    ):
        raise ConflictError(
            "GRANT_ALREADY_ISSUED: query original attachment; a lost secret is not replayed"
        )
    clock = await now(db)
    latest = await db.scalar(
        select(InteractiveExecutionGrant)
        .where(
            InteractiveExecutionGrant.interactive_binding_id == row.id,
            InteractiveExecutionGrant.job_id == job.id,
        )
        .order_by(InteractiveExecutionGrant.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if latest and (latest.status != "ACTIVE" or latest.expires_at <= clock):
        raise ConflictError(
            "execution authorization ended; reconcile and explicitly recover the original epoch"
        )
    active = list(
        await db.scalars(
            select(InteractiveExecutionGrant)
            .where(
                InteractiveExecutionGrant.interactive_binding_id == row.id,
                InteractiveExecutionGrant.status == "ACTIVE",
            )
            .with_for_update()
        )
    )
    # A continuation replaces only the same attachment's old short capability.
    for prior in active:
        prior.status, prior.row_version = "REVOKED", prior.row_version + 1
    execution_token = secrets.token_urlsafe(48)
    _node, device = await authenticate_device(db, device_token, row.node_id)
    short = InteractiveExecutionGrant(
        interactive_binding_id=row.id,
        device_grant_id=device.id,
        job_id=job.id,
        integration_grant_id=grant.id,
        token_hash=token_hash(execution_token),
        binding_epoch=binding.binding_epoch,
        claim_identity=interactive_claim_identity(row.id, job.lease_token),
        call_id=payload.continuation_key,
        host_attachment_id=row.host_attachment_id,
        host_proof_sha256=canonical_json_sha256(payload.host_proof.model_dump(mode="json")),
        not_before=clock,
        expires_at=min(
            clock
            + timedelta(
                seconds=min(120, getattr(get_settings(), "interactive_grant_ttl_seconds", 120))
            ),
            job.lease_expires_at,
            grant.expires_at,
            device.expires_at,
        ),
    )
    db.add(short)
    await db.flush()
    event(
        db,
        grant,
        "interactive.execution.granted",
        "InteractiveExecutionGrant",
        short.id,
        run_id=run.id,
        extra={"execution_binding_id": str(row.id), "binding_epoch": binding.binding_epoch},
    )
    await db.commit()
    result = await execution_read(db, row)
    # Private daemon response only. The MCP projection must strip this secret.
    result.update(execution_token=execution_token, expires_at=short.expires_at.isoformat())
    return result


async def validate_execution_grant(db, token, execution_token, execution_id):
    grant = await authenticate(db, token, "run:execute")
    row = await owned_attachment(db, grant, execution_id=execution_id)
    short = await db.scalar(
        select(InteractiveExecutionGrant)
        .where(InteractiveExecutionGrant.token_hash == token_hash(execution_token))
        .execution_options(populate_existing=True)
    )
    if (
        not execution_token
        or len(execution_token) > 512
        or not short
        or short.interactive_binding_id != row.id
        or short.integration_grant_id != grant.id
    ):
        raise HTTPException(403, "Current interactive execution capability required")
    from hypertest.application.jobs import JobLeaseLost

    try:
        job = await validate_execution_record(db, row, short)
    except JobLeaseLost:
        raise HTTPException(403, "Interactive execution claim is stale") from None
    return row, short, job


async def validate_execution_record(db, row, short):
    """Lock aggregate then exact authorization references, serializing revocation.

    No external I/O occurs while these transaction locks are held. Every domain
    commit re-enters this check; the inbox itself conveys no execution authority.
    """
    from hypertest.application.bindings import assert_binding_claim
    from hypertest.domain.connector import HarnessDeviceGrant, HarnessNode, NodeProjectCapability
    from hypertest.domain.interactive import interactive_claim_identity

    if not row or not short:
        raise HTTPException(403, "Interactive execution authorization required")
    job = await db.get(DurableJob, short.job_id, populate_existing=True)
    if not job or not job.lease_token:
        raise HTTPException(403, "Interactive execution claim is stale")
    await assert_binding_claim(
        db, row.binding_id, short.binding_epoch, job_id=job.id, lease_token=job.lease_token
    )

    async def locked(model, *conditions):
        return await db.scalar(
            select(model)
            .where(*conditions)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )

    actor = await locked(
        InteractiveActorIdentity, InteractiveActorIdentity.id == row.actor_identity_id
    )
    client = await locked(
        InteractiveClientRegistration,
        InteractiveClientRegistration.actor_identity_id == row.actor_identity_id,
        InteractiveClientRegistration.client_instance_id == row.client_instance_id,
    )
    integration = await locked(
        InteractiveIntegrationGrant, InteractiveIntegrationGrant.id == short.integration_grant_id
    )
    node = await locked(HarnessNode, HarnessNode.id == row.node_id)
    device = (
        await locked(HarnessDeviceGrant, HarnessDeviceGrant.id == short.device_grant_id)
        if short.device_grant_id
        else None
    )
    scope = await locked(
        NodeProjectCapability,
        NodeProjectCapability.node_id == row.node_id,
        NodeProjectCapability.project_id == job.project_id,
        NodeProjectCapability.capability == "harness",
    )
    short = await locked(InteractiveExecutionGrant, InteractiveExecutionGrant.id == short.id)
    clock = await now(db)
    if (
        short.status != "ACTIVE"
        or not short.not_before <= clock < short.expires_at
        or short.claim_identity != interactive_claim_identity(row.id, job.lease_token)
        or not integration
        or integration.status != "ACTIVE"
        or not integration.not_before <= clock < integration.expires_at
        or "run:execute" not in integration.scopes
        or integration.project_id != job.project_id
        or integration.actor_identity_id != row.actor_identity_id
        or integration.client_instance_id != row.client_instance_id
        or not actor
        or not client
        or actor.status != "ACTIVE"
        or client.status != "ACTIVE"
        or not node
        or node.registration_status != "ACTIVE"
        or not device
        or device.node_id != row.node_id
        or device.status != "ACTIVE"
        or not device.not_before <= clock < device.expires_at
        or not scope
        or scope.status != "ACTIVE"
        or row.host_proof.get("adapter_id")
        not in scope.constraints.get("interactive_host_adapters", [])
    ):
        raise HTTPException(403, "Interactive execution authorization ended")
    return job


async def recover_execution(db, token, device_token, execution_id, payload, operator):
    """API: authorize and durably queue original-identity recovery; never read files."""
    from hypertest.api.interactive_schemas import InteractiveRecoveryCommand
    from hypertest.domain.harness import RuntimeControlRequest

    grant = await authenticate(db, token, "run:execute")
    row = await owned_attachment(db, grant, execution_id=execution_id)
    run = await db.get(TestRun, row.test_run_id)
    await verify_host(db, token, device_token, grant, run, payload.host_proof)
    if attachment_digest(payload.host_proof) != row.input_digest:
        raise ConflictError("recovery requires the original native/workspace/source attachment")
    _node, device = await authenticate_device(db, device_token, row.node_id)
    digest = canonical_json_sha256(
        {
            "expected_epoch": payload.expected_epoch,
            "expected_row_version": payload.expected_row_version,
            "retry_key": payload.retry_key,
            "attachment_digest": row.input_digest,
        }
    )
    await get_run_binding(db, run.id, lock=True)
    existing = await find_recovery_control(db, row.id, payload.retry_key)
    if existing:
        if existing.payload.get("input_digest") != digest:
            raise ConflictError("recovery key is already bound to different input")
    else:
        clock = await now(db)
        command = InteractiveRecoveryCommand(
            kind="INTERACTIVE_MCP_RECOVERY_V1",
            execution_id=row.id,
            integration_grant_id=grant.id,
            device_grant_id=device.id,
            requested_by=operator,
            input_digest=digest,
            payload=payload,
        )
        request = RuntimeControlRequest(
            operation="RECOVER_BINDING",
            payload=command.model_dump(mode="json"),
            expires_at=clock + timedelta(seconds=get_settings().runtime_control_timeout_seconds),
        )
        db.add(request)
        await db.flush()
    # Release aggregate locks before waiting; the independent Worker owns I/O.
    await db.commit()
    import asyncio

    deadline = asyncio.get_running_loop().time() + get_settings().runtime_control_timeout_seconds
    while True:
        result = await query_recovery(db, token, execution_id, payload.retry_key)
        if result.get("status") not in {"QUEUED", "RUNNING"}:
            return result
        if asyncio.get_running_loop().time() >= deadline:
            return result
        await asyncio.sleep(0.1)


async def find_recovery_control(db, execution_id, retry_key):
    from hypertest.domain.harness import RuntimeControlRequest

    return await db.scalar(
        select(RuntimeControlRequest)
        .where(
            RuntimeControlRequest.operation == "RECOVER_BINDING",
            RuntimeControlRequest.payload["kind"].astext == "INTERACTIVE_MCP_RECOVERY_V1",
            RuntimeControlRequest.payload["execution_id"].astext == str(execution_id),
            RuntimeControlRequest.payload["payload"]["retry_key"].astext == retry_key,
        )
        .order_by(RuntimeControlRequest.created_at)
        .limit(1)
        .execution_options(populate_existing=True)
    )


async def query_recovery(db, token, execution_id, retry_key):
    grant = await authenticate(db, token, "run:execute")
    row = await owned_attachment(db, grant, execution_id=execution_id)
    request = await find_recovery_control(db, row.id, retry_key)
    if not request:
        return {"status": "NOT_FOUND", "retry_key": retry_key}
    result = (
        (request.result or {})
        if request.status == "SUCCEEDED"
        else {
            "status": request.status,
            "execution_id": str(row.id),
            "retry_key": retry_key,
            "control_request_id": str(request.id),
            "error_code": request.error_code,
            "instruction": "Query this original recovery key; do not replay unknown recovery",
        }
    )
    if request.status == "FAILED":
        raise ConflictError(
            "interactive recovery rejected: " + (request.error_code or "CONTROL_FAILED")
        )
    await db.commit()
    return result


async def authorize_recovery_command(db, command, *, lock=False):
    """Worker revalidates the exact authority accepted by the operator API."""
    from hypertest.domain.connector import HarnessDeviceGrant, HarnessNode, NodeProjectCapability

    grant = await db.get(
        InteractiveIntegrationGrant, command.integration_grant_id, populate_existing=True
    )
    grant = await authenticate_integration_record(db, grant, "run:execute")
    row = await owned_attachment(db, grant, execution_id=command.execution_id)
    run = await db.get(TestRun, row.test_run_id)
    if lock:
        await get_run_binding(db, run.id, lock=True)
        # Same authorization lock order as domain tool admission and revocation.
        for model, predicates in [
            (InteractiveActorIdentity, [InteractiveActorIdentity.id == row.actor_identity_id]),
            (
                InteractiveClientRegistration,
                [
                    InteractiveClientRegistration.actor_identity_id == row.actor_identity_id,
                    InteractiveClientRegistration.client_instance_id == row.client_instance_id,
                ],
            ),
            (
                InteractiveIntegrationGrant,
                [InteractiveIntegrationGrant.id == command.integration_grant_id],
            ),
            (HarnessNode, [HarnessNode.id == row.node_id]),
            (HarnessDeviceGrant, [HarnessDeviceGrant.id == command.device_grant_id]),
            (
                NodeProjectCapability,
                [
                    NodeProjectCapability.node_id == row.node_id,
                    NodeProjectCapability.project_id == run.project_id,
                    NodeProjectCapability.capability == "harness",
                ],
            ),
            (
                NodeProjectCapability,
                [
                    NodeProjectCapability.node_id == row.node_id,
                    NodeProjectCapability.project_id == run.project_id,
                    NodeProjectCapability.capability == "source_acquisition",
                ],
            ),
        ]:
            await db.scalar(
                select(model)
                .where(*predicates)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        grant = await authenticate_integration_record(db, grant, "run:execute", run_id=run.id)
    clock = await now(db)
    device = await db.get(HarnessDeviceGrant, command.device_grant_id, populate_existing=True)
    node = await db.get(HarnessNode, row.node_id, populate_existing=True)
    if (
        not device
        or device.node_id != row.node_id
        or device.status != "ACTIVE"
        or not device.not_before <= clock < device.expires_at
        or not node
        or node.registration_status != "ACTIVE"
    ):
        raise HTTPException(403, "Original recovery device authorization ended")
    _node, transfer, source = await verify_host_context(
        db, node, grant, run, command.payload.host_proof
    )
    if attachment_digest(command.payload.host_proof) != row.input_digest:
        raise ConflictError("recovery requires original native/workspace/source identity")
    return grant, row, run, transfer, source


async def recover_execution_from_control(db, command_data):
    """Trusted runtime-control Worker: fixed source I/O, then original epoch recovery."""
    from hypertest.api.interactive_schemas import InteractiveRecoveryCommand
    from hypertest.application.bindings import recover_run_binding
    from hypertest.domain.enums import ExecutionStatus
    from hypertest.domain.harness import GitLabIssueOperation, RunToolCall
    from hypertest.domain.jobs import ACTIVE_JOB_STATUSES
    from hypertest.domain.models import TestExecution

    command = InteractiveRecoveryCommand.model_validate(command_data)
    payload, operator = command.payload, command.requested_by
    if command.input_digest != canonical_json_sha256(
        {
            "expected_epoch": payload.expected_epoch,
            "expected_row_version": payload.expected_row_version,
            "retry_key": payload.retry_key,
            "attachment_digest": attachment_digest(payload.host_proof),
        }
    ):
        raise ConflictError("recovery command identity does not match its fixed input digest")
    grant, row, run, transfer, source = await authorize_recovery_command(db, command)
    source_workspace, workspace_id = transfer.server_workspace, row.workspace_id
    commit_sha, origin = source.commit_sha, source.repository_url
    await db.commit()
    await verify_workspace(source_workspace, workspace_id, commit_sha, origin)
    grant, row, run, _transfer, _source = await authorize_recovery_command(db, command, lock=True)
    binding = await get_run_binding(db, run.id, lock=True)
    if await db.scalar(
        select(DurableJob.id)
        .where(DurableJob.test_run_id == run.id, DurableJob.status.in_(ACTIVE_JOB_STATUSES))
        .limit(1)
    ):
        raise ConflictError("the original Job must finish before explicit recovery")
    if await db.scalar(
        select(TestExecution.id)
        .where(
            TestExecution.test_run_id == run.id,
            TestExecution.status.in_(
                [
                    ExecutionStatus.QUEUED,
                    ExecutionStatus.PROVISIONING,
                    ExecutionStatus.RUNNING,
                    ExecutionStatus.COLLECTING,
                ]
            ),
        )
        .limit(1)
    ):
        raise ConflictError("finish or safely cancel the original Runner Execution before recovery")
    from hypertest.domain.interactive import InteractiveToolRequest

    abandoned = list(
        await db.scalars(
            select(InteractiveToolRequest)
            .where(
                InteractiveToolRequest.interactive_binding_id == row.id,
                InteractiveToolRequest.status.in_(["QUEUED", "RUNNING"]),
            )
            .with_for_update()
        )
    )
    finished = await now(db)
    for request in abandoned:
        request.status = "REJECTED" if request.status == "QUEUED" else "UNKNOWN"
        request.error_code, request.finished_at = "WORKER_CLAIM_ENDED", finished
    await db.flush()
    # Reconcile only original trusted records; never replay a handler to discover
    # whether its external side effect happened.
    uncertain = list(
        await db.scalars(
            select(RunToolCall)
            .where(
                RunToolCall.binding_id == binding.id, RunToolCall.status.in_(["STARTED", "UNKNOWN"])
            )
            .with_for_update()
        )
    )
    for call in uncertain:
        if call.tool_name == "request_execution":
            execution = await db.scalar(
                select(TestExecution).where(
                    TestExecution.test_run_id == run.id,
                    TestExecution.idempotency_key == f"harness:{call.id}",
                )
            )
            if execution and execution.status in {
                ExecutionStatus.COMPLETED,
                ExecutionStatus.ERROR,
                ExecutionStatus.TIMED_OUT,
                ExecutionStatus.CANCELLED,
            }:
                call.status, call.finished_at = "SUCCEEDED", await now(db)
                call.result = {
                    "status": execution.status.value,
                    "execution_id": str(execution.id),
                    "execution_key": execution.key,
                    "outcome": execution.outcome.value if execution.outcome else None,
                }
                continue
        if call.tool_name == "request_gitlab_issue":
            from hypertest.domain.interactive import InteractiveToolRequest

            queued = await db.scalar(
                select(InteractiveToolRequest).where(
                    InteractiveToolRequest.interactive_binding_id == row.id,
                    InteractiveToolRequest.idempotency_key == call.idempotency_key,
                    InteractiveToolRequest.input_digest == call.input_sha256,
                    InteractiveToolRequest.tool_name == call.tool_name,
                )
            )
            operation = None
            if queued:
                original = {k: v for k, v in queued.arguments.items() if k != "idempotency_key"}
                operation = await db.scalar(
                    select(GitLabIssueOperation).where(
                        GitLabIssueOperation.binding_id == binding.id,
                        GitLabIssueOperation.finding_id == original["finding_id"],
                        GitLabIssueOperation.input_sha256 == canonical_json_sha256(original),
                    )
                )
            if operation and operation.status in {"SUCCEEDED", "REJECTED"}:
                call.status, call.finished_at = "SUCCEEDED", await now(db)
                call.result = {
                    "operation_id": str(operation.id),
                    "status": operation.status,
                    "issue_url": operation.issue_url,
                }
                continue
        raise ConflictError(
            "OUTCOME_UNKNOWN: reconcile the recorded tool/Runner/Issue operation before recovery"
        )
    if await db.scalar(
        select(GitLabIssueOperation.id)
        .where(
            GitLabIssueOperation.binding_id == binding.id,
            GitLabIssueOperation.status.in_(["PENDING", "UNKNOWN"]),
        )
        .limit(1)
    ):
        raise ConflictError(
            "OUTCOME_UNKNOWN: reconcile the original issue operation before recovery"
        )
    old_job = await db.scalar(
        select(DurableJob)
        .where(DurableJob.test_run_id == run.id)
        .order_by(DurableJob.created_at.desc())
        .with_for_update()
        .limit(1)
    )
    if not old_job or old_job.status not in {
        JobStatus.FAILED,
        JobStatus.INTERRUPTED,
        JobStatus.CANCELLED,
    }:
        raise ConflictError("only an interrupted original Job may be explicitly recovered")
    for short in await db.scalars(
        select(InteractiveExecutionGrant).where(
            InteractiveExecutionGrant.interactive_binding_id == row.id,
            InteractiveExecutionGrant.status == "ACTIVE",
        )
    ):
        short.status, short.row_version = "REVOKED", short.row_version + 1
    await recover_run_binding(
        db,
        binding.id,
        expected_epoch=payload.expected_epoch,
        expected_row_version=payload.expected_row_version,
        provider_session_id=row.native_session_id,
        workspace_id=row.workspace_id,
        harness_host_id=binding.harness_host_id,
        prior_calls_fenced=True,
        workspace_verified=True,
    )
    state = await db.get(RunHarnessState, binding.id)
    state.active_mission_id = state.active_attempt_id = None
    new_job = await submit_job(
        db,
        run.id,
        old_job.job_type,
        payload=old_job.payload,
        idempotency_key=f"interactive-recover:{payload.retry_key}",
        retry_of_job_id=old_job.id,
        commit=False,
    )
    event(
        db,
        grant,
        "interactive.execution.recovered",
        "InteractiveExecutionBinding",
        row.id,
        run_id=run.id,
        extra={
            "operator": operator,
            "job_id": str(new_job.id),
            "binding_epoch": binding.binding_epoch,
        },
    )
    await db.commit()
    result = await execution_read(db, row)
    result["new_job_id"] = str(new_job.id)
    return result


def tool_envelope(request):
    return {
        "status": request.status,
        "result": request.result,
        "request_id": str(request.id),
        "tool_call_id": request.tool_call_id,
        "idempotency_key": request.idempotency_key,
        "request_key": request.idempotency_key,
        "error_code": request.error_code,
    }


async def query_tool(db, token, execution_id, name, key):
    """Read exact delivery/operation only, including after its execution grant ends."""
    from hypertest.application.harness_tools import TOOL_MODELS
    from hypertest.domain.harness import RunToolCall
    from hypertest.domain.interactive import InteractiveToolRequest, interactive_claim_identity

    if name not in TOOL_MODELS:
        raise NotFoundError("Unsupported typed domain tool")
    grant = await authenticate(db, token, "run:execute")
    row = await owned_attachment(db, grant, execution_id=execution_id)
    request = await db.scalar(
        select(InteractiveToolRequest)
        .where(
            InteractiveToolRequest.interactive_binding_id == row.id,
            InteractiveToolRequest.idempotency_key == key,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not request:
        return {"status": "NOT_FOUND", "request_key": key}
    if request.tool_name != name:
        raise ConflictError("request key is already bound to a different tool")
    if request.status == "QUEUED":
        job = await db.get(DurableJob, request.job_id, populate_existing=True)
        short = await db.get(
            InteractiveExecutionGrant, request.execution_grant_id, populate_existing=True
        )
        clock = await now(db)
        if (
            not job
            or job.status != JobStatus.RUNNING
            or not job.lease_token
            or not job.lease_expires_at
            or job.lease_expires_at <= clock
            or request.claim_identity != interactive_claim_identity(row.id, job.lease_token)
            or not short
            or short.status != "ACTIVE"
            or short.expires_at <= clock
        ):
            request.status, request.error_code, request.finished_at = (
                "REJECTED",
                "WORKER_CLAIM_ENDED",
                clock,
            )
    if request.status in {"RUNNING", "UNKNOWN"}:
        job = await db.get(DurableJob, request.job_id, populate_existing=True)
        clock = await now(db)
        stale = (
            not job
            or job.status != JobStatus.RUNNING
            or not job.lease_token
            or not job.lease_expires_at
            or job.lease_expires_at <= clock
            or request.claim_identity != interactive_claim_identity(row.id, job.lease_token)
        )
        if request.status == "RUNNING" and stale:
            request.status, request.error_code, request.finished_at = (
                "UNKNOWN",
                "WORKER_CLAIM_ENDED",
                clock,
            )
            await db.flush()
        call = await db.scalar(
            select(RunToolCall).where(
                RunToolCall.binding_id == row.binding_id,
                RunToolCall.idempotency_key == key,
                RunToolCall.tool_name == name,
                RunToolCall.input_sha256 == request.input_digest,
            )
        )
        if call and call.status in {"SUCCEEDED", "FAILED"} and call.result is not None:
            request.status = "SUCCEEDED" if call.status == "SUCCEEDED" else "REJECTED"
            request.result, request.error_code, request.finished_at = call.result, None, clock
    result = tool_envelope(request)
    await db.commit()
    return result


async def enqueue_tool(
    db, token, execution_token, execution_id, name, arguments, *, request_key=None
):
    """Authenticate + persist + bounded wait. No Harness or Runner runs here."""
    import asyncio

    from hypertest.application.harness_tools import TOOL_MODELS
    from hypertest.domain.interactive import InteractiveToolRequest

    if name not in TOOL_MODELS:
        raise NotFoundError("Unsupported typed domain tool")
    args = TOOL_MODELS[name][0].model_validate(arguments).model_dump(mode="json")
    business_key = args.get("idempotency_key")
    if request_key is not None and (not 1 <= len(request_key) <= 255 or not request_key.strip()):
        raise ConflictError("invalid transport request key")
    if business_key and request_key and business_key != request_key:
        raise ConflictError("transport key must equal the original business idempotency key")
    key = business_key or request_key or str(uuid7())
    digest = canonical_json_sha256({"tool": name, "arguments": args})
    row, short, job = await validate_execution_grant(db, token, execution_token, execution_id)
    existing = await db.scalar(
        select(InteractiveToolRequest).where(
            InteractiveToolRequest.interactive_binding_id == row.id,
            InteractiveToolRequest.idempotency_key == key,
        )
    )
    if existing:
        if existing.tool_name != name or existing.input_digest != digest:
            raise ConflictError("request key is already bound to different input")
    else:
        request = InteractiveToolRequest(
            interactive_binding_id=row.id,
            execution_grant_id=short.id,
            integration_grant_id=short.integration_grant_id,
            actor_identity_id=row.actor_identity_id,
            client_instance_id=row.client_instance_id,
            job_id=job.id,
            binding_epoch=short.binding_epoch,
            claim_identity=short.claim_identity,
            tool_call_id=str(uuid7()),
            idempotency_key=key,
            tool_name=name,
            input_digest=digest,
            arguments=args,
        )
        db.add(request)
    await db.commit()
    # The Worker is independent of this HTTP coroutine. Disconnect/cancellation
    # cannot cancel its Runner or invoke a second dispatch. Client queries key.
    for _ in range(150):
        result = await query_tool(db, token, execution_id, name, key)
        if result["status"] not in {"QUEUED", "RUNNING"}:
            return result
        await asyncio.sleep(0.1)
    return result
