"""Authenticated, scoped source staging and immutable source acceptance."""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import hmac
import os
import secrets
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.source_transfer_schemas import SourceAcquisitionReceipt, SourceTransferCreate
from hypertest.application.services import ConflictError, NotFoundError
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.connector.security import authenticate_device, require_capability, token_hash
from hypertest.connector.source import (
    MAX_BUNDLE_BYTES,
    SourceBundleError,
    materialize,
    verify_bundle,
)
from hypertest.domain.models import AuditEvent, OutboxEvent, Project, SourceSnapshot
from hypertest.domain.source_transfer import (
    SourceAcquisitionRequest,
    SourceBundleTransfer,
    SourceTransferSnapshot,
    SourceUploadGrant,
)
from hypertest.harness_bridge.protocol import BridgeError


def source_root() -> Path:
    root = Path(get_settings().artifact_root).resolve() / "sources"
    if root.is_symlink():
        raise SourceBundleError("source store may not be a symlink")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def source_checkout_root() -> Path:
    """Place accepted Runner inputs inside the existing workspace boundary.

    The Artifact Store owns upload staging and immutable bundles. It may be a
    sibling mount of the workspace volume, so it cannot also own the checkout
    later admitted by persistent_workspace.verify_workspace.
    """
    root = Path(get_settings().workspace_root).resolve() / ".hypertest-source-checkouts"
    if root.is_symlink() or root.resolve() != root:
        raise SourceBundleError("source checkout store may not traverse a symlink")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


MAX_STAGING_BYTES = 4 * MAX_BUNDLE_BYTES
STAGING_RETENTION_SECONDS = 600


def reserve_staging(size: int) -> tuple[int, Path]:
    """Reserve bounded temporary storage across API processes, cleaning crash debris.

    Sparse preallocation makes concurrent reservations visible before a client
    sends bytes. Only receiver-owned staging files can be removed; accepted
    content-addressed bundles, checkouts and Canonical Artifacts are untouched.
    """
    root = source_root()
    directory = root / "staging"
    if directory.resolve() != directory.absolute():
        raise SourceBundleError("unsafe source staging directory")
    directory.mkdir(mode=0o700, exist_ok=True)
    lock = directory / ".quota.lock"
    lock_fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        now, reserved = time.time(), 0
        for path in directory.glob("source-*"):
            if path.is_symlink() or not path.is_file():
                raise SourceBundleError("unexpected source staging entry")
            stat = path.stat()
            if stat.st_mtime < now - STAGING_RETENTION_SECONDS:
                path.unlink()
            else:
                reserved += stat.st_size
        if not 1 <= size <= MAX_BUNDLE_BYTES or reserved + size > MAX_STAGING_BYTES:
            raise ConflictError("source staging quota reached; wait for active uploads or expired staging cleanup")
        descriptor, name = tempfile.mkstemp(prefix="source-", dir=directory)
        try:
            os.ftruncate(descriptor, size)
        except OSError:
            os.close(descriptor)
            Path(name).unlink(missing_ok=True)
            raise
        return descriptor, Path(name)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _event(db, row, action, extra=None):
    state = {"status": row.status, "request_id": str(row.request_id), "node_id": str(row.node_id),
             "bundle_sha256": row.bundle_sha256, **(extra or {})}
    db.add(AuditEvent(project_id=row.project_id, actor_type="SYSTEM", actor_ref="source-receiver",
                      action=action, entity_type="SourceBundleTransfer", entity_id=row.id,
                      after_state=state, event_metadata={"operational": True}))
    db.add(OutboxEvent(aggregate_type="SourceBundleTransfer", aggregate_id=row.id,
                       event_type=action, payload={"transfer_id": str(row.id), **state}))


async def source_scope(db, row):
    scope = await require_capability(db, row.node_id, row.project_id, "source_acquisition")
    if (scope.id != row.source_capability_id or scope.policy_version != row.policy_version
            or row.origin not in scope.constraints.get("allowed_origins", [])):
        raise BridgeError("SOURCE_ACQUISITION_SCOPE_REJECTED")
    return scope


