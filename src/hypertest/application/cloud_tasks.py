"""Transactional ADR-019 control plane. No Git, model, shell or test invocation."""
import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, text

from hypertest.api.cloud_schemas import PROFILE, CloudBudgetReservation, CloudBudgetSettlement
from hypertest.application import interactive
from hypertest.application.services import canonical_json_sha256
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.connector.security import token_hash
from hypertest.domain.cloud_tasks import (
    TERMINAL,
    CloudArtifact,
    CloudAssetReference,
    CloudAssetRevision,
    CloudAttempt,
    CloudConfigCredential,
    CloudDelegation,
    CloudDelegationAsset,
    CloudInputAnswer,
    CloudInputRequest,
    CloudInputResolution,
    CloudOperationReceipt,
    CloudRunArtifact,
    CloudRunCase,
    CloudRunRecord,
    CloudTask,
    CloudWorkGrant,
    CredentialVersion,
    ProjectCloudConfigRevision,
    ProjectCredential,
)
from hypertest.domain.models import AuditEvent, OutboxEvent, Project
from hypertest.domain.session_tasks import SessionTask

SCOPES = {
    "CONFIGURE": "cloud:configure", "STORE_CREDENTIAL": "credential:manage", "REVOKE_CREDENTIAL": "credential:manage",
    "CREATE_TASK": "cloud:dispatch", "UPDATE_TASK": "cloud:dispatch", "RESOLVE_INPUTS": "cloud:dispatch", "DISPATCH": "cloud:dispatch",
    "CANCEL_TASK": "cloud:control", "CANCEL_ATTEMPT": "cloud:control", "RESUME_ATTEMPT": "cloud:control", "RECONCILE_ATTEMPT": "cloud:control", "ANSWER_INPUT": "cloud:control",
    "TRANSITION": "cloud:work", "SUBMIT_ASSETS": "cloud:work", "UPLOAD_ARTIFACT": "cloud:work", "SUBMIT_RUN": "cloud:work",
    "SUBMIT_DELEGATION": "cloud:work", "REQUEST_INPUT": "cloud:work", "COMPLETE_ATTEMPT": "cloud:work",
}
ALLOWED = {
    "QUEUED": {"PREPARING", "CANCELLED"},
    "PREPARING": {"RUNNING", "WAITING_INPUT", "FAILED", "CANCELLED", "RECOVERY_REQUIRED"},
    "RUNNING": {"WAITING_INPUT", "COMPLETED", "FAILED", "CANCELLED", "RECOVERY_REQUIRED"},
    "WAITING_INPUT": {"PREPARING", "CANCELLED", "RECOVERY_REQUIRED"},
    "RECOVERY_REQUIRED": {"PREPARING", "COMPLETED", "FAILED", "CANCELLED"},
}
EMERGENCY_CANCEL_REASON = "OPERATOR_REQUESTED_CANCELLATION"
_UNAVAILABLE_SECRET_SCAN_CODES = frozenset({
    "CREDENTIAL_KEY_UNAVAILABLE", "CREDENTIAL_KEY_PERMISSIONS", "CREDENTIAL_KEY_INVALID",
    "CREDENTIAL_DECRYPTION_FAILED", "CRYPTO_UNAVAILABLE",
})


@dataclass(frozen=True)
class WorkerIdentity:
    worker_id: str
    lease_token: str
    generation: int
    work_token: str


def public(row):
    hidden = {"encrypted_secret", "lease_token_hash", "token_hash", "content"}
    def encode(value):
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        return value
    return {c.name: encode(getattr(row, c.name)) for c in row.__table__.columns if c.name not in hidden}


def enabled():
    if not getattr(get_settings(), "cloud_enabled", False):
        raise HTTPException(503, "Cloud execution is disabled; historical reads and Local synchronization remain available")


async def clock(db):
    return await db.scalar(select(func.clock_timestamp()))


async def project(db, project_id, *, lock=False, include_deleted=False):
    query = select(Project).where(Project.id == project_id)
    if lock:
        # Management DELETE holds the conflicting exclusive Project lock. Keep
        # this admission lock through commit, before any Cloud operation/Task lock.
        query = query.with_for_update(read=True)
    row = await db.scalar(query.execution_options(populate_existing=True))
    if row is None or (row.deleted_at is not None and not include_deleted):
        raise HTTPException(404, "Project not found")
    return row


async def _lock(db, name):
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": name})


async def _task(db, task_id, project_id=None, lock=False):
    query = select(CloudTask).where(CloudTask.id == task_id)
    if lock:
        query = query.with_for_update()
    task = await db.scalar(query.execution_options(populate_existing=True))
    if task is None or (project_id is not None and task.project_id != project_id):
        raise HTTPException(404, "Cloud task not found in Project")
    return task


async def _attempt(db, task, attempt_id):
    attempt = await db.scalar(select(CloudAttempt).where(CloudAttempt.id == attempt_id).with_for_update())
    if attempt is None or attempt.task_id != task.id or task.latest_attempt_id != attempt.id:
        raise HTTPException(409, "Attempt is not the current attempt of this Task")
    return attempt


async def _current_grant(db, grant_id, project_id):
    if grant_id:
        from hypertest.domain.interactive import InteractiveIntegrationGrant
        grant = await db.get(InteractiveIntegrationGrant, grant_id, populate_existing=True)
        await interactive.authenticate_integration_record(db, grant, "cloud:dispatch", project_id=project_id)


async def worker_authority(db, task, attempt, identity):
    if identity is None:
        raise HTTPException(403, "A target-bound cloud:work capability is required")
    now = await clock(db)
    grant = await db.scalar(select(CloudWorkGrant).where(CloudWorkGrant.token_hash == token_hash(identity.work_token)))
    if (grant is None or grant.attempt_id != attempt.id or grant.project_id != task.project_id
            or grant.worker_id != identity.worker_id or grant.lease_generation != identity.generation
            or grant.revoked_at is not None or not now < grant.expires_at
            or attempt.lease_owner != identity.worker_id or attempt.lease_generation != identity.generation
            or attempt.lease_token_hash != token_hash(identity.lease_token)
            or attempt.lease_expires_at is None or not now < attempt.lease_expires_at
            or attempt.status in TERMINAL or attempt.status in {"WAITING_INPUT", "RECOVERY_REQUIRED"}):
        raise HTTPException(409, "Cloud worker capability or lease is stale")
    await _current_grant(db, attempt.authorization_grant_id, task.project_id)
    config = await _configuration(db, task.project_id, task.config_id)
    authorize_cloud_environment(config.configuration)


def authorize_cloud_environment(configuration):
    """An environment restriction can only remove Cloud admission paths."""
    environment = configuration["environment"]
    policy = environment.get("cloud_access_policy")
    if policy not in (None, "LOCAL_ONLY", "WEB_ONLY"):
        raise HTTPException(403, "CLOUD_ACCESS_POLICY_INVALID")
    if policy == "LOCAL_ONLY":
        raise HTTPException(403, "LOCAL_MODE_REQUIRED")
    if policy == "WEB_ONLY" and environment.get("connection") != "HTTPS":
        raise HTTPException(403, "CLOUD_WEB_ONLY")


async def _credential_versions(db, config, *, now=None):
    rows = []
    for role, resource in (("SUT", config["sut"]), ("FRAMEWORK", config["framework"]), ("ENVIRONMENT", config["environment"])):
        ref = resource.get("credential_version_id")
        if not ref:
            continue
        version = await db.get(CredentialVersion, UUID(ref))
        credential = await db.scalar(select(ProjectCredential).where(
            ProjectCredential.id == version.credential_id).with_for_update(read=True)
            .execution_options(populate_existing=True)) if version else None
        if role == "ENVIRONMENT":
            from .cloud_ssh import exact_target
            target = exact_target(resource)
        else:
            target = resource.get("url")
        if not version or not credential or credential.status != "ACTIVE" or (now and version.expires_at and version.expires_at <= now):
            raise HTTPException(409, "Referenced credential is unavailable or revoked")
        if target not in credential.allowed_targets:
            raise HTTPException(403, "Credential is not authorized for the exact resource target")
        action = "git:read" if role in {"SUT", "FRAMEWORK"} else "environment:read"
        if action not in credential.allowed_actions:
            raise HTTPException(403, "Credential does not permit this resource operation")
        if role in {"SUT", "FRAMEWORK"} and credential.kind not in {"GIT_TOKEN", "GIT_SSH_KEY"}:
            raise HTTPException(422, "Repository credential has incompatible purpose")
        if role == "ENVIRONMENT" and resource.get("connection") == "SSH" and credential.kind != "SSH_KEY":
            raise HTTPException(422, "SSH authentication requires an SSH credential")
        rows.append((role, version, credential))
    return rows


async def _configuration(db, project_id, config_id):
    config = await db.get(ProjectCloudConfigRevision, config_id)
    if config is None or config.project_id != project_id:
        raise HTTPException(404, "Cloud configuration not found in Project")
    for _, version, _ in await _credential_versions(db, config.configuration, now=await clock(db)):
        if version.project_id != project_id:
            raise HTTPException(403, "Credential belongs to another Project")
    return config


