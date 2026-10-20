"""Create a reproducible run from the Web's input form in one transaction."""

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.api.schemas import SourceSnapshotCreate
from hypertest.application.policy import compile_policy
from hypertest.application.services import (
    ConflictError,
    NotFoundError,
    canonical_json_sha256,
    source_fingerprint,
)
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.domain.harness_selection import RunHarnessSelection
from hypertest.domain.models import (
    AuditEvent,
    OutboxEvent,
    PolicySnapshot,
    Project,
    SourceSnapshot,
    TestRun,
)
from hypertest.runner.environments import resolve_environment


async def _existing_request(
    session: AsyncSession, project_id: UUID, payload: RunBootstrap,
    source: SourceSnapshotCreate, effective_policy_hash: str,
) -> TestRun | None:
    """A replay uses the original binding, even if a mutable image tag moved."""
    if not payload.idempotency_key:
        return None
    existing = await session.scalar(select(TestRun).where(
        TestRun.project_id == project_id, TestRun.trigger_type == "WEB",
        TestRun.trigger_ref == payload.idempotency_key,
    ))
    if existing is None:
        return None
    selected = await session.get(RunHarnessSelection, existing.id)
    expected = (payload.harness_mode, payload.harness_node_id, payload.source_bundle_transfer_id)
    actual = ((selected.mode, selected.node_id, selected.source_bundle_transfer_id)
              if selected else ("SERVER_HOST", None, None))
    if actual != expected:
        raise ConflictError("idempotency key is already bound to a different Harness selection")
    snapshot = await session.get(SourceSnapshot, existing.source_snapshot_id)
    policy = await session.get(PolicySnapshot, existing.policy_snapshot_id)
    request = payload.environment.model_dump(mode="json", exclude_none=True) if payload.environment else None
    binding = snapshot.environment_definition if snapshot is not None else None
    original_request = binding.get("request") if binding is not None else None
    if (snapshot is None or policy is None or original_request != request
            or snapshot.source_fingerprint != source_fingerprint(
                project_id, source, environment_definition=binding,
            )
            or compile_policy(policy.compiled_policy).effective_policy_hash != effective_policy_hash):
        raise ConflictError("idempotency key is already bound to a different run request")
    return existing


@dataclass(frozen=True)
class PreparedBootstrapInputs:
    input_digest: str
    environment_definition: dict | None
    prd_artifact_uri: str
    configuration_artifact_uri: str


def _preparation_digest(payload: RunBootstrap) -> str:
    return canonical_json_sha256({
        "repository_url": payload.repository_url.strip(), "commit_sha": payload.commit_sha.lower(),
        "prd_text": payload.prd_text, "configuration_text": payload.configuration_text,
        "environment": payload.environment.model_dump(mode="json", exclude_none=True) if payload.environment else None,
        "effective_policy_hash": compile_policy({"gate_version": "mvp/v1", **payload.policy}).effective_policy_hash,
    })


def _materialize_input(content: bytes) -> str:
    """Publish immutable inputs atomically, before any aggregate row lock."""
    root = Path(get_settings().artifact_root).resolve()
    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    if not inputs.resolve().is_relative_to(root):
        raise ValueError("input store must remain under the configured artifact root")
    digest = hashlib.sha256(content).hexdigest()
    target = inputs / f"{digest}.txt"
    if target.is_symlink():
        raise ValueError("input artifact must be a regular file")
    if not target.exists():
        with tempfile.NamedTemporaryFile(dir=inputs, prefix=".input-", delete=False) as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), 0o644)
            output.write(content)
        try:
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    if target.is_symlink() or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise ValueError("existing input artifact failed integrity verification")
    return str(target)


async def prepare_bootstrap_inputs(
    session: AsyncSession, project_id: UUID, payload: RunBootstrap,
) -> PreparedBootstrapInputs:
    """External I/O phase. Call before starting the atomic submission transaction.

    Queued environment resolution uses its existing durable control request and
    may commit this session. Never invoke this with staged receipt/domain writes.
    """
    if session.new or session.dirty or session.deleted:
        raise ValueError("bootstrap preparation requires a session without pending domain writes")
    if await session.scalar(select(Project.id).where(Project.id == project_id)) is None:
        raise NotFoundError("project not found")
    environment_definition = None
    if payload.environment is not None:
        await session.commit()
        try:
            if get_settings().execution_mode == "queued":
                from hypertest.application.runtime_control import request_control

                result = await request_control(session, "RESOLVE_ENVIRONMENT", payload.environment.model_dump(mode="json"))
                environment_definition = result["binding"]
            else:
                environment_definition = await resolve_environment(payload.environment)
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            raise ConflictError("controlled environment unavailable; build the configured profile on this host") from exc
    return PreparedBootstrapInputs(
        input_digest=_preparation_digest(payload), environment_definition=environment_definition,
        prd_artifact_uri=_materialize_input(payload.prd_text.encode("utf-8")),
        configuration_artifact_uri=_materialize_input(payload.configuration_text.encode("utf-8")),
    )