async def create_transfer(db: AsyncSession, project_id: UUID, payload: SourceTransferCreate):
    project = await db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise NotFoundError("project not found")
    scope = await require_capability(db, payload.node_id, project_id, "source_acquisition")
    if payload.policy_version != scope.policy_version or payload.origin not in scope.constraints.get("allowed_origins", []):
        raise ConflictError("source origin/policy is outside the explicitly approved acquisition scope")
    fields = {"project_id": project_id, **payload.model_dump(exclude={"idempotency_key", "request_id"})}
    request = await db.get(SourceAcquisitionRequest, payload.request_id)
    if request is None:
        request = SourceAcquisitionRequest(id=payload.request_id, **fields)
        db.add(request)
        await db.flush()
    elif any(getattr(request, key) != value for key, value in fields.items()):
        raise ConflictError("source request ID already fixes different immutable inputs")
    existing = await db.scalar(select(SourceBundleTransfer).where(
        SourceBundleTransfer.project_id == project_id, SourceBundleTransfer.idempotency_key == payload.idempotency_key))
    if existing:
        if existing.request_id != request.id or any(getattr(existing, key) != value for key, value in fields.items()):
            raise ConflictError("source transfer idempotency key fixes different inputs")
        await db.commit()
        return existing
    now = await db.scalar(select(func.clock_timestamp()))
    row = SourceBundleTransfer(id=uuid7(), request_id=request.id, source_capability_id=scope.id,
        idempotency_key=payload.idempotency_key, **fields, status="UPLOADING", expires_at=now + timedelta(minutes=30))
    db.add(row)
    await db.flush()
    _event(db, row, "source_transfer.created")
    await db.commit()
    return row


async def get_transfer(db, transfer_id):
    row = await db.get(SourceBundleTransfer, transfer_id)
    if row is None:
        raise NotFoundError("source transfer not found")
    return row


async def authorize_upload(db: AsyncSession, transfer_id: UUID, receipt: SourceAcquisitionReceipt, device_token: str):
    row = await db.scalar(select(SourceBundleTransfer).where(SourceBundleTransfer.id == transfer_id).with_for_update())
    if row is None:
        raise NotFoundError("source transfer not found")
    _, device = await authenticate_device(db, device_token, row.node_id)
    await source_scope(db, row)
    now = await db.scalar(select(func.clock_timestamp()))
    if row.status != "UPLOADING" or now >= row.expires_at:
        raise ConflictError("source transfer no longer accepts an upload grant")
    fixed = {"transfer_id": str(row.id), "request_id": str(row.request_id), "project_id": str(row.project_id),
             "node_id": str(row.node_id), "origin": row.origin, "ref": row.ref,
             "commit_sha": row.commit_sha, "policy_version": row.policy_version}
    data = receipt.model_dump(mode="json")
    if any(data[key] != value for key, value in fixed.items()):
        raise ConflictError("source receipt does not match the immutable acquisition request")
    existing = await db.scalar(select(SourceUploadGrant).where(SourceUploadGrant.transfer_id == row.id))
    if existing:
        # Never create another upload identity for uncertain/expired writes.
        raise ConflictError("upload grant already exists; reconcile this transfer or explicitly retry with a new key")
    token = secrets.token_urlsafe(32)
    grant = SourceUploadGrant(transfer_id=row.id, device_grant_id=device.id, token_hash=token_hash(token),
        bundle_sha256=receipt.bundle_sha256, bundle_size=receipt.bundle_size, receipt=data,
        status="ACTIVE", created_at=now, expires_at=min(row.expires_at, device.expires_at, now + timedelta(seconds=120)))
    db.add(grant)
    await db.commit()
    return {"upload_token": token, "expires_at": grant.expires_at.isoformat(), "max_size": grant.bundle_size}