def _authorize_input_reads(task_inputs, configuration, now):
    """Apply the original DRAFT grant before even narrow Git preflight I/O."""
    authorize_cloud_environment(configuration)
    authorization = task_inputs["authorization"]
    targets = set(authorization["targets"])
    required_targets = {configuration[role]["url"] for role in ("sut", "framework")}
    if configuration["environment"].get("host"):
        from .cloud_ssh import exact_target
        required_targets.add(exact_target(configuration["environment"]))
    expires_at = datetime.fromisoformat(authorization["expires_at"].replace("Z", "+00:00"))
    if (not required_targets <= targets or "git:read" not in authorization["permitted_actions"]
            or expires_at <= now):
        raise HTTPException(403, "Original input authorization does not permit current repository preflight")


# Credential plaintext is never included in an ordinary request digest, receipt,
# snapshot, audit or exception. A keyed fingerprint distinguishes changed secrets
# on replay without exposing an offline guessable unsalted secret hash.
def _cipher():
    from hypertest.cloud.crypto import CredentialCipher
    path = getattr(get_settings(), "cloud_credential_key_file", None)
    if not path:
        raise HTTPException(503, "Cloud credential encryption is not configured")
    return CredentialCipher.from_key_file(path)


def _safe_payload(payload):
    data = payload.model_dump(mode="json")
    data.pop("secret", None)
    if payload.operation == "UPLOAD_ARTIFACT":
        data.pop("content_base64", None)
    return data


def _contains_secret(value, secret):
    """Inspect decoded values so JSON escaping cannot hide a credential match."""
    if isinstance(value, str):
        content = value.encode()
        return bool(secret) and (secret in content or base64.b64encode(secret) in content)
    if isinstance(value, dict):
        return any(_contains_secret(key, secret) or _contains_secret(item, secret)
                   for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item, secret) for item in value)
    return False