async def bootstrap_run(
    session: AsyncSession, project_id: UUID, payload: RunBootstrap, *,
    commit: bool = True, prepared: PreparedBootstrapInputs | None = None,
) -> TestRun:
    policy_content = {"gate_version": "mvp/v1", **payload.policy}
    compiled_policy = compile_policy(policy_content)
    if not payload.prd_text.strip():
        raise ValueError("PRD text must not be blank")
    prd = payload.prd_text.encode("utf-8")
    digest = hashlib.sha256(prd).hexdigest()
    configuration = payload.configuration_text.encode("utf-8")
    configuration_digest = hashlib.sha256(configuration).hexdigest()
    branch = (payload.branch or "").strip() or None
    source = SourceSnapshotCreate(
        repository_url=payload.repository_url.strip(),
        commit_sha=payload.commit_sha.lower(),
        branch=branch,
        prd_sha256=digest,
        configuration_sha256=configuration_digest,
    )
    existing = await _existing_request(session, project_id, payload, source, compiled_policy.effective_policy_hash)
    if existing is not None:
        if commit:
            await session.commit()
        return existing
    transfer = None
    if payload.harness_mode == "LOCAL_CONNECTOR":
        from hypertest.application.source_transfer import accepted_transfer
        transfer = await accepted_transfer(session, payload.source_bundle_transfer_id,
            project_id=project_id, node_id=payload.harness_node_id,
            origin=source.repository_url, commit_sha=source.commit_sha)
    if prepared is None:
        if not commit:
            raise ValueError("atomic bootstrap requires pre-materialized inputs outside its transaction")
        prepared = await prepare_bootstrap_inputs(session, project_id, payload)
    if prepared.input_digest != _preparation_digest(payload):
        raise ConflictError("prepared inputs do not match the requested immutable bootstrap inputs")
    environment_definition = prepared.environment_definition
    project = await session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise NotFoundError("project not found")
    # Serialize same-key requests after resolution. A racing request may have
    # frozen a different actual image; never replace its first accepted binding.
    existing = await _existing_request(session, project_id, payload, source, compiled_policy.effective_policy_hash)
    if existing is not None:
        if commit:
            await session.commit()
        return existing
    if transfer is not None:
        # Freeze-time authorization, after all external environment I/O. Row
        # locks serialize concurrent node/capability revocation with acceptance.
        from hypertest.connector.security import require_capability
        from hypertest.domain.connector import HarnessNode, NodeProjectCapability
        await session.scalar(select(HarnessNode).where(HarnessNode.id == payload.harness_node_id)
                             .with_for_update().execution_options(populate_existing=True))
        await session.scalars(select(NodeProjectCapability).where(
            NodeProjectCapability.node_id == payload.harness_node_id,
            NodeProjectCapability.project_id == project_id,
            NodeProjectCapability.capability.in_(["harness", "source_acquisition"]))
            .order_by(NodeProjectCapability.id).with_for_update()
            .execution_options(populate_existing=True))
        await require_capability(session, payload.harness_node_id, project_id, "harness")
        transfer = await accepted_transfer(session, payload.source_bundle_transfer_id,
            project_id=project_id, node_id=payload.harness_node_id,
            origin=source.repository_url, commit_sha=source.commit_sha)
    fingerprint = source_fingerprint(project.id, source, environment_definition=environment_definition)
    source.prd_artifact_uri = prepared.prd_artifact_uri
    snapshot = await session.scalar(
        select(SourceSnapshot).where(
            SourceSnapshot.project_id == project.id,
            SourceSnapshot.source_fingerprint == fingerprint,
        )
    )
    if snapshot is None:
        snapshot = SourceSnapshot(
            project_id=project.id, source_fingerprint=fingerprint,
            environment_definition=environment_definition, **source.model_dump()
        )
        session.add(snapshot)
        await session.flush()
    policy_hash = canonical_json_sha256(policy_content)
    policy = await session.scalar(
        select(PolicySnapshot).where(
            PolicySnapshot.project_id == project.id,
            PolicySnapshot.content_sha256 == policy_hash,
        )
    )
    if policy is None:
        policy = PolicySnapshot(
            project_id=project.id,
            policy_name="Web policy",
            policy_version="mvp/v1",
            content_sha256=policy_hash,
            compiled_policy=policy_content,
        )
        session.add(policy)
        await session.flush()
    run = TestRun(
        key=public_key("TR"),
        project_id=project.id,
        source_snapshot_id=snapshot.id,
        policy_snapshot_id=policy.id,
        trigger_type="WEB",
        trigger_ref=payload.idempotency_key,
        created_by="user",
    )
    session.add(run)
    await session.flush()
    if transfer is not None:
        from hypertest.application.source_transfer import link_snapshot
        await link_snapshot(session, transfer, snapshot.id)
        session.add(RunHarnessSelection(test_run_id=run.id, mode="LOCAL_CONNECTOR",
            node_id=payload.harness_node_id, source_bundle_transfer_id=transfer.id))
    session.add(
        AuditEvent(
            project_id=project.id,
            test_run_id=run.id,
            actor_type="USER",
            actor_ref="web",
            action="test_run.created",
            entity_type="TestRun",
            entity_id=run.id,
            after_state={
                "source_snapshot_id": str(snapshot.id),
                "policy_snapshot_id": str(policy.id),
            },
            event_metadata={"channel": "web"},
        )
    )
    session.add(
        OutboxEvent(
            aggregate_type="TestRun",
            aggregate_id=run.id,
            event_type="test_run.created",
            payload={"test_run_id": str(run.id), "source_snapshot_id": str(snapshot.id)},
        )
    )
    if commit:
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        await session.refresh(run)
    else:
        await session.flush()
    return run