async def validate_upload(db, transfer_id, device_token, upload_token, *, lock=False):
    query = select(SourceBundleTransfer).where(SourceBundleTransfer.id == transfer_id).execution_options(populate_existing=True)
    row = await db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise NotFoundError("source transfer not found")
    _, device = await authenticate_device(db, device_token, row.node_id)
    await source_scope(db, row)
    grant = await db.scalar(select(SourceUploadGrant).where(SourceUploadGrant.transfer_id == row.id).execution_options(populate_existing=True))
    now = await db.scalar(select(func.clock_timestamp()))
    if (not grant or not upload_token or not hmac.compare_digest(grant.token_hash, token_hash(upload_token))
            or grant.device_grant_id != device.id or grant.expires_at <= now or row.expires_at <= now
            or (grant.status != "ACTIVE" and not (grant.status == "CONSUMED" and row.status == "ACCEPTED"))):
        raise BridgeError("SOURCE_TRANSFER_GRANT_REJECTED")
    return row, grant


async def accept_staged_upload(db: AsyncSession, transfer_id: UUID, staging: Path, device_token: str, upload_token: str):
    row, grant = await validate_upload(db, transfer_id, device_token, upload_token, lock=True)
    expected_digest, expected_size = grant.bundle_sha256, grant.bundle_size
    if row.status == "ACCEPTED":
        await db.commit()
        return row
    if row.status != "UPLOADING":
        raise ConflictError("source transfer is already verifying or terminal")
    row.status = "VERIFYING"
    _event(db, row, "source_transfer.verifying")
    await db.commit()
    try:
        # No aggregate locks span object verification or Git/filesystem I/O.
        content = await asyncio.to_thread(staging.read_bytes)
        if len(content) != expected_size or len(content) > MAX_BUNDLE_BYTES or hashlib.sha256(content).hexdigest() != expected_digest:
            raise SourceBundleError("source transfer byte length or digest mismatch")
        verified = await asyncio.to_thread(verify_bundle, content, origin=row.origin, commit_sha=row.commit_sha)
        if verified.manifest["root_tree"] != grant.receipt["root_tree"]:
            raise SourceBundleError("source acquisition receipt root tree mismatch")
        root = source_root()
        bundle = root / "sha256" / expected_digest[:2] / (expected_digest + ".json")
        workspace = source_checkout_root() / expected_digest
        bundle.parent.mkdir(parents=True, exist_ok=True)
        if bundle.is_symlink() or workspace.is_symlink() or not bundle.parent.resolve().is_relative_to(root):
            raise SourceBundleError("unsafe content-addressed source store")
        try:
            with bundle.open("xb") as output:
                output.write(content)
        except FileExistsError:
            if hashlib.sha256(await asyncio.to_thread(bundle.read_bytes)).hexdigest() != expected_digest:
                raise SourceBundleError("stored source bundle integrity mismatch") from None
        await asyncio.to_thread(materialize, verified, workspace)
        bundle.chmod(0o444)
        for base, directories, files in os.walk(workspace):
            for name in files:
                file = Path(base) / name
                file.chmod(0o555 if file.stat().st_mode & 0o111 else 0o444)
            for name in directories:
                (Path(base) / name).chmod(0o555)
        workspace.chmod(0o555)
        row, grant = await validate_upload(db, transfer_id, device_token, upload_token, lock=True)
        if row.status != "VERIFYING":
            raise ConflictError("source acceptance ownership changed")
        # The receipt is authenticated by this exact device grant over HTTPS;
        # capability + policy is separately checked again after all object I/O.
        row.status, row.root_tree = "ACCEPTED", verified.manifest["root_tree"]
        row.object_format = verified.manifest["object_format"]
        row.bundle_sha256, row.bundle_size = expected_digest, expected_size
        row.manifest, row.acquisition_receipt = verified.manifest, {**grant.receipt, "device_grant_id": str(grant.device_grant_id)}
        row.bundle_path, row.server_workspace, row.accepted_at = str(bundle), str(workspace), datetime.now(UTC)
        grant.status = "CONSUMED"
        _event(db, row, "source_transfer.accepted")
        await db.commit()
        return row
    except (SourceBundleError, BridgeError, OSError, ConflictError) as exc:
        await db.rollback()
        row = await db.scalar(select(SourceBundleTransfer).where(SourceBundleTransfer.id == transfer_id).with_for_update())
        if row.status == "VERIFYING":
            row.status, row.error_code = "REJECTED", "SOURCE_VERIFICATION_REJECTED"
            grant = await db.scalar(select(SourceUploadGrant).where(SourceUploadGrant.transfer_id == row.id))
            if grant and grant.status == "ACTIVE":
                grant.status = "REVOKED"
            _event(db, row, "source_transfer.rejected")
            await db.commit()
        raise SourceBundleError("source bundle rejected by independent receiver verification") from exc
    finally:
        staging.unlink(missing_ok=True)