async def _reject_secrets(db, project_id, values):
    """Admission guard supplements runtime filtering, including exact canaries."""
    encoded = json.dumps(values, ensure_ascii=False).encode()
    if re.search(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----|(?:gh[pousr]_|glpat-)[A-Za-z0-9_-]{16,}", encoded):
        raise HTTPException(422, "Potential secret material is not an accepted testing artifact")
    versions = list(await db.scalars(select(CredentialVersion).where(CredentialVersion.project_id == project_id)))
    if versions:
        cipher = _cipher()
        for version in versions:
            credential = await db.get(ProjectCredential, version.credential_id)
            context = {"project_id": str(project_id), "credential_id": str(credential.id), "version": version.version, "purpose": credential.purpose}
            secret = cipher.decrypt(version.encrypted_secret, context=context)
            if _contains_secret(values, secret):
                raise HTTPException(422, "Credential material is not an accepted testing artifact")


async def _snapshot(db, task):
    result = {"profile": PROFILE, "task_kind": "CLOUD_TASK", "product_mode": "CLOUD", "task": public(task)}
    for key, model in (("attempts", CloudAttempt), ("resolutions", CloudInputResolution),
                       ("assets", CloudAssetRevision), ("artifacts", CloudArtifact), ("runs", CloudRunRecord),
                       ("run_cases", CloudRunCase), ("delegations", CloudDelegation),
                       ("questions", CloudInputRequest), ("answers", CloudInputAnswer)):
        rows = list(await db.scalars(select(model).where(model.task_id == task.id).order_by(model.id)))
        result[key] = [public(row) for row in rows]
    asset_ids = [UUID(row["id"]) for row in result["assets"]]
    result["asset_references"] = [public(row) for row in await db.scalars(select(CloudAssetReference).where(CloudAssetReference.asset_id.in_(asset_ids)))] if asset_ids else []
    run_ids = [UUID(row["id"]) for row in result["runs"]]
    result["run_artifacts"] = [public(row) for row in await db.scalars(select(CloudRunArtifact).where(CloudRunArtifact.run_id.in_(run_ids)))] if run_ids else []
    delegation_ids = [UUID(row["id"]) for row in result["delegations"]]
    result["delegation_assets"] = [public(row) for row in await db.scalars(select(CloudDelegationAsset).where(CloudDelegationAsset.delegation_id.in_(delegation_ids)))] if delegation_ids else []
    from .cloud_ssh import terminal_results
    result["remote_operation_results"] = await terminal_results(db, task.id)
    return result


def _events(db, project_id, actor_ref, operation, entity_id, response):
    metadata = {key: value for key, value in response.items() if key not in {"configuration", "task_snapshot"}}
    db.add(AuditEvent(project_id=project_id, actor_type="WORKER" if actor_ref.startswith("worker:") else "USER", actor_ref=actor_ref,
        action="cloud." + operation.lower(), entity_type="CloudTask", entity_id=entity_id, event_metadata=metadata))
    db.add(OutboxEvent(aggregate_type="CloudTask", aggregate_id=entity_id or project_id,
        event_type="cloud." + operation.lower(), payload=metadata))


async def mutate(db, payload, actor_ref, *, authorization_check=None, worker=None, grant_id=None):
    """One immutable key / optimistic version / current authority / transaction."""
    await project(db, payload.project_id, lock=True)
    await _lock(db, f"cloud-operation:{payload.project_id}:{payload.operation_key}")
    if authorization_check:
        await authorization_check()
    safe = _safe_payload(payload)
    if payload.operation == "STORE_CREDENTIAL":
        secret_value = payload.secret.get_secret_value().encode()
        if _contains_secret(safe, secret_value):
            raise HTTPException(422, "Credential secret cannot appear in readable metadata")
        await _reject_secrets(db, payload.project_id, safe)
        cipher = _cipher()
        # Ciphertext does not belong to normal business persistence; only this
        # keyed fingerprint is used to detect a conflicting secret on replay.
        # A keyed identity distinguishes changed secrets without copying their
        # plaintext or randomized ciphertext into the operation journal.
        from hypertest.cloud.crypto import credential_fingerprint
        safe["secret_fingerprint"] = credential_fingerprint(cipher, payload.secret.get_secret_value())
    digest = canonical_json_sha256(safe)
    prior = await db.scalar(select(CloudOperationReceipt).where(CloudOperationReceipt.project_id == payload.project_id,
        CloudOperationReceipt.operation_key == payload.operation_key))
    if prior:
        if prior.actor_ref != actor_ref or prior.input_digest != digest or prior.operation != payload.operation:
            raise HTTPException(409, "Cloud operation key conflicts with its original actor or request")
        return prior.response
    if payload.operation not in {"CANCEL_TASK", "CANCEL_ATTEMPT", "ANSWER_INPUT", "RECONCILE_ATTEMPT", "REVOKE_CREDENTIAL"}:
        enabled()
    fixed_control_fallback = False
    if payload.operation not in {"STORE_CREDENTIAL", "REVOKE_CREDENTIAL"}:
        from hypertest.cloud.errors import CloudBlocked
        try:
            await _reject_secrets(db, payload.project_id, safe)
        except (CloudBlocked, HTTPException) as error:
            unavailable = (
                isinstance(error, CloudBlocked) and error.code in _UNAVAILABLE_SECRET_SCAN_CODES
            ) or (
                isinstance(error, HTTPException) and error.status_code == 503
                and error.detail == "Cloud credential encryption is not configured"
            )
            if (not unavailable or payload.operation not in {"CANCEL_TASK", "CANCEL_ATTEMPT"}
                    or payload.reason != EMERGENCY_CANCEL_REASON
                    or not re.fullmatch(r"(?:web|cancel):[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", payload.operation_key)):
                raise
            # The strict cancellation schema allows only target/key/version and
            # this public fixed reason. Preserve the original full digest/key;
            # no unscanned free text, answer or reconciliation is persisted.
            fixed_control_fallback = True
    task = attempt = None
    if hasattr(payload, "task_id"):
        task = await _task(db, payload.task_id, payload.project_id, lock=True)
        if payload.expected_version != task.version:
            raise HTTPException(409, "Cloud Task version is stale")
        if hasattr(payload, "attempt_id"):
            attempt = await _attempt(db, task, payload.attempt_id)
        if SCOPES[payload.operation] == "cloud:work":
            await worker_authority(db, task, attempt, worker)
    version = task.version + 1 if task else payload.expected_version + 1
    refs = {}
    op = payload.operation
    if op == "CONFIGURE":
        await _lock(db, f"cloud-config:{payload.project_id}")
        latest = await db.scalar(select(func.max(ProjectCloudConfigRevision.revision)).where(ProjectCloudConfigRevision.project_id == payload.project_id)) or 0
        if latest != payload.expected_version:
            raise HTTPException(409, "Cloud configuration version is stale")
        configuration = payload.configuration.model_dump(mode="json")
        credentials = await _credential_versions(db, configuration, now=await clock(db))
        if any(row.project_id != payload.project_id for _, row, _ in credentials):
            raise HTTPException(403, "Cross-Project credential reference")
        config = ProjectCloudConfigRevision(id=uuid7(), project_id=payload.project_id, revision=latest + 1,
            configuration=configuration, digest=canonical_json_sha256(configuration), created_by=actor_ref)
        db.add(config)
        await db.flush()
        for role, credential, _ in credentials:
            db.add(CloudConfigCredential(project_id=payload.project_id, config_id=config.id, credential_version_id=credential.id, role=role))
        version = config.revision
        refs = {"config_id": str(config.id)}
    elif op in {"STORE_CREDENTIAL", "REVOKE_CREDENTIAL"}:
        await _lock(db, f"cloud-credentials:{payload.project_id}")
        credential = await db.get(ProjectCredential, payload.credential_id) if payload.credential_id else None
        if payload.credential_id and (credential is None or credential.project_id != payload.project_id):
            raise HTTPException(404, "Credential not found in Project")
        current = credential.version if credential else 0
        if current != payload.expected_version:
            raise HTTPException(409, "Credential version is stale")
        if op == "REVOKE_CREDENTIAL":
            if credential is None:
                raise HTTPException(404, "Credential not found")
            credential.status = "REVOKED"
            credential.version += 1
            refs = {"credential_id": str(credential.id), "credential_status": "REVOKED"}
        else:
            if credential and (credential.kind != payload.kind or credential.purpose != payload.purpose or credential.allowed_targets != payload.allowed_targets or credential.allowed_actions != payload.allowed_actions):
                raise HTTPException(409, "Credential rotation cannot change its immutable purpose or target scope")
            if credential and credential.status != "ACTIVE":
                raise HTTPException(409, "Revoked credential cannot be reactivated")
            if credential is None:
                credential = ProjectCredential(id=uuid7(), project_id=payload.project_id, kind=payload.kind, label=payload.label,
                    purpose=payload.purpose, allowed_targets=payload.allowed_targets, allowed_actions=payload.allowed_actions,
                    version=1, status="ACTIVE", created_by=actor_ref)
                db.add(credential)
            else:
                credential.version += 1
            await db.flush()
            context = {"project_id": str(payload.project_id), "credential_id": str(credential.id), "version": credential.version, "purpose": credential.purpose}
            envelope = _cipher().encrypt(payload.secret.get_secret_value(), context=context)
            cv = CredentialVersion(id=uuid7(), project_id=payload.project_id, credential_id=credential.id, version=credential.version,
                encrypted_secret=envelope, key_id=get_settings().cloud_credential_key_id,
                expires_at=payload.expires_at, created_by=actor_ref)
            db.add(cv)
            refs = {"credential_id": str(credential.id), "credential_version_id": str(cv.id)}
        version = credential.version
    elif op == "CREATE_TASK":
        if payload.expected_version != 0:
            raise HTTPException(409, "New Cloud Task requires expected_version=0")
        config = await _configuration(db, payload.project_id, payload.config_id)
        authorize_cloud_environment(config.configuration)
        if payload.related_task_id:
            await _task(db, payload.related_task_id, payload.project_id)
        task = CloudTask(id=uuid7(), project_id=payload.project_id, owner_actor_ref=actor_ref, title=payload.title,
            config_id=payload.config_id, inputs=payload.inputs.model_dump(mode="json"), status="DRAFT", version=1,
            reported_result="NOT_RUN", related_task_id=payload.related_task_id)
        db.add(task)
        version = 1
    elif op == "UPDATE_TASK":
        if task.status != "DRAFT" or task.frozen_manifest:
            raise HTTPException(409, "Only an undispatched DRAFT can be edited")
        config = await _configuration(db, payload.project_id, payload.config_id)
        authorize_cloud_environment(config.configuration)
        task.title, task.inputs, task.config_id = payload.title, payload.inputs.model_dump(mode="json"), payload.config_id
    elif op == "RESOLVE_INPUTS":
        if task.status != "DRAFT" or task.frozen_manifest:
            raise HTTPException(409, "Only DRAFT accepts input resolution")
        config = await _configuration(db, task.project_id, task.config_id)
        _authorize_input_reads(task.inputs, config.configuration, await clock(db))
        resolution = CloudInputResolution(id=uuid7(), project_id=task.project_id, task_id=task.id,
            operation_key=payload.operation_key, source_draft_version=version,
            source_digest=canonical_json_sha256({"inputs": task.inputs, "config_id": str(task.config_id), "config_digest": config.digest}),
            status="PENDING", requested_by=actor_ref, grant_id=grant_id)
        db.add(resolution)
        refs = {"resolution_id": str(resolution.id), "resolution_status": "PENDING"}
    elif op == "DISPATCH":
        config = await _configuration(db, task.project_id, task.config_id)
        _authorize_input_reads(task.inputs, config.configuration, await clock(db))
        environment = config.configuration["environment"]
        if environment.get("ssh_access") is not None:
            from .cloud_ssh import authorize_environment
            authorize_environment(task, environment, await clock(db))
        if task.status == "DRAFT":
            resolution = await db.get(CloudInputResolution, payload.resolution_id)
            expected_digest = canonical_json_sha256({"inputs": task.inputs, "config_id": str(task.config_id), "config_digest": config.digest})
            if (not resolution or resolution.task_id != task.id or resolution.status != "ACCEPTED"
                    or resolution.accepted_task_version != task.version or resolution.source_digest != expected_digest):
                raise HTTPException(409, "Dispatch requires an accepted immutable resolution for this exact DRAFT version")
            manifest = {"profile": PROFILE, "project_id": str(task.project_id), "cloud_task_id": str(task.id),
                "config_id": str(config.id), "config_revision": config.revision, "configuration": config.configuration,
                "inputs": task.inputs, "resolution": resolution.result, "resolution_id": str(resolution.id),
                "prd_sha256": hashlib.sha256(task.inputs["prd_markdown"].encode()).hexdigest()}
            task.frozen_manifest, task.input_digest = manifest, canonical_json_sha256(manifest)
        else:
            old = await db.get(CloudAttempt, task.latest_attempt_id) if task.latest_attempt_id else None
            if not task.frozen_manifest or not old or old.id != payload.retry_of_attempt_id or old.status not in TERMINAL:
                raise HTTPException(409, "Explicit retry requires the terminal latest Attempt and its frozen input")
            if old.checkpoint.get("pending_operation_keys") or old.checkpoint.get("external_operations_reconciled") is False:
                raise HTTPException(409, "Unreconciled external operations prevent retry")
            from .cloud_ssh import ensure_remote_closed
            await ensure_remote_closed(db, task_id=task.id)
        authorization = task.inputs["authorization"]
        if datetime.fromisoformat(authorization["expires_at"].replace("Z", "+00:00")) <= await clock(db):
            raise HTTPException(403, "Frozen execution authorization expired")
        count, seconds, cost = await _task_budget_usage(db, task.id)
        budgets = task.inputs["budgets"]
        if count >= budgets["max_attempts"] or seconds >= budgets["total_seconds"] or cost >= budgets["total_cost_microunits"]:
            raise HTTPException(409, "Cloud Task cumulative budget is exhausted")
        if await db.scalar(select(CloudAttempt.id).where(CloudAttempt.task_id == task.id, CloudAttempt.status.not_in(TERMINAL))):
            raise HTTPException(409, "Task already has an unfinished Attempt")
        attempt = CloudAttempt(id=uuid7(), task_id=task.id, project_id=task.project_id, attempt_no=count + 1,
            input_digest=task.input_digest, status="QUEUED", reported_result="NOT_RUN", lease_generation=0,
            checkpoint={}, runtime_metadata={}, usage_seconds=0, cost_microunits=0, authorization_grant_id=grant_id)
        db.add(attempt)
        await db.flush()
        task.latest_attempt_id, task.status, task.reported_result = attempt.id, "QUEUED", "NOT_RUN"
        refs = {"attempt_id": str(attempt.id), "input_digest": task.input_digest}
    elif op == "CANCEL_TASK":
        if task.status != "DRAFT" or task.latest_attempt_id is not None:
            raise HTTPException(409, "Task cancellation requires an undispatched DRAFT")
        task.status = "CANCELLED"
        for resolution in await db.scalars(select(CloudInputResolution).where(
                CloudInputResolution.task_id == task.id, CloudInputResolution.status.in_(["PENDING", "RESOLVING"]))):
            resolution.status = "RECOVERY_REQUIRED" if resolution.status == "RESOLVING" else "FAILED"
            for capability in await db.scalars(select(CloudWorkGrant).where(
                    CloudWorkGrant.resolution_id == resolution.id, CloudWorkGrant.revoked_at.is_(None))):
                capability.revoked_at = await clock(db)
    elif op == "CANCEL_ATTEMPT":
        if attempt.status in TERMINAL:
            raise HTTPException(409, "Terminal Attempts are immutable")
        target = "CANCELLED" if attempt.status == "QUEUED" and attempt.lease_owner is None else "RECOVERY_REQUIRED"
        await _fence(db, attempt)
        _state(task, attempt, target, payload.reason, await clock(db))
        checkpoint = dict(attempt.checkpoint)
        checkpoint["cancellation_requested"] = True
        attempt.checkpoint = checkpoint
    elif op == "RESUME_ATTEMPT":
        from .cloud_ssh import ensure_remote_closed
        await ensure_remote_closed(db, task_id=task.id)
        if attempt.status not in {"WAITING_INPUT", "RECOVERY_REQUIRED"}:
            raise HTTPException(409, "Only waiting or recovery Attempt may resume explicitly")
        proof = payload.reconciliation
        if not all(proof.get(key) is True for key in ("old_owner_fenced", "local_processes_stopped", "external_operations_reconciled", "checkpoint_verified")) or not proof.get("observations"):
            raise HTTPException(409, "Resume requires observed reconciliation and a verified runtime checkpoint")
        if not attempt.checkpoint.get("runtime_context"):
            raise HTTPException(409, "No recoverable runtime context exists")
        unanswered = await db.scalar(select(CloudInputRequest.id).where(CloudInputRequest.attempt_id == attempt.id,
            ~select(CloudInputAnswer.id).where(CloudInputAnswer.question_id == CloudInputRequest.id).exists()))
        if unanswered:
            raise HTTPException(409, "Input questions remain unanswered")
        await _fence(db, attempt)
        attempt.runtime_metadata = {**attempt.runtime_metadata, "resume_reconciliation": proof}
        _state(task, attempt, "PREPARING", payload.reason, await clock(db))
    elif op == "RECONCILE_ATTEMPT":
        from .cloud_ssh import ensure_remote_closed
        await ensure_remote_closed(db, task_id=task.id)
        if attempt.status != "RECOVERY_REQUIRED":
            raise HTTPException(409, "Only recovery Attempts accept explicit terminal reconciliation")
        proof = payload.reconciliation
        if (not all(proof.get(key) is True for key in
                    ("old_owner_fenced", "local_processes_stopped", "external_operations_reconciled"))
                or not isinstance(proof.get("observations"), str) or not proof["observations"].strip()
                or proof.get("pending_operation_keys")):
            raise HTTPException(409, "Reconciliation requires observed stopping and no unresolved external operations")
        await _fence(db, attempt)
        attempt.checkpoint = {**attempt.checkpoint, "reconciliation": proof,
                              "pending_operation_keys": [], "external_operations_reconciled": True}
        _state(task, attempt, payload.status, payload.reason, await clock(db))
    elif op == "ANSWER_INPUT":
        question = await db.get(CloudInputRequest, payload.question_id)
        if not question or question.attempt_id != attempt.id or attempt.status != "WAITING_INPUT":
            raise HTTPException(409, "Question does not belong to the waiting Attempt")
        db.add(CloudInputAnswer(task_id=task.id, question_id=question.id, task_version=version, answer=payload.answer, answered_by=actor_ref))
    elif op == "TRANSITION":
        if payload.status == "FAILED":
            from .cloud_ssh import ensure_remote_closed
            await ensure_remote_closed(db, task_id=task.id)
        if payload.status == "FAILED" and attempt.checkpoint.get("pending_operation_keys"):
            raise HTTPException(409, "Pending external operations require recovery")
        if payload.status == "RUNNING":
            if payload.budget_reservation is None:
                raise HTTPException(409, "RUNNING requires a durable Worker budget reservation")
            await _reserve_budget(db, task, attempt, payload, worker)
        attempt.runtime_metadata = {**attempt.runtime_metadata, **payload.runtime_metadata}
        if payload.checkpoint is not None:
            attempt.checkpoint = {**attempt.checkpoint, "runtime_context": payload.checkpoint}
        _usage(attempt, payload.usage_seconds, payload.cost_microunits)
        if payload.budget_settlement is not None:
            await _settle_budget(db, attempt, payload, worker)
        # Settlement queries may autoflush. Keep the Attempt nonterminal until
        # its complete accounting is ready, then fence before the first flush
        # of the terminal state; the database forbids any later terminal edit.
        _state(task, attempt, payload.status, payload.reason, await clock(db))
        if payload.status in TERMINAL or payload.status == "RECOVERY_REQUIRED":
            await _fence(db, attempt)
    elif op == "SUBMIT_ASSETS":
        refs = await _assets(db, task, attempt, payload, version)
    elif op == "UPLOAD_ARTIFACT":
        try:
            content = base64.b64decode(payload.content_base64, validate=True)
            content.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(422, "Artifact requires valid base64 UTF-8 original bytes") from None
        if len(content) != payload.byte_count or hashlib.sha256(content).hexdigest() != payload.sha256:
            raise HTTPException(422, "Artifact original byte count or hash mismatch")
        await _reject_secrets(db, task.project_id, content.decode("utf-8"))
        artifact = CloudArtifact(id=uuid7(), task_id=task.id, project_id=task.project_id, attempt_id=attempt.id,
            filename=payload.filename, media_type=payload.media_type, byte_count=len(content), sha256=payload.sha256,
            content=content, verified_at=await clock(db))
        db.add(artifact)
        await db.flush()
        stored = await db.scalar(select(CloudArtifact.content).where(CloudArtifact.id == artifact.id))
        if stored != content or hashlib.sha256(stored).hexdigest() != artifact.sha256:
            raise HTTPException(409, "Persisted Artifact readback failed")
        refs = {"artifact_id": str(artifact.id), "sha256": artifact.sha256, "byte_count": artifact.byte_count}
    elif op == "SUBMIT_RUN":
        refs = await _run(db, task, attempt, payload, version)
    elif op == "SUBMIT_DELEGATION":
        refs = await _delegation(db, task, attempt, payload, version)
    elif op == "REQUEST_INPUT":
        from .cloud_ssh import ensure_remote_closed
        await ensure_remote_closed(db, task_id=task.id)
        if not payload.local_processes_stopped or not payload.external_operations_reconciled:
            raise HTTPException(409, "Unstopped or uncertain operations require RECOVERY_REQUIRED")
        if payload.required_action not in task.inputs["authorization"]["permitted_actions"]:
            raise HTTPException(403, "Input cannot expand the frozen authorization; create a related Task")
        question = CloudInputRequest(id=uuid7(), task_id=task.id, attempt_id=attempt.id, task_version=version,
            question_key=payload.question_key, question=payload.question, options=payload.options,
            checkpoint=payload.checkpoint, required_action=payload.required_action)
        db.add(question)
        attempt.checkpoint = {**attempt.checkpoint, "runtime_context": payload.checkpoint}
        _state(task, attempt, "WAITING_INPUT", "Input required", await clock(db))
        await _fence(db, attempt)
        refs = {"question_id": str(question.id)}
    elif op == "COMPLETE_ATTEMPT":
        await _finish(db, task, attempt, payload)
        _usage(attempt, payload.usage_seconds, payload.cost_microunits)
        if payload.budget_settlement is not None:
            await _settle_budget(db, attempt, payload, worker)
        _state(task, attempt, "COMPLETED", "Explicit manifest accepted", await clock(db))
        attempt.reported_result = task.reported_result = payload.reported_result
        attempt.checkpoint = {**attempt.checkpoint, "final_report_revision": str(payload.final_report_revision),
            "completion_manifest": payload.completion_manifest.model_dump(mode="json")}
        await _fence(db, attempt)
    else:
        raise HTTPException(422, "Unsupported Cloud operation")
    if task:
        task.version = version
        task.updated_at = await clock(db)
    await db.flush()
    if worker is not None and op not in {"REQUEST_INPUT", "COMPLETE_ATTEMPT"} and attempt and attempt.status not in TERMINAL | {"RECOVERY_REQUIRED"}:
        await worker_authority(db, task, attempt, worker)
    if authorization_check:
        await authorization_check()
    response = {"status": "ACCEPTED", "profile": PROFILE, "project_id": str(payload.project_id),
        "operation_key": payload.operation_key, "operation": op, "version": version,
        "task_id": str(task.id) if task else None, **refs}
    if fixed_control_fallback:
        response["safety_control"] = "FIXED_CANCELLATION_WITH_SECRET_SCAN_UNAVAILABLE"
    if attempt:
        response["attempt_id"] = str(attempt.id)
        response["checkpoint"] = attempt.checkpoint
    snapshot = await _snapshot(db, task) if task else None
    db.add(CloudOperationReceipt(id=uuid7(), project_id=payload.project_id, task_id=task.id if task else None,
        attempt_id=attempt.id if attempt else None, operation_key=payload.operation_key, operation=op,
        actor_ref=actor_ref, input_digest=digest, expected_version=payload.expected_version,
        accepted_version=version, response=response, task_snapshot=snapshot))
    _events(db, payload.project_id, actor_ref, op, task.id if task else None, response)
    await db.commit()
    return response


def _state(task, attempt, target, reason, now):
    if target not in ALLOWED.get(attempt.status, set()):
        raise HTTPException(409, "Illegal Cloud Attempt state transition")
    attempt.status = task.status = target
    attempt.reason = reason
    if target == "RUNNING" and attempt.started_at is None:
        attempt.started_at = now
    if target in TERMINAL:
        attempt.ended_at = now


def _usage(attempt, seconds, cost):
    if seconds < attempt.usage_seconds or cost < attempt.cost_microunits:
        raise HTTPException(409, "Attempt cumulative usage cannot decrease")
    attempt.usage_seconds, attempt.cost_microunits = seconds, cost


def _reservation_charge(reservation):
    """A HELD reservation is a limit commitment, never observed expenditure."""
    try:
        if not isinstance(reservation, dict) or reservation.get("profile") != "cloud-budget-reservation/v1alpha1":
            raise ValueError()
        typed = CloudBudgetReservation.model_validate({
            "accounting_unit": reservation.get("accounting_unit", "CONSERVATIVE_MICROUNITS"),
            "reserved_seconds": reservation["reserved_seconds"],
            "request_limits": reservation["request_limits"],
        })
        cost = sum(item.max_requests * item.cost_per_request_microunits for item in typed.request_limits)
        if reservation.get("reserved_cost_microunits") != cost or reservation.get("state") not in {"HELD", "SETTLED"}:
            raise ValueError()
        if reservation["state"] == "SETTLED":
            proof = reservation.get("settlement")
            if not isinstance(proof, dict):
                raise ValueError()
            observed = CloudBudgetSettlement.model_validate({key: proof[key] for key in CloudBudgetSettlement.model_fields})
            limits = {item.scope: item for item in typed.request_limits}
            counts = {item.scope: item.requests for item in observed.requests}
            if (observed.accounting_unit != typed.accounting_unit or set(counts) != set(limits)
                    or any(counts[scope] > limits[scope].max_requests for scope in counts)):
                raise ValueError()
            observed_cost = sum(counts[scope] * limits[scope].cost_per_request_microunits for scope in counts)
            if proof.get("observed_cost_microunits") != observed_cost:
                raise ValueError()
            return observed.observed_seconds, observed_cost
        return typed.reserved_seconds, cost
    except (KeyError, TypeError, ValueError):
        raise HTTPException(409, "Budget reservation cannot be safely interpreted") from None


def effective_budget_usage(attempt):
    """Charge max(observed, held); lost leases and reconciliation never erase holds."""
    reservation = attempt.runtime_metadata.get("budget_reservation")
    if reservation is not None:
        held_seconds, held_cost = _reservation_charge(reservation)
    else:
        preparation = attempt.runtime_metadata.get("preparation_budget_reservation")
        held_seconds, held_cost = 0, 0
        if preparation is not None:
            if (not isinstance(preparation, dict) or preparation.get("state") != "HELD"
                    or type(preparation.get("reserved_seconds")) is not int or preparation["reserved_seconds"] < 1):
                raise HTTPException(409, "Preparation budget reservation cannot be safely interpreted")
            held_seconds = preparation["reserved_seconds"]
    return max(attempt.usage_seconds, held_seconds), max(attempt.cost_microunits, held_cost)


async def _task_budget_usage(db, task_id, *, exclude_attempt_id=None):
    rows = await db.scalars(select(CloudAttempt).where(CloudAttempt.task_id == task_id))
    count, seconds, cost = 0, 0, 0
    for row in rows:
        count += 1
        if row.id != exclude_attempt_id:
            charged_seconds, charged_cost = effective_budget_usage(row)
            seconds += charged_seconds
            cost += charged_cost
    return count, seconds, cost


async def _reserve_budget(db, task, attempt, payload, worker):
    if worker is None or attempt.status != "PREPARING" or attempt.runtime_metadata.get("budget_reservation") is not None:
        raise HTTPException(409, "A budget reservation requires the current preparing Worker and no prior hold")
    typed = payload.budget_reservation
    preparation = attempt.runtime_metadata.get("preparation_budget_reservation", {})
    if typed.reserved_seconds < preparation.get("reserved_seconds", 0):
        raise HTTPException(409, "Execution reservation must include the complete preparation deadline")
    reserved_cost = sum(item.max_requests * item.cost_per_request_microunits for item in typed.request_limits)
    _, seconds, cost = await _task_budget_usage(db, task.id, exclude_attempt_id=attempt.id)
    budgets = task.inputs["budgets"]
    if typed.accounting_unit != budgets.get("accounting_unit", "CONSERVATIVE_MICROUNITS"):
        raise HTTPException(409, "Reservation accounting unit differs from the frozen task budget")
    if (seconds + max(typed.reserved_seconds, attempt.usage_seconds, payload.usage_seconds) > budgets["total_seconds"]
            or cost + max(reserved_cost, attempt.cost_microunits, payload.cost_microunits) > budgets["total_cost_microunits"]):
        raise HTTPException(409, "Cloud Task cumulative budget cannot cover this reservation")
    record = {**typed.model_dump(mode="json"), "profile": "cloud-budget-reservation/v1alpha1",
        "state": "HELD", "reserved_cost_microunits": reserved_cost,
        "operation_key": payload.operation_key, "lease_generation": worker.generation,
        "reserved_at": (await clock(db)).isoformat()}
    attempt.runtime_metadata = {**attempt.runtime_metadata, "budget_reservation": record}


async def _settle_budget(db, attempt, payload, worker):
    from .cloud_ssh import ensure_remote_closed
    await ensure_remote_closed(db, task_id=attempt.task_id)
    record = attempt.runtime_metadata.get("budget_reservation")
    if worker is None or not isinstance(record, dict) or record.get("state") != "HELD":
        raise HTTPException(409, "Settlement requires the current Worker and an outstanding reservation")
    _reservation_charge(record)
    settlement = payload.budget_settlement
    if settlement.accounting_unit != record.get("accounting_unit", "CONSERVATIVE_MICROUNITS"):
        raise HTTPException(409, "Settlement accounting unit differs from the reserved task budget")
    limits = {item["scope"]: item for item in record["request_limits"]}
    observed = {item.scope: item.requests for item in settlement.requests}
    if set(observed) != set(limits) or any(observed[scope] > limits[scope]["max_requests"] for scope in observed):
        raise HTTPException(409, "Observed model request counts do not match the reserved scopes or limits")
    observed_cost = sum(observed[scope] * limits[scope]["cost_per_request_microunits"] for scope in observed)
    if payload.usage_seconds != settlement.observed_seconds or payload.cost_microunits != observed_cost:
        raise HTTPException(409, "Observed usage must agree with complete stopped-broker accounting")
    # A Worker must observe its complete namespace stopped and every model broker
    # joined with no in-flight request. Missing proof leaves HELD, including after
    # CANCEL/lease loss/operator reconciliation. The original hold is retained.
    proof = {**settlement.model_dump(mode="json"), "observed_cost_microunits": observed_cost,
        "accounting_unit": record.get("accounting_unit", "CONSERVATIVE_MICROUNITS"),
        "accounting_basis": "OBSERVED_REQUEST_COUNTS_AT_RESERVED_RATE_NOT_PROVIDER_INVOICE",
        "operation_key": payload.operation_key, "lease_generation": worker.generation,
        "settled_at": (await clock(db)).isoformat()}
    metadata = {**attempt.runtime_metadata, "budget_reservation": {**record, "state": "SETTLED", "settlement": proof}}
    if "preparation_budget_reservation" in metadata:
        metadata["preparation_budget_reservation"] = {**metadata["preparation_budget_reservation"],
            "state": "SETTLED", "settlement_operation_key": payload.operation_key}
    attempt.runtime_metadata = metadata


async def _fence(db, attempt):
    attempt.lease_generation += 1
    attempt.lease_owner = attempt.lease_token_hash = attempt.lease_expires_at = None
    now = await clock(db)
    for grant in await db.scalars(select(CloudWorkGrant).where(CloudWorkGrant.attempt_id == attempt.id, CloudWorkGrant.revoked_at.is_(None))):
        grant.revoked_at = now


async def _asset(db, task_id, asset_id, *, kind=None):
    row = await db.get(CloudAssetRevision, asset_id)
    if row is None or row.task_id != task_id or (kind and row.kind != kind):
        raise HTTPException(422, "Asset revision does not belong to this Task or kind")
    return row


async def _artifact(db, task_id, artifact_id):
    row = await db.get(CloudArtifact, artifact_id)
    if row is None or row.task_id != task_id or not row.verified_at:
        raise HTTPException(422, "Accepted Artifact does not belong to this Task")
    if len(row.content) != row.byte_count or hashlib.sha256(row.content).hexdigest() != row.sha256:
        raise HTTPException(409, "Artifact bytes failed persisted integrity verification")
    return row


async def _assets(db, task, attempt, payload, version):
    accepted = []
    checkpoint_id = None
    for item in payload.assets:
        if item.artifact_id:
            await _artifact(db, task.id, item.artifact_id)
        for ref in item.referenced_asset_ids:
            await _asset(db, task.id, ref)
        if item.kind == "IMPLEMENTATION":
            details = item.details
            if details.get("framework_sha") != task.frozen_manifest["resolution"]["repositories"]["framework"]["commit_sha"]:
                raise HTTPException(422, "Implementation must identify its exact frozen framework baseline")
            if not all(key in details for key in ("cwd", "dirty_files", "untracked_files", "test_tree_digest")):
                raise HTTPException(422, "Implementation requires reconstructable test tree metadata")
            if (details["dirty_files"] or details["untracked_files"]) and not item.artifact_id:
                raise HTTPException(422, "Unpushed test changes require original complete patch or file Artifact")
        original = item.model_dump(mode="json")
        digest = canonical_json_sha256(original)
        prior = await db.scalar(select(CloudAssetRevision).where(CloudAssetRevision.task_id == task.id,
            CloudAssetRevision.kind == item.kind, CloudAssetRevision.key == item.key).order_by(CloudAssetRevision.revision.desc()).limit(1))
        if payload.checkpoint_report_key == item.key and item.kind == "REPORT" and prior and prior.attempt_id != attempt.id:
            raise HTTPException(409, "Progress REPORT key cannot be reused across Attempts")
        # Reuse requires the same true source Attempt, rather than relabeling a
        # previous Attempt's unchanged output as newly produced material.
        if prior and prior.content_digest == digest and prior.attempt_id == attempt.id:
            row = prior
        else:
            row = CloudAssetRevision(id=uuid7(), task_id=task.id, attempt_id=attempt.id, kind=item.kind, key=item.key,
                revision=prior.revision + 1 if prior else 1, task_version=version, title=item.title,
                markdown=item.markdown, details=item.details, artifact_id=item.artifact_id,
                reported_result=item.reported_result, source=item.source, content_digest=digest)
            db.add(row)
            await db.flush()
            for ref in set(item.referenced_asset_ids):
                db.add(CloudAssetReference(task_id=task.id, asset_id=row.id, referenced_asset_id=ref))
        accepted.append({"id": str(row.id), "kind": row.kind, "key": row.key, "revision": row.revision})
        if payload.checkpoint_report_key == item.key and item.kind == "REPORT":
            checkpoint_id = row.id
    if checkpoint_id:
        attempt.checkpoint = {**attempt.checkpoint, "progress_report_revision": str(checkpoint_id)}
    return {"assets": accepted}


async def _run(db, task, attempt, payload, version):
    if await db.scalar(select(CloudRunRecord.id).where(CloudRunRecord.attempt_id == attempt.id, CloudRunRecord.run_key == payload.run_key)):
        raise HTTPException(409, "A run key is immutable; reconcile its original operation")
    execution = payload.execution.model_dump(mode="json")
    action = "ci:execute" if payload.execution.source == "CI" else "framework:execute"
    if action not in task.inputs["authorization"]["permitted_actions"]:
        raise HTTPException(403, "Framework execution is outside the frozen allowed actions")
    if payload.execution.framework_sha != task.frozen_manifest["resolution"]["repositories"]["framework"]["commit_sha"]:
        raise HTTPException(422, "Run does not use the frozen framework baseline")
    if payload.execution.entrypoint not in task.inputs["framework_entrypoints"]:
        raise HTTPException(403, "Run entrypoint is outside frozen authorization")
    if task.frozen_manifest["configuration"]["environment"]["require_matching_deployment"]:
        if payload.execution.actual_sut_build == "UNKNOWN" or not payload.execution.environment_observation.get("deployment_matches_expected"):
            raise HTTPException(409, "Required deployment identity was not observed")
    if len({c.case_revision_id for c in payload.cases}) != len(payload.cases):
        raise HTTPException(422, "Duplicate Run case revision")
    for item in payload.cases:
        await _asset(db, task.id, item.case_revision_id, kind="CASE")
    artifacts = [("REPORT", ref) for ref in payload.report_artifact_ids] + [("LOG", ref) for ref in payload.log_artifact_ids]
    for _, ref in artifacts:
        await _artifact(db, task.id, ref)
    run = CloudRunRecord(id=uuid7(), task_id=task.id, attempt_id=attempt.id, task_version=version,
        run_key=payload.run_key, execution=execution, reported_result=payload.reported_result)
    db.add(run)
    await db.flush()
    for role, ref in set(artifacts):
        db.add(CloudRunArtifact(task_id=task.id, run_id=run.id, artifact_id=ref, role=role))
    for item in payload.cases:
        db.add(CloudRunCase(task_id=task.id, run_id=run.id, case_revision_id=item.case_revision_id,
            actual=item.actual, reported_result=item.reported_result))
    return {"run_id": str(run.id)}


async def _delegation(db, task, attempt, payload, version):
    row = await db.scalar(select(CloudDelegation).where(CloudDelegation.attempt_id == attempt.id,
        CloudDelegation.delegation_key == payload.delegation_key))
    if row and (row.status in TERMINAL or row.provider != payload.provider or row.responsibility != payload.responsibility):
        raise HTTPException(409, "Delegation terminal observation and responsibility are immutable")
    if payload.status in TERMINAL and not payload.terminal_observation:
        raise HTTPException(422, "Delegation requires an observable terminal record")
    for ref in payload.asset_ids:
        asset = await _asset(db, task.id, ref)
        if asset.attempt_id != attempt.id:
            raise HTTPException(422, "Delegation output source Attempt mismatch")
    if row is None:
        row = CloudDelegation(id=uuid7(), task_id=task.id, attempt_id=attempt.id,
            delegation_key=payload.delegation_key, provider=payload.provider, responsibility=payload.responsibility)
        db.add(row)
    row.task_version, row.native_ref, row.status, row.terminal_observation = version, payload.native_ref, payload.status, payload.terminal_observation
    await db.flush()
    existing = set(await db.scalars(select(CloudDelegationAsset.asset_id).where(CloudDelegationAsset.delegation_id == row.id)))
    for ref in set(payload.asset_ids) - existing:
        db.add(CloudDelegationAsset(task_id=task.id, delegation_id=row.id, asset_id=ref))
    return {"delegation_id": str(row.id)}


async def _finish(db, task, attempt, payload):
    from .cloud_ssh import ensure_remote_closed
    await ensure_remote_closed(db, task_id=task.id)
    manifest = payload.completion_manifest
    if not manifest.all_local_processes_stopped or not manifest.external_operations_reconciled or manifest.pending_operation_keys:
        raise HTTPException(409, "Completion is blocked by active processes or unresolved external operations")
    if attempt.checkpoint.get("pending_operation_keys"):
        raise HTTPException(409, "Runtime checkpoint still contains unresolved operation keys")
    report = await _asset(db, task.id, payload.final_report_revision, kind="REPORT")
    if report.attempt_id != attempt.id:
        raise HTTPException(422, "Final report must originate from the current Attempt")
    if report.reported_result != payload.reported_result:
        raise HTTPException(409, "Final report and completion reported results disagree")
    kinds = set()
    for ref in manifest.required_asset_ids:
        asset = await _asset(db, task.id, ref)
        if asset.attempt_id != attempt.id:
            raise HTTPException(422, "Completion cannot relabel an old Attempt's required outputs")
        if asset.artifact_id:
            await _artifact(db, task.id, asset.artifact_id)
        kinds.add(asset.kind)
    if not set(task.inputs["expected_outputs"]) <= kinds:
        raise HTTPException(409, "Required stage outputs are missing from the accepted completion manifest")
    if payload.final_report_revision not in manifest.required_asset_ids:
        raise HTTPException(422, "Final report must be an explicit completion asset")
    outstanding = await db.scalar(select(CloudDelegation.id).where(CloudDelegation.attempt_id == attempt.id,
        CloudDelegation.status.not_in(TERMINAL)))
    if outstanding:
        raise HTTPException(409, "A delegated Agent has no observable terminal record")
    runs = list(await db.scalars(select(CloudRunRecord).where(CloudRunRecord.attempt_id == attempt.id)))
    if not runs and not manifest.no_tests_reason:
        raise HTTPException(409, "Completion requires actual Run records or an explicit reason for no testing")
    if not runs and payload.reported_result == "PASS":
        raise HTTPException(409, "No test execution cannot substantiate reported PASS")
    if runs and payload.reported_result == "PASS":
        latest = max(runs, key=lambda run: (run.created_at, run.id))
        if latest.reported_result != "PASS":
            raise HTTPException(409, "Latest execution report cannot substantiate reported PASS")
        contradictory = await db.scalar(select(CloudRunCase.id).where(
            CloudRunCase.run_id == latest.id, CloudRunCase.reported_result.in_(["FAIL", "ERROR", "BLOCKED", "UNKNOWN", "NOT_RUN"])))
        if contradictory:
            raise HTTPException(409, "Latest case observations contradict reported PASS")
    # Reported outcomes are retained; this never creates legacy Evidence/Gate.


async def receipt_view(db, project_id, operation_key, actor_ref=None, *, operator=False):
    # Tombstones stop new admissions, not original-key UNKNOWN reconciliation.
    # Current authorization and the original receipt owner are still required.
    await project(db, project_id, include_deleted=True)
    row = await db.scalar(select(CloudOperationReceipt).where(CloudOperationReceipt.project_id == project_id,
        CloudOperationReceipt.operation_key == operation_key))
    if row is None:
        raise HTTPException(404, "Cloud receipt not found; this does not authorize replay")
    if actor_ref is not None and not operator and row.actor_ref != actor_ref:
        raise HTTPException(403, "Cloud receipt belongs to another submitter")
    return row.response


async def read_task(db, task_id, *, project_id=None, version=None, offset=0, limit=24000):
    task = await _task(db, task_id, project_id)
    if offset < 0 or not 1 <= limit <= 24000 or (offset and version is None):
        raise HTTPException(422, "Continuation requires a fixed version and bounded range")
    selected = version or task.version
    row = await db.scalar(select(CloudOperationReceipt).where(CloudOperationReceipt.task_id == task.id,
        CloudOperationReceipt.accepted_version == selected))
    if not row or not row.task_snapshot:
        raise HTTPException(404, "Accepted Cloud Task version not found")
    content = json.dumps(row.task_snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    end = min(offset + limit, len(content))
    if offset > len(content):
        raise HTTPException(422, "Read offset is beyond the accepted snapshot")
    return {"profile": PROFILE, "task_id": str(task.id), "project_id": str(task.project_id), "version": selected,
        "encoding": "utf-8", "unit": "unicode_characters", "offset": offset, "next_offset": end,
        "total_characters": len(content), "complete": end == len(content), "content": content[offset:end],
        "sha256": hashlib.sha256(content.encode()).hexdigest()}


async def task_summary(db, task_id, *, project_id=None):
    task = await _task(db, task_id, project_id)
    result = public(task)
    attempt = await db.get(CloudAttempt, task.latest_attempt_id) if task.latest_attempt_id else None
    resolutions = await db.scalars(select(CloudInputResolution).where(
        CloudInputResolution.task_id == task.id).order_by(CloudInputResolution.id))
    result.update(task_kind="CLOUD_TASK", product_mode="CLOUD",
        observed_at=(await clock(db)).isoformat(),
        current_attempt=public(attempt) if attempt else None,
        resolutions=[{"id": str(row.id), "status": row.status,
                      "source_draft_version": row.source_draft_version,
                      "accepted_task_version": row.accepted_task_version} for row in resolutions])
    from .cloud_ssh import live_operations
    result["remote_operations"] = await live_operations(db, attempt.id) if attempt else []
    return result


async def configuration(db, project_id):
    await project(db, project_id)
    rows = list(await db.scalars(select(ProjectCloudConfigRevision).where(ProjectCloudConfigRevision.project_id == project_id)
        .order_by(ProjectCloudConfigRevision.revision.desc())))
    return {"items": [public(row) for row in rows]}


async def credentials(db, project_id):
    await project(db, project_id)
    rows = list(await db.scalars(select(ProjectCredential).where(ProjectCredential.project_id == project_id).order_by(ProjectCredential.id)))
    versions = list(await db.scalars(select(CredentialVersion).where(CredentialVersion.project_id == project_id).order_by(CredentialVersion.version)))
    return {"credentials": [public(row) for row in rows], "versions": [public(row) for row in versions]}


async def artifact_bytes(db, project_id, task_id, artifact_id, *, offset=0, length=65536):
    await _task(db, task_id, project_id)
    row = await _artifact(db, task_id, artifact_id)
    if offset < 0 or not 1 <= length <= 65536 or offset > row.byte_count:
        raise HTTPException(422, "Artifact offset exceeds size")
    content = row.content[offset:offset + length]
    return {**public(row), "offset": offset, "content_base64": base64.b64encode(content).decode(),
        "next_offset": offset + len(content), "complete": offset + len(content) == row.byte_count}


async def directory(db, project_id, *, actor_ref, local_allowed, cloud_allowed,
                    operator=False, task_kind=None, product_mode=None, provider=None, offset=0, limit=50):
    await project(db, project_id)
    entries = []
    if cloud_allowed and task_kind in {None, "CLOUD_TASK"} and product_mode in {None, "CLOUD"} and provider in {None, "deepseek"}:
        for row in await db.scalars(select(CloudTask).where(CloudTask.project_id == project_id)):
            entries.append({"task_kind": "CLOUD_TASK", "product_mode": "CLOUD", "task_id": str(row.id),
                "project_id": str(project_id), "title": row.title, "provider": "deepseek", "source": "CLOUD_WORKER",
                "status": row.status, "reported_result": row.reported_result, "version": row.version,
                "updated_at": row.updated_at.isoformat()})
    if local_allowed and task_kind in {None, "SESSION_TASK"} and product_mode in {None, "LOCAL"}:
        query = select(SessionTask).where(SessionTask.project_id == project_id, SessionTask.deleted_at.is_(None))
        if not operator:
            # Match the Local ID-read boundary: precreated tasks have no owner,
            # and only their explicitly intended actor can see them before bind.
            query = query.where(or_(
                and_(SessionTask.binding_state == "BOUND", SessionTask.owner_actor_ref == actor_ref),
                and_(SessionTask.binding_state == "UNBOUND", SessionTask.intended_actor_ref == actor_ref),
            ))
        if provider:
            query = query.where(SessionTask.provider == provider)
        for row in await db.scalars(query):
            entries.append({"task_kind": "SESSION_TASK", "product_mode": "LOCAL", "task_id": str(row.id),
                "project_id": str(project_id), "title": row.title, "provider": row.provider, "source": row.source,
                "binding_state": row.binding_state, "session_id": row.session_id,
                "status": row.status, "reported_result": row.reported_result, "version": row.version,
                "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
                "updated_at": max(stamp for stamp in (row.created_at, row.last_managed_at, row.last_synced_at)
                                  if stamp is not None).isoformat()})
    entries.sort(key=lambda item: (item["updated_at"], item["task_kind"], item["task_id"]), reverse=True)
    return {"items": entries[offset:offset + limit], "total": len(entries), "offset": offset, "limit": limit}


async def claim_attempt(db, worker_id, lease_seconds=90, *, project_id=None):
    """Operational claim; never reclaims an expired active runtime automatically."""
    enabled()
    # A short SKIP LOCKED Task lock serializes with controls and avoids acquiring
    # Attempt before Task, which would invert the mutation lock order.
    query = select(CloudTask).join(CloudAttempt, CloudAttempt.id == CloudTask.latest_attempt_id).where(
        CloudAttempt.status.in_(["QUEUED", "PREPARING"]), CloudAttempt.lease_owner.is_(None)
    )
    if project_id is not None:
        query = query.where(CloudTask.project_id == project_id)
    task = await db.scalar(query.order_by(CloudAttempt.queued_at, CloudAttempt.id)
                           .with_for_update(of=CloudTask, skip_locked=True).limit(1))
    if not task:
        return None
    attempt = await _attempt(db, task, task.latest_attempt_id)
    await _current_grant(db, attempt.authorization_grant_id, task.project_id)
    config = await _configuration(db, task.project_id, task.config_id)
    authorize_cloud_environment(config.configuration)
    now = await clock(db)
    auth_expiry = datetime.fromisoformat(task.inputs["authorization"]["expires_at"].replace("Z", "+00:00"))
    if now >= auth_expiry:
        _state(task, attempt, "CANCELLED", "Execution authorization expired before claim", now)
        await db.commit()
        return None
    _, other_seconds, other_cost = await _task_budget_usage(db, task.id, exclude_attempt_id=attempt.id)
    budgets = task.inputs["budgets"]
    available_seconds = max(0, budgets["total_seconds"] - other_seconds - attempt.usage_seconds)
    available_cost = max(0, budgets["total_cost_microunits"] - other_cost - attempt.cost_microunits)
    if available_seconds < 1 or available_cost < 1:
        _state(task, attempt, "CANCELLED", "Cumulative budget exhausted before claim", now)
        await db.commit()
        return None
    token, work_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    attempt.lease_generation += 1
    attempt.lease_owner, attempt.lease_token_hash = worker_id, token_hash(token)
    attempt.lease_expires_at = min(now + timedelta(seconds=max(15, min(lease_seconds, 900))), auth_expiry)
    if attempt.status == "QUEUED":
        _state(task, attempt, "PREPARING", "Worker claimed", now)
    namespace = f"cloud-{task.id}-{attempt.id}"
    attempt.workspace_id = attempt.workspace_id or namespace
    attempt.runtime_namespace = attempt.runtime_namespace or namespace
    attempt.dsh_home = attempt.dsh_home or namespace + "/dsh-home"
    if not attempt.runtime_metadata.get("preparation_budget_reservation"):
        attempt.runtime_metadata = {**attempt.runtime_metadata, "preparation_budget_reservation": {
            "state": "HELD", "reserved_seconds": min(get_settings().cloud_attempt_timeout_seconds, available_seconds),
            "lease_generation": attempt.lease_generation, "claimed_at": now.isoformat()}}
    db.add(CloudWorkGrant(project_id=task.project_id, attempt_id=attempt.id, token_hash=token_hash(work_token),
        worker_id=worker_id, lease_generation=attempt.lease_generation, expires_at=attempt.lease_expires_at, created_at=now))
    # Claim is operational, so it does not spend an optimistic business version.
    _events(db, task.project_id, "worker:" + worker_id, "CLAIM", task.id,
        {"attempt_id": str(attempt.id), "generation": attempt.lease_generation})
    await db.commit()
    return {"task": public(task), "attempt": public(attempt), "lease_token": token,
        "generation": attempt.lease_generation, "work_token": work_token,
        "budget_remaining": {"seconds": available_seconds, "cost_microunits": available_cost}}


async def renew_lease(db, attempt_id, worker_id, lease_token, generation, work_token, lease_seconds=90):
    attempt_row = await db.get(CloudAttempt, attempt_id)
    if not attempt_row:
        raise HTTPException(404, "Attempt not found")
    task = await _task(db, attempt_row.task_id, lock=True)
    attempt = await _attempt(db, task, attempt_id)
    identity = WorkerIdentity(worker_id, lease_token, generation, work_token)
    await worker_authority(db, task, attempt, identity)
    now = await clock(db)
    expires = datetime.fromisoformat(task.inputs["authorization"]["expires_at"].replace("Z", "+00:00"))
    attempt.lease_expires_at = min(now + timedelta(seconds=max(15, min(lease_seconds, 900))), expires)
    grant = await db.scalar(select(CloudWorkGrant).where(CloudWorkGrant.token_hash == token_hash(work_token)))
    grant.expires_at = attempt.lease_expires_at
    await db.commit()
    return {"expires_at": attempt.lease_expires_at.isoformat(), "generation": generation}


async def claim_resolution(db, worker_id, lease_seconds=90, *, project_id=None):
    enabled()
    query = select(CloudInputResolution).where(CloudInputResolution.status == "PENDING")
    if project_id is not None:
        query = query.where(CloudInputResolution.project_id == project_id)
    row = await db.scalar(query.order_by(CloudInputResolution.created_at, CloudInputResolution.id)
                          .with_for_update(skip_locked=True).limit(1))
    if row is None:
        return None
    await _current_grant(db, row.grant_id, row.project_id)
    task = await _task(db, row.task_id)
    if task.status != "DRAFT" or task.version != row.source_draft_version:
        row.status = "FAILED"
        await db.commit()
        return None
    config = await _configuration(db, row.project_id, task.config_id)
    try:
        _authorize_input_reads(task.inputs, config.configuration, await clock(db))
    except HTTPException:
        row.status = "FAILED"
        await db.commit()
        return None
    token, work_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    row.status, row.worker_id, row.lease_token_hash = "RESOLVING", worker_id, token_hash(token)
    row.lease_expires_at = await clock(db) + timedelta(seconds=max(15, min(lease_seconds, 900)))
    db.add(CloudWorkGrant(project_id=row.project_id, resolution_id=row.id,
        worker_id=worker_id, lease_generation=1, token_hash=token_hash(work_token),
        expires_at=row.lease_expires_at, created_at=await clock(db)))
    await db.commit()
    return {"resolution": public(row), "task": public(task), "configuration": config.configuration,
            "lease_token": token, "work_token": work_token, "generation": 1}


async def accept_resolution(db, resolution_id, worker_id, lease_token, result, *, work_token=None):
    """Worker-only acceptance; I/O happened before entering this transaction."""
    row = await db.get(CloudInputResolution, resolution_id)
    if row is None:
        raise HTTPException(404, "Resolution not found")
    task = await _task(db, row.task_id, lock=True)
    row = await db.scalar(select(CloudInputResolution).where(CloudInputResolution.id == resolution_id).with_for_update())
    # Exact accepted result can be read back after an interrupted response; no
    # repeated parsing or moving-ref resolution is required.
    if row.status == "ACCEPTED":
        if row.worker_id != worker_id or row.lease_token_hash != token_hash(lease_token) or row.digest != canonical_json_sha256(result):
            raise HTTPException(409, "Resolution acceptance conflicts with original result")
        await _current_grant(db, row.grant_id, row.project_id)
        original = await db.scalar(select(CloudOperationReceipt).where(
            CloudOperationReceipt.project_id == row.project_id,
            CloudOperationReceipt.operation_key == "resolution:" + str(row.id)))
        if original is None:
            raise HTTPException(409, "Accepted resolution receipt requires reconciliation")
        return original.response
    await resolution_authority(db, row, worker_id, lease_token, work_token)
    now = await clock(db)
    if row.status != "RESOLVING" or row.worker_id != worker_id or row.lease_token_hash != token_hash(lease_token) or not now < row.lease_expires_at:
        raise HTTPException(409, "Resolution worker ownership is stale")
    await _current_grant(db, row.grant_id, row.project_id)
    if task.status != "DRAFT" or task.version != row.source_draft_version:
        raise HTTPException(409, "DRAFT changed during input resolution")
    config = await _configuration(db, row.project_id, task.config_id)
    _authorize_input_reads(task.inputs, config.configuration, now)
    if canonical_json_sha256({"inputs": task.inputs, "config_id": str(task.config_id), "config_digest": config.digest}) != row.source_digest:
        raise HTTPException(409, "DRAFT resources changed during resolution")
    for role in ("sut", "framework"):
        repository = result.get("repositories", {}).get(role, {})
        sha = repository.get("commit_sha", "")
        if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", sha) or repository.get("url") != config.configuration[role]["url"]:
            raise HTTPException(422, "Resolution must fix both original repositories to complete commit identities")
        selector = task.inputs[role + "_selector"]
        if repository.get("selector") != selector:
            raise HTTPException(422, "Resolution selector differs from the DRAFT")
        if selector["kind"] == "MR":
            if not all(re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", repository.get(key, "")) for key in ("base_sha", "head_sha", "actual_checkout_sha")):
                raise HTTPException(422, "MR resolution requires base/head and actual checkout identity")
            if repository["actual_checkout_sha"] != sha or repository.get("checkout_strategy") != selector["checkout_strategy"]:
                raise HTTPException(422, "MR actual checkout strategy differs from resolved commit")
    if not result.get("observed_at") or not result.get("source") or not result.get("environment_observation"):
        raise HTTPException(422, "Resolution requires observed provenance and explicit environment observation")
    await _reject_secrets(db, row.project_id, result)
    row.result, row.digest, row.status = result, canonical_json_sha256(result), "ACCEPTED"
    row.accepted_task_version = task.version = task.version + 1
    row.accepted_at = task.updated_at = now
    await db.flush()
    response = {"status": "ACCEPTED", "profile": PROFILE, "project_id": str(task.project_id), "task_id": str(task.id),
        "operation": "ACCEPT_RESOLUTION", "operation_key": "resolution:" + str(row.id), "resolution_id": str(row.id), "version": task.version}
    db.add(CloudOperationReceipt(project_id=task.project_id, task_id=task.id, operation_key=response["operation_key"],
        operation="ACCEPT_RESOLUTION", actor_ref="worker:" + worker_id, input_digest=row.digest,
        expected_version=row.source_draft_version, accepted_version=task.version, response=response, task_snapshot=await _snapshot(db, task)))
    _events(db, task.project_id, "worker:" + worker_id, "ACCEPT_RESOLUTION", task.id, response)
    await db.commit()
    return response


async def resolution_authority(db, row, worker_id, lease_token, work_token):
    """INPUT_RESOLUTION authority never authorizes a runtime or test command."""
    now = await clock(db)
    grant = await db.scalar(select(CloudWorkGrant).where(
        CloudWorkGrant.token_hash == token_hash(work_token))) if work_token else None
    if (row.status != "RESOLVING" or row.worker_id != worker_id
            or row.lease_token_hash != token_hash(lease_token)
            or not row.lease_expires_at or now >= row.lease_expires_at
            or not grant or grant.resolution_id != row.id or grant.project_id != row.project_id
            or grant.worker_id != worker_id or grant.revoked_at is not None or now >= grant.expires_at):
        raise HTTPException(409, "Input-resolution capability or lease is stale")
    await _current_grant(db, row.grant_id, row.project_id)


async def _materialize_config_credentials(db, config, project_id, permitted_actions):
    """Private host-only material: caller has already checked the fenced lease."""
    material = {}
    for role, version, credential in await _credential_versions(db, config, now=await clock(db)):
        if version.project_id != project_id:
            raise HTTPException(403, "Credential belongs to another Project")
        required = {"git:read"} if role in {"SUT", "FRAMEWORK"} else {
            action for action in permitted_actions if action.startswith("environment:")
        }
        if role == "ENVIRONMENT" and not required:
            continue
        if not required <= set(credential.allowed_actions):
            raise HTTPException(403, "Credential does not permit frozen resource operations")
        context = {"project_id": str(project_id), "credential_id": str(credential.id),
                   "version": version.version, "purpose": credential.purpose}
        material[role] = _cipher().decrypt(version.encrypted_secret, context=context)
    return material


async def materialize_credentials(db, task_id, attempt_id, identity):
    """Called only by the host Worker, never by an Agent or public read API."""
    task = await _task(db, task_id, lock=True)
    attempt = await _attempt(db, task, attempt_id)
    await worker_authority(db, task, attempt, identity)
    config = await _configuration(db, task.project_id, task.config_id)
    return await _materialize_config_credentials(
        db, config.configuration, task.project_id, task.inputs["authorization"]["permitted_actions"])


async def materialize_resolution_credentials(db, resolution_id, worker_id, lease_token, work_token):
    row = await db.get(CloudInputResolution, resolution_id, populate_existing=True)
    if row is None:
        raise HTTPException(404, "Input resolution not found")
    task = await _task(db, row.task_id)
    await resolution_authority(db, row, worker_id, lease_token, work_token)
    if task.status != "DRAFT" or task.version != row.source_draft_version:
        raise HTTPException(409, "Input-resolution DRAFT changed")
    config = await _configuration(db, row.project_id, task.config_id)
    _authorize_input_reads(task.inputs, config.configuration, await clock(db))
    return await _materialize_config_credentials(db, config.configuration, row.project_id, {"git:read"})


async def expire_leases(db):
    """Fence lost workers; never automatically replay an expired runtime."""
    now = await clock(db)
    tasks = list(await db.scalars(select(CloudTask).join(CloudAttempt, CloudAttempt.id == CloudTask.latest_attempt_id).where(
        CloudAttempt.status.in_(["PREPARING", "RUNNING"]), CloudAttempt.lease_expires_at < now)
        .with_for_update(of=CloudTask, skip_locked=True)))
    for task in tasks:
        attempt = await _attempt(db, task, task.latest_attempt_id)
        await _fence(db, attempt)
        _state(task, attempt, "RECOVERY_REQUIRED", "Worker lease expired; no automatic execution retry", now)
        _events(db, task.project_id, "worker:lease-reconciler", "LEASE_EXPIRED", task.id, {"attempt_id": str(attempt.id)})
    resolutions = list(await db.scalars(select(CloudInputResolution).where(CloudInputResolution.status == "RESOLVING",
        CloudInputResolution.lease_expires_at < now).with_for_update(skip_locked=True)))
    for row in resolutions:
        row.status = "RECOVERY_REQUIRED"
    await db.commit()
    return len(tasks) + len(resolutions)