async def accepted_transfer(db: AsyncSession, transfer_id: UUID, project_id: UUID, node_id: UUID, origin: str, commit_sha: str):
    row = await get_transfer(db, transfer_id)
    if (row.status != "ACCEPTED" or row.project_id != project_id or row.node_id != node_id
            or row.origin != origin or row.commit_sha != commit_sha or not row.server_workspace):
        raise ConflictError("accepted source transfer does not match the fixed source and node")
    await source_scope(db, row)
    return row


async def link_snapshot(db: AsyncSession, transfer: SourceBundleTransfer, snapshot_id: UUID):
    snapshot = await db.get(SourceSnapshot, snapshot_id)
    if (not snapshot or transfer.status != "ACCEPTED" or snapshot.project_id != transfer.project_id
            or snapshot.repository_url != transfer.origin or snapshot.commit_sha != transfer.commit_sha):
        raise ConflictError("source transfer cannot link a different frozen snapshot")
    previous = await db.scalar(select(SourceTransferSnapshot).where(SourceTransferSnapshot.source_snapshot_id == snapshot_id))
    if previous:
        first = await db.get(SourceBundleTransfer, previous.transfer_id)
        if first.bundle_sha256 != transfer.bundle_sha256:
            raise ConflictError("snapshot already fixes a different accepted source object")
    if await db.get(SourceTransferSnapshot, (transfer.id, snapshot_id)) is None:
        db.add(SourceTransferSnapshot(transfer_id=transfer.id, source_snapshot_id=snapshot_id))


async def dispatch_source(db: AsyncSession, transfer_id: UUID):
    row = await get_transfer(db, transfer_id)
    await source_scope(db, row)
    if row.status == "ACCEPTED":
        await db.commit()
        return row
    if row.status != "UPLOADING":
        raise ConflictError("source transfer is terminal or requires reconciliation; use an explicit new retry key")
    payload = {"transfer_id": str(row.id), "request_id": str(row.request_id), "project_id": str(row.project_id),
               "node_id": str(row.node_id), "origin": row.origin, "ref": row.ref,
               "commit_sha": row.commit_sha, "policy_version": row.policy_version}
    node_id = row.node_id
    await db.commit()
    # Source acquisition starts only after the trusted Runner's basic preflight;
    # the selected immutable environment is resolved again at bootstrap.
    # Server Harness availability is unrelated to the local source capability.
    try:
        if get_settings().execution_mode == "queued":
            from hypertest.application.runtime_control import request_control
            capabilities = await request_control(db, "CAPABILITIES", {})
            if "docker" not in capabilities.get("runner_backends", []):
                raise ConflictError("trusted Docker Runner is unavailable for source acquisition")
        else:
            from hypertest.runner.backends import DockerRunner
            await DockerRunner().fingerprint()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ConflictError("trusted Runner preflight must succeed before local source acquisition") from exc
    row = await db.get(SourceBundleTransfer, transfer_id, populate_existing=True)
    await source_scope(db, row)
    if row.status != "UPLOADING" or row.expires_at <= await db.scalar(select(func.clock_timestamp())):
        raise ConflictError("source acquisition request changed or expired during Runner preflight")
    await db.commit()
    from hypertest.connector.client import RemoteBridgeClient
    await RemoteBridgeClient(node_id, timeout=120).request("prepare_source", payload)
    row = await db.get(SourceBundleTransfer, transfer_id, populate_existing=True)
    if row.status != "ACCEPTED":
        raise ConflictError("source connector replied before independent acceptance")
    return row
